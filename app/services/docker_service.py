"""Read-only access to the Docker Engine through the official Docker SDK."""
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import docker
from docker.errors import APIError, DockerException, NotFound

from app.core.config import Settings
from app.core.redaction import redact, redact_env
from app.models.schemas import ContainerDetail, ContainerSummary, LogLine, LogWindow

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s?(.*)$", re.S)
_ERROR_RE = re.compile(r"\b(error|err|fatal|critical|panic|exception|traceback|failed|failure|denied|refused)\b", re.I)
_WARN_RE = re.compile(r"\b(warn|warning|deprecated|timeout|timed out|retrying)\b", re.I)
_DEBUG_RE = re.compile(r"\b(debug|trace)\b", re.I)


class DockerUnavailable(Exception):
    """Docker cannot be reached; the message says what to check."""


class ContainerNotFound(Exception):
    pass


def classify_level(text: str) -> str:
    if _ERROR_RE.search(text):
        return "error"
    if _WARN_RE.search(text):
        return "warning"
    if _DEBUG_RE.search(text):
        return "debug"
    return "info"


def parse_docker_time(value: Optional[str]) -> Optional[datetime]:
    """Parse Docker's RFC3339 timestamps (nanosecond precision, 'Z' suffix)."""
    if not value or value.startswith("0001-01-01"):
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})?", value)
    if not match:
        return None
    base, fraction, zone = match.groups()
    fraction = (fraction or "")[:7]
    zone = "+00:00" if zone in (None, "Z") else zone
    return datetime.fromisoformat(f"{base}{fraction}{zone}")


class DockerService:
    def __init__(self, settings: Settings, client_factory: Optional[Callable[[], docker.DockerClient]] = None):
        self._settings = settings
        self._client_factory = client_factory or self._default_factory
        self._client = None

    def _default_factory(self) -> docker.DockerClient:
        if self._settings.docker_host:
            return docker.DockerClient(base_url=self._settings.docker_host, timeout=10)
        return docker.from_env(timeout=10)

    def client(self):
        if self._client is None:
            try:
                client = self._client_factory()
                client.ping()
            except Exception as exc:  # SDK raises DockerException, requests errors, FileNotFoundError...
                raise DockerUnavailable(
                    "Cannot reach the Docker Engine. Start Docker Desktop (or the Docker service) "
                    "and check DOP_DOCKER_HOST if you set it. "
                    f"Detail: {type(exc).__name__}"
                ) from exc
            self._client = client
        return self._client

    def _guard(self, call):
        try:
            return call()
        except NotFound as exc:
            raise ContainerNotFound("Container not found.") from exc
        except (APIError, DockerException) as exc:
            self._client = None
            raise DockerUnavailable(f"Docker returned an error: {type(exc).__name__}") from exc

    # --- containers ---------------------------------------------------------

    def list_containers(self, include_stats: bool = False) -> list[ContainerSummary]:
        def run():
            containers = self.client().containers.list(all=True, limit=self._settings.max_containers)
            result = []
            for c in containers:
                c.reload()
                summary = self._summary(c.attrs)
                if include_stats and summary.status == "running":
                    self._apply_stats(c, summary)
                result.append(summary)
            return result
        return self._guard(run)

    def get_container(self, ref: str, include_stats: bool = True) -> ContainerDetail:
        def run():
            c = self.client().containers.get(ref)
            detail = self._detail(c.attrs)
            if include_stats and detail.status == "running":
                self._apply_stats(c, detail)
            return detail
        return self._guard(run)

    def _summary(self, a: dict) -> ContainerSummary:
        state = a.get("State", {})
        health = (state.get("Health") or {}).get("Status")
        started = parse_docker_time(state.get("StartedAt"))
        uptime = None
        if state.get("Running") and started:
            uptime = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
        status = state.get("Status", "unknown")
        if state.get("Restarting"):
            status = "restarting"
        return ContainerSummary(
            id=a["Id"][:12],
            name=a.get("Name", "").lstrip("/"),
            image=a.get("Config", {}).get("Image", ""),
            status=status,
            health=health,
            uptime_seconds=uptime,
            restart_count=a.get("RestartCount"),
            exit_code=state.get("ExitCode") if status in ("exited", "dead") else None,
        )

    def _detail(self, a: dict) -> ContainerDetail:
        state = a.get("State", {})
        cfg = a.get("Config", {})
        host_cfg = a.get("HostConfig", {})
        ports = {}
        for port, bindings in (a.get("NetworkSettings", {}).get("Ports") or {}).items():
            ports[port] = [f"{b.get('HostIp', '')}:{b.get('HostPort', '')}" for b in bindings or []]
        health_log = [
            redact((entry.get("Output") or "").strip()[:300])
            for entry in (state.get("Health") or {}).get("Log", [])[-3:]
        ]
        cmd = (cfg.get("Entrypoint") or []) + (cfg.get("Cmd") or [])
        return ContainerDetail(
            **self._summary(a).model_dump(),
            full_id=a["Id"],
            created=a.get("Created"),
            started_at=state.get("StartedAt"),
            finished_at=state.get("FinishedAt"),
            error=redact(state.get("Error") or "") or None,
            oom_killed=bool(state.get("OOMKilled")),
            restart_policy=(host_cfg.get("RestartPolicy") or {}).get("Name") or None,
            command=[redact(str(part)) for part in cmd],
            ports=ports,
            env=redact_env(cfg.get("Env")),
            mounts=[f"{m.get('Type')}:{m.get('Destination')} ({'rw' if m.get('RW') else 'ro'})" for m in a.get("Mounts", [])],
            networks=list((a.get("NetworkSettings", {}).get("Networks") or {}).keys()),
            health_log=[h for h in health_log if h],
        )

    # --- stats --------------------------------------------------------------

    def get_stats(self, ref: str) -> dict:
        """Return CPU/memory for a running container; unavailable values are None."""
        def run():
            c = self.client().containers.get(ref)
            holder = ContainerSummary(id=ref, name=ref, image="", status=c.attrs.get("State", {}).get("Status", "unknown"))
            if holder.status != "running":
                return {"available": False, "reason": f"Container is {holder.status}; stats exist only for running containers."}
            self._apply_stats(c, holder)
            if holder.cpu_percent is None and holder.memory_bytes is None:
                return {"available": False, "reason": "Docker returned no usable stats."}
            return {"available": True, "cpu_percent": holder.cpu_percent, "memory_bytes": holder.memory_bytes,
                    "memory_limit_bytes": holder.memory_limit_bytes}
        return self._guard(run)

    @staticmethod
    def _apply_stats(container, target) -> None:
        try:
            s = container.stats(stream=False)
        except Exception:
            return  # leave metrics as None => shown as "unavailable"
        target.cpu_percent = cpu_percent(s)
        mem = s.get("memory_stats") or {}
        if mem.get("usage") is not None:
            stats = mem.get("stats") or {}
            cache = stats.get("inactive_file", stats.get("cache", 0)) or 0
            target.memory_bytes = max(0, mem["usage"] - cache)
            target.memory_limit_bytes = mem.get("limit")

    # --- logs ---------------------------------------------------------------

    def get_log_window(self, ref: str, tail: int = 300, since_minutes: Optional[int] = None) -> LogWindow:
        tail = max(1, min(tail, self._settings.log_max_lines))

        def run():
            c = self.client().containers.get(ref)
            kwargs = {"tail": tail, "timestamps": True, "stdout": True, "stderr": True}
            if since_minutes:
                kwargs["since"] = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
            return c.logs(**kwargs)

        raw: bytes = self._guard(run)
        truncated = False
        limit = self._settings.log_max_bytes
        if len(raw) > limit:
            raw, truncated = raw[-limit:], True
        text = raw.decode("utf-8", errors="replace")
        lines = []
        for i, line in enumerate(l for l in text.splitlines() if l.strip()):
            match = _TS_RE.match(line)
            ts, body = (match.group(1), match.group(2)) if match else (None, line)
            body = redact(body)
            lines.append(LogLine(index=i, timestamp=ts, level=classify_level(body), text=body))
        return LogWindow(container_id=ref, lines=lines, truncated=truncated or len(lines) >= tail, requested_tail=tail)

    # --- engine-level info --------------------------------------------------

    def environment_info(self) -> dict:
        def run():
            c = self.client()
            info, version = c.info(), c.version()
            return {
                "server_version": info.get("ServerVersion"),
                "api_version": version.get("ApiVersion"),
                "operating_system": info.get("OperatingSystem"),
                "architecture": info.get("Architecture"),
                "cpus": info.get("NCPU"),
                "memory_total_bytes": info.get("MemTotal"),
                "containers_total": info.get("Containers"),
                "containers_running": info.get("ContainersRunning"),
                "containers_paused": info.get("ContainersPaused"),
                "containers_stopped": info.get("ContainersStopped"),
                "images": info.get("Images"),
            }
        return self._guard(run)

    def ping(self) -> tuple[bool, str]:
        try:
            self.client()
            return True, "connected"
        except DockerUnavailable as exc:
            return False, str(exc)


def cpu_percent(stats: dict) -> Optional[float]:
    try:
        cpu, pre = stats["cpu_stats"], stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
        sys_delta = cpu["system_cpu_usage"] - pre["system_cpu_usage"]
        cpus = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or []) or 1
        if sys_delta <= 0 or cpu_delta < 0:
            return None
        return round(cpu_delta / sys_delta * cpus * 100.0, 2)
    except (KeyError, TypeError):
        return None
