"""Deterministic diagnostic rules.

Rules read verified evidence (Docker metadata and bounded logs) and return Findings.
They never call an AI provider. A single keyword match is reported as low confidence;
confidence rises only when independent signals, or container metadata, agree.
"""
import re
import shlex
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.models.schemas import ContainerDetail, Finding, LogLine
from app.services.docker_service import parse_docker_time

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
MAX_EVIDENCE_LINES = 6


@dataclass
class Evidence:
    container: Optional[ContainerDetail]
    lines: list[LogLine]


@dataclass(frozen=True)
class Signal:
    label: str
    pattern: re.Pattern


def sig(label: str, regex: str) -> Signal:
    return Signal(label, re.compile(regex, re.I))


def _excerpt(line: LogLine) -> str:
    return f"log #{line.index}: {line.text[:200]}"


def _scan(lines: list[LogLine], signals: list[Signal]) -> dict[str, list[LogLine]]:
    hits: dict[str, list[LogLine]] = {}
    for line in lines:
        for s in signals:
            if s.pattern.search(line.text):
                hits.setdefault(s.label, []).append(line)
    return hits


def _confidence(distinct_signals: int, metadata_support: bool) -> str:
    if metadata_support:
        return "high" if distinct_signals >= 1 or metadata_support == "strong" else "medium"
    return "medium" if distinct_signals >= 2 else "low"


def _cmds(ev: Evidence, *items: tuple[str, str]) -> list[dict]:
    name = shlex.quote(ev.container.name) if ev.container else "<container>"
    return [{"command": cmd.format(c=name), "note": note} for cmd, note in items]


def _signal_rule(rule_id, title, severity, signals, causes, steps, meta=None, commands=(), meta_needs_hits=False):
    """Build a rule from log signals plus an optional metadata corroboration callback."""
    def rule(ev: Evidence) -> Optional[Finding]:
        hits = _scan(ev.lines, signals)
        meta_facts = meta(ev) if meta else []
        if not hits and not meta_facts:
            return None
        if meta_needs_hits and not hits:
            return None
        evidence, refs, log_refs = [], [], []
        evidence.extend(meta_facts)
        for label, matched in hits.items():
            for line in matched[:2]:
                if len(evidence) < MAX_EVIDENCE_LINES + len(meta_facts):
                    evidence.append(_excerpt(line))
                log_refs.append(line.index)
            refs.append(f"signal:{label} ({len(matched)} line{'s' if len(matched) != 1 else ''})")
        support = "strong" if (meta_facts and hits) else bool(meta_facts)
        return Finding(
            rule_id=rule_id, title=title, severity=severity,
            confidence=_confidence(len(hits), support),
            evidence=evidence, possible_causes=list(causes), next_steps=list(steps),
            commands=_cmds(ev, *commands), references=refs,
            log_refs=sorted(set(log_refs)),
        )
    return rule


# --- metadata-driven rules ---------------------------------------------------

_EXIT_MEANING = {
    1: "a generic application error",
    2: "misuse of a shell builtin or a CLI usage error",
    125: "Docker failed to run the container command",
    126: "the command was found but is not executable",
    127: "the command was not found in the image",
    137: "the process was killed with SIGKILL (OOM killer, `docker kill`, or a stop timeout)",
    139: "a segmentation fault (SIGSEGV)",
    143: "the process received SIGTERM (a normal `docker stop`)",
}


def rule_exit(ev: Evidence) -> Optional[Finding]:
    c = ev.container
    if not c or c.status not in ("exited", "dead") or c.exit_code in (None, 0):
        return None
    last_errors = [l for l in ev.lines if l.level == "error"][-2:]
    meaning = _EXIT_MEANING.get(c.exit_code, "a non-zero exit status")
    evidence = [f"metadata: State.ExitCode = {c.exit_code} ({meaning})", f"metadata: State.FinishedAt = {c.finished_at}"]
    evidence += [_excerpt(l) for l in last_errors]
    return Finding(
        rule_id="DOP-EXIT-001", title=f"Container exited with code {c.exit_code}",
        severity="low" if c.exit_code == 143 else "high", confidence="high",
        evidence=evidence,
        possible_causes=["The application crashed or hit a fatal error (see the last error lines)",
                         "The process was stopped externally (manual stop, orchestrator, or resource limit)"],
        next_steps=["Read the last log lines before the exit", "Compare the exit code with the image's entrypoint behaviour",
                    "Check whether the container was stopped by a person or a restart policy"],
        commands=_cmds(ev, ("docker logs --tail 100 {c}", "Last output before exit"),
                       ("docker inspect --format '{{{{json .State}}}}' {c}", "Full exit state")),
        references=["metadata:State.ExitCode", "metadata:State.FinishedAt"],
        log_refs=[l.index for l in last_errors],
    )


_OOM_SIGNALS = [sig("python-memoryerror", r"\bMemoryError\b"), sig("java-oom", r"java\.lang\.OutOfMemoryError"),
                sig("kernel-oom", r"out of memory|oom[- ]kill|Killed process \d+"), sig("node-heap", r"JavaScript heap out of memory")]


def rule_oom(ev: Evidence) -> Optional[Finding]:
    c = ev.container
    hits = _scan(ev.lines, _OOM_SIGNALS)
    meta = []
    if c and c.oom_killed:
        meta.append("metadata: State.OOMKilled = true")
    if c and c.exit_code == 137:
        meta.append("metadata: State.ExitCode = 137")
    if not hits and not (c and c.oom_killed):
        return None
    confirmed = bool(c and c.oom_killed)
    confidence = "high" if confirmed else ("medium" if (hits and meta) else "low")
    evidence = meta + [_excerpt(l) for ls in hits.values() for l in ls[:2]][:MAX_EVIDENCE_LINES]
    return Finding(
        rule_id="DOP-OOM-001", title="Out-of-memory indicators" + (" (kernel OOM kill confirmed by Docker)" if confirmed else ""),
        severity="critical" if confirmed else "high", confidence=confidence, evidence=evidence,
        possible_causes=["The container's memory limit is lower than the workload needs", "A memory leak or unbounded cache",
                         "The host itself is short on memory"],
        next_steps=["Compare memory usage against the container's limit", "Raise the limit only after checking for a leak",
                    "Review recent traffic or data-size changes"],
        commands=_cmds(ev, ("docker stats --no-stream {c}", "Current memory usage"),
                       ("docker inspect --format '{{{{.HostConfig.Memory}}}}' {c}", "Configured memory limit in bytes")),
        references=["metadata:State.OOMKilled"] if confirmed else [], log_refs=[l.index for ls in hits.values() for l in ls],
    )


def rule_restart(ev: Evidence) -> Optional[Finding]:
    c = ev.container
    if not c or not ((c.restart_count or 0) >= 3 or c.status == "restarting"):
        return None
    evidence = [f"metadata: RestartCount = {c.restart_count}", f"metadata: status = {c.status}",
                f"metadata: RestartPolicy = {c.restart_policy or 'none'}"]
    if c.exit_code is not None:
        evidence.append(f"metadata: last ExitCode = {c.exit_code}")
    errors = [l for l in ev.lines if l.level == "error"][-2:]
    evidence += [_excerpt(l) for l in errors]
    return Finding(
        rule_id="DOP-RESTART-001", title="Container is restarting repeatedly",
        severity="critical" if (c.restart_count or 0) >= 10 else "high", confidence="high", evidence=evidence,
        possible_causes=["The main process exits shortly after start (crash, missing config, failed dependency)",
                         "A failing health check combined with an orchestrator restart policy"],
        next_steps=["Find the first error in the logs after each restart", "Check the exit code and health status",
                    "Temporarily stop the restart policy while investigating, after reviewing the impact"],
        commands=_cmds(ev, ("docker logs --tail 200 {c}", "Output across recent restarts"),
                       ("docker inspect --format '{{{{.RestartCount}}}} {{{{.HostConfig.RestartPolicy.Name}}}}' {c}", "Restart count and policy")),
        references=["metadata:RestartCount", "metadata:HostConfig.RestartPolicy"], log_refs=[l.index for l in errors],
    )


def rule_health(ev: Evidence) -> Optional[Finding]:
    c = ev.container
    if not c or c.health != "unhealthy":
        return None
    evidence = ["metadata: State.Health.Status = unhealthy"] + [f"health probe output: {h}" for h in c.health_log]
    return Finding(
        rule_id="DOP-HEALTH-001", title="Health check is failing", severity="high", confidence="high", evidence=evidence,
        possible_causes=["The service is not listening where the health check probes", "The service is up but returning errors",
                         "The health check command itself is wrong or missing a tool in the image"],
        next_steps=["Run the same probe by hand from inside the container", "Compare the probe port/path with what the app serves",
                    "Check whether the app is still starting (start period too short)"],
        commands=_cmds(ev, ("docker inspect --format '{{{{json .State.Health}}}}' {c}", "Recent probe results"),
                       ("docker logs --tail 100 {c}", "Application output")),
        references=["metadata:State.Health"],
    )


def rule_startup_error(ev: Evidence) -> Optional[Finding]:
    """Docker could not create/start the process at all (image, entrypoint, port allocation)."""
    c = ev.container
    if not c or not c.error:
        return None
    err = c.error
    kinds = []
    if re.search(r"port is already allocated|address already in use|Ports are not available|Only one usage of each socket", err, re.I):
        return None  # handled by the port rule
    if re.search(r"pull access denied|manifest unknown|no matching manifest|repository does not exist", err, re.I):
        kinds.append("image could not be pulled or does not match this platform")
    if re.search(r"executable file not found|no such file or directory|exec format error|permission denied", err, re.I):
        kinds.append("the entrypoint/command cannot be executed")
    if re.search(r"OCI runtime", err, re.I):
        kinds.append("the container runtime failed to create the process")
    return Finding(
        rule_id="DOP-START-001", title="Docker reported an error starting the container",
        severity="high", confidence="high" if kinds else "medium",
        evidence=[f"metadata: State.Error = {err[:300]}"],
        possible_causes=kinds or ["See the Docker error message above"] + [
            "Wrong image name, tag, or architecture", "Entrypoint or command missing from the image",
            "Registry login required or rate limit reached"],
        next_steps=["Verify the image name, tag and platform", "Try pulling the image manually", "Check the command/entrypoint in the Dockerfile or compose file"],
        commands=_cmds(ev, ("docker image inspect {image}".replace("{image}", shlex.quote(c.image)), "Confirm the image exists locally"),
                       ("docker inspect --format '{{{{.State.Error}}}}' {c}", "Docker's startup error")),
        references=["metadata:State.Error"],
    )


def _port_meta(ev: Evidence) -> list[str]:
    c = ev.container
    if c and c.error and re.search(r"port is already allocated|address already in use|Ports are not available|Only one usage of each socket", c.error, re.I):
        return [f"metadata: State.Error = {c.error[:300]}"]
    return []


rule_port = _signal_rule(
    "DOP-PORT-001", "Port binding conflict", "high",
    [sig("address-in-use", r"address already in use|EADDRINUSE|Only one usage of each socket"),
     sig("port-allocated", r"port is already allocated|Ports are not available")],
    ["Another process or container already listens on that host port", "A previous instance of this container is still running",
     "The application tries to bind a port that is already used inside the container"],
    ["Identify what owns the port", "Change the host port mapping or stop the other process", "Check for duplicate compose projects"],
    meta=_port_meta,
    commands=[("docker ps --format 'table {{{{.Names}}}}\\t{{{{.Ports}}}}'", "Which containers publish ports"),
              ("docker port {c}", "Port mappings of this container")],
)

# --- log-signal rules --------------------------------------------------------

def _startup_meta(ev: Evidence) -> list[str]:
    c = ev.container
    if not c:
        return []
    start, end = parse_docker_time(c.started_at), parse_docker_time(c.finished_at)
    if c.exit_code not in (None, 0) and start and end and 0 <= (end - start).total_seconds() <= 15:
        return [f"metadata: ran {(end - start).total_seconds():.1f}s before exiting with code {c.exit_code}"]
    return []


rule_startup = _signal_rule(
    "DOP-APP-001", "Application failed during startup", "high",
    [sig("python-traceback", r"Traceback \(most recent call last\)"), sig("fatal", r"\b(fatal|panic)\b"),
     sig("uncaught", r"Unhandled(?:Promise)?Rejection|uncaught exception|Exception in thread \"main\""),
     sig("exception-line", r"^\s*(?:\w+\.)*\w*(?:Error|Exception):")],
    ["An unhandled exception while initialising the app", "A required service or file was unavailable at startup", "A configuration value is invalid"],
    ["Read the first error after the container started, not only the last line", "Check the related findings for configuration and dependency problems"],
    meta=_startup_meta, commands=[("docker logs --tail 200 {c}", "Full startup output")],
)


def _env_meta(ev: Evidence) -> list[str]:
    c = ev.container
    if not c:
        return []
    names = {e["name"] for e in c.env}
    missing = []
    for line in ev.lines:
        if re.search(r"not set|missing|required|undefined|KeyError", line.text, re.I):
            for var in re.findall(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", line.text) + re.findall(r"KeyError: '(\w+)'", line.text):
                if var not in names and var not in missing:
                    missing.append(var)
    return [f"metadata: variable {v} is not present in the container environment (names checked, values not shown)" for v in missing[:4]]


rule_env = _signal_rule(
    "DOP-ENV-001", "Missing or unset environment variable", "high",
    [sig("env-not-set", r"(environment variable|env var)\b.{0,60}(not set|missing|required|undefined|not defined)"),
     sig("var-not-set", r"\b[A-Z][A-Z0-9_]{2,}\b.{0,20}\b(is|are) (not set|required|missing|undefined)"),
     sig("python-keyerror-env", r"KeyError: '[A-Z][A-Z0-9_]+'"),
     sig("missing-config", r"missing (required )?(environment|env|config)")],
    ["The variable is not passed in compose/`docker run -e`", "The .env file is not loaded or has a typo in the name", "A secret was not provisioned in this environment"],
    ["Compare the variable name with the app's documentation", "Check the compose `environment:`/`env_file:` section", "Never paste real secret values into tickets or chat"],
    meta=_env_meta, meta_needs_hits=True, commands=[("docker inspect --format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' {c}", "Environment (review before sharing: may contain secrets)")],
)

rule_database = _signal_rule(
    "DOP-DB-001", "Database connectivity or authentication problem", "high",
    [sig("conn-refused-db", r"(connection refused|ECONNREFUSED).{0,80}(5432|3306|27017|6379|1433)|(5432|3306|27017|6379|1433).{0,80}(connection refused|ECONNREFUSED)"),
     sig("pg-connect", r"could not connect to server|psycopg2\.OperationalError|asyncpg\.\w*Error|PostgreSQL.*(refused|unavailable)"),
     sig("mysql-connect", r"Can't connect to MySQL|ER_ACCESS_DENIED|Access denied for user|Unknown database|Too many connections"),
     sig("auth-failed", r"password authentication failed|no pg_hba\.conf entry|authentication failed for user"),
     sig("mongo-redis", r"MongoServerSelectionError|MongoNetworkError|Redis.{0,40}(refused|ECONNREFUSED)|NOAUTH"),
     sig("db-missing", r"database \".+\" does not exist")],
    ["The database container is down, still initialising, or unhealthy", "The app uses `localhost` instead of the database's service name",
     "Wrong credentials, database name or host in the connection string", "The two containers are not on the same Docker network"],
    ["Check the database container's status and health first", "Confirm the hostname resolves from the app's network", "Verify credentials by name (never paste the password)",
     "Use a compose health check and `depends_on: condition: service_healthy`"],
    commands=[("docker ps -a", "Is the database container running?"), ("docker network ls", "Which networks exist"),
              ("docker inspect --format '{{{{json .NetworkSettings.Networks}}}}' {c}", "Networks this container is attached to")],
)

rule_dns = _signal_rule(
    "DOP-DNS-001", "DNS resolution failure", "medium",
    [sig("name-not-known", r"Name or service not known|Temporary failure in name resolution"),
     sig("node-dns", r"getaddrinfo (ENOTFOUND|EAI_AGAIN)|ENOTFOUND"), sig("go-dns", r"no such host|lookup .+ on .+:53")],
    ["The hostname is misspelled or does not exist", "The service name is only resolvable on a different Docker network",
     "The host's DNS server is unreachable from the container"],
    ["Check the hostname spelling", "Confirm both containers share a user-defined network", "Test resolution from inside the container"],
    commands=[("docker inspect --format '{{{{json .NetworkSettings.Networks}}}}' {c}", "Attached networks"),
              ("docker exec {c} getent hosts <hostname>", "Resolve a name from inside (replace <hostname>; requires the tool in the image)")],
)

rule_network = _signal_rule(
    "DOP-NET-001", "Network connectivity failure", "medium",
    [sig("timeout", r"connection timed out|ETIMEDOUT|i/o timeout|context deadline exceeded|read timed out"),
     sig("unreachable", r"No route to host|network is unreachable|EHOSTUNREACH"), sig("reset", r"connection reset by peer|ECONNRESET")],
    ["A firewall or security group blocks the destination", "The target service is overloaded or down", "Wrong IP/port, or the container lacks outbound access"],
    ["Test reachability of the target from the host and from the container", "Check firewall and security group rules", "Look for matching errors in the target service's logs"],
    commands=[("docker inspect --format '{{{{json .NetworkSettings.Networks}}}}' {c}", "Network attachment")],
)

rule_proxy = _signal_rule(
    "DOP-PROXY-001", "Reverse proxy cannot reach the upstream", "high",
    [sig("nginx-upstream", r"upstream (timed out|prematurely closed)|connect\(\) failed \(111: Connection refused\)|no live upstreams"),
     sig("bad-gateway", r"502 Bad Gateway|504 Gateway Time-?out"), sig("traefik-haproxy", r"Bad Gateway|backend .+ has no server available|NOSRV")],
    ["The upstream container is down, restarting or unhealthy", "The proxy points to the wrong host or port", "The upstream is too slow and the proxy timeout is shorter"],
    ["Check that the upstream container is running and healthy", "Verify the upstream address in the proxy config",
     "Compare proxy timeouts with the upstream's response time", "Review the upstream's own logs at the same time"],
    commands=[("docker ps -a", "Upstream status"), ("docker logs --tail 100 {c}", "Proxy output")],
)

rule_dependency = _signal_rule(
    "DOP-DEP-001", "Missing dependency or module", "high",
    [sig("python-import", r"ModuleNotFoundError|ImportError|No module named"), sig("node-module", r"Cannot find module|MODULE_NOT_FOUND"),
     sig("java-class", r"ClassNotFoundException|NoClassDefFoundError"), sig("shared-lib", r"error while loading shared libraries")],
    ["The image was built without installing the dependency", "A version mismatch between build and runtime environments", "A bind mount hides the installed packages"],
    ["Check the dependency list used for the image build", "Rebuild the image without cache after fixing it", "Look for volume mounts that overlay the app directory"],
    commands=[("docker history {c}".replace("{c}", "<image>"), "Review image layers (replace <image>)")],
)

rule_config = _signal_rule(
    "DOP-CFG-001", "Invalid or unreadable configuration", "medium",
    [sig("yaml", r"yaml\.(scanner|parser)|YAMLError"), sig("json", r"JSONDecodeError|Unexpected token .* in JSON"),
     sig("invalid-config", r"invalid (configuration|config|setting|value)|failed to (load|parse) (config|configuration)"),
     sig("file-missing", r"(config|\.conf|\.ya?ml|\.json|\.ini).{0,40}No such file or directory")],
    ["A syntax error in a mounted config file", "A config file path that does not exist in the container", "A value of the wrong type or range"],
    ["Validate the config file syntax locally", "Confirm the mount path and file permissions", "Diff against the last known-good config"],
    commands=[("docker inspect --format '{{{{json .Mounts}}}}' {c}", "Mounted files and directories")],
)

_ACCESS_RE = re.compile(r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)[^"]*"\s+(\d{3})\b')
_JSON_STATUS_RE = re.compile(r'"status(?:_code)?"\s*:\s*(\d{3})')


def _http_codes(lines: list[LogLine]) -> list[tuple[int, int, str]]:
    found = []
    for line in lines:
        m = _ACCESS_RE.search(line.text)
        if m:
            found.append((line.index, int(m.group(2)), m.group(1)))
            continue
        m = _JSON_STATUS_RE.search(line.text)
        if m:
            found.append((line.index, int(m.group(1)), ""))
    return found


def rule_http(ev: Evidence) -> list[Finding]:
    codes = _http_codes(ev.lines)
    findings = []
    server_errors = [x for x in codes if 500 <= x[1] <= 599]
    client_errors = [x for x in codes if 400 <= x[1] <= 499]
    total = len(codes)
    if server_errors:
        counts: dict[int, int] = {}
        for _, code, _ in server_errors:
            counts[code] = counts.get(code, 0) + 1
        evidence = [f"{total} HTTP requests parsed from logs; 5xx: " + ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))]
        evidence += [_excerpt(ev.lines[i]) for i, _, _ in server_errors[:3]]
        gateway = any(c in (502, 503, 504) for c in counts)
        findings.append(Finding(
            rule_id="DOP-HTTP-5XX", title="HTTP 5xx responses in logs", severity="high",
            confidence="medium" if len(server_errors) >= 3 else "low", evidence=evidence,
            possible_causes=(["The upstream service behind this proxy is unavailable or slow"] if gateway else [])
            + ["An unhandled exception in the application", "A failing dependency (database, cache, external API)"],
            next_steps=["Match 5xx timestamps with application errors", "Check whether the 5xx started after a deployment", "Look at upstream/dependency health"],
            commands=_cmds(ev, ("docker logs --since 30m {c}", "Last 30 minutes of output")),
            references=[f"http:{k}" for k in counts], log_refs=[i for i, _, _ in server_errors],
        ))
    if len(client_errors) >= 5:
        counts = {}
        for _, code, _ in client_errors:
            counts[code] = counts.get(code, 0) + 1
        findings.append(Finding(
            rule_id="DOP-HTTP-4XX", title="Many HTTP 4xx responses in logs", severity="low", confidence="medium",
            evidence=[f"{len(client_errors)} of {total} parsed requests returned 4xx: " + ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))]
            + [_excerpt(ev.lines[i]) for i, _, _ in client_errors[:2]],
            possible_causes=["Broken links or a client calling a removed route (404)", "Expired or missing credentials (401/403)", "Clients sending invalid payloads (400/422)"],
            next_steps=["Group the failing paths and see whether one client causes them", "Check recent API or routing changes"],
            references=[f"http:{k}" for k in counts], log_refs=[i for i, _, _ in client_errors],
        ))
    return findings


RULES: list[Callable[[Evidence], object]] = [
    rule_exit, rule_oom, rule_restart, rule_health, rule_startup_error, rule_port, rule_startup, rule_env,
    rule_database, rule_dns, rule_network, rule_proxy, rule_dependency, rule_config, rule_http,
]


def analyze(container: Optional[ContainerDetail], lines: list[LogLine]) -> list[Finding]:
    """Run every rule; return findings ordered by severity then confidence. Also tags log lines."""
    ev = Evidence(container, lines)
    findings: list[Finding] = []
    for rule in RULES:
        result = rule(ev)
        if result is None:
            continue
        findings.extend(result if isinstance(result, list) else [result])
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], CONFIDENCE_ORDER[f.confidence]))
    by_index = {l.index: l for l in lines}
    for f in findings:
        for i in f.log_refs:
            if i in by_index and f.rule_id not in by_index[i].rule_ids:
                by_index[i].rule_ids.append(f.rule_id)
    return findings
