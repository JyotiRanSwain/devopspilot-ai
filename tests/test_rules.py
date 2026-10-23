from app.models.schemas import LogLine
from app.services.diagnostic_engine import analyze
from tests.conftest import make_attrs
from app.services.docker_service import DockerService
from app.core.config import Settings


def detail(**kw):
    return DockerService(Settings(), client_factory=lambda: None)._detail(make_attrs(**kw))


def lines(*texts):
    return [LogLine(index=i, text=t) for i, t in enumerate(texts)]


def ids(findings):
    return {f.rule_id for f in findings}


def test_exit_code_and_meaning():
    f = analyze(detail(name="a", status="exited", exit_code=127), [])
    assert "DOP-EXIT-001" in ids(f) and "not found" in f[0].evidence[0]


def test_clean_exit_has_no_finding():
    assert analyze(detail(name="a", status="exited", exit_code=0), []) == []


def test_oom_confirmed_by_metadata_is_high_confidence():
    f = [x for x in analyze(detail(name="a", status="exited", exit_code=137, oom=True), []) if x.rule_id == "DOP-OOM-001"][0]
    assert f.confidence == "high" and f.severity == "critical"


def test_single_keyword_is_low_confidence():
    f = analyze(None, lines("something said MemoryError once"))
    assert f[0].rule_id == "DOP-OOM-001" and f[0].confidence == "low"


def test_two_independent_signals_raise_confidence():
    f = analyze(None, lines("psycopg2.OperationalError: could not connect to server", "password authentication failed for user x"))
    db = [x for x in f if x.rule_id == "DOP-DB-001"][0]
    assert db.confidence == "medium"


def test_restart_loop():
    f = analyze(detail(name="w", status="restarting", restart_count=12), [])
    r = [x for x in f if x.rule_id == "DOP-RESTART-001"][0]
    assert r.severity == "critical"


def test_unhealthy_redacts_probe_output():
    f = [x for x in analyze(detail(name="w", health="unhealthy"), []) if x.rule_id == "DOP-HEALTH-001"][0]
    assert "hunter2" not in " ".join(f.evidence)


def test_port_conflict_from_docker_error():
    f = analyze(detail(name="w", status="created", error="Bind for 0.0.0.0:80 failed: port is already allocated"), [])
    assert "DOP-PORT-001" in ids(f) and "DOP-START-001" not in ids(f)


def test_missing_env_checks_container_environment():
    d = detail(name="a", env=["OTHER=1"])
    f = [x for x in analyze(d, lines("ERROR environment variable DATABASE_URL is not set")) if x.rule_id == "DOP-ENV-001"][0]
    assert any("DATABASE_URL is not present" in e for e in f.evidence)


def test_env_rule_needs_log_signal():
    assert "DOP-ENV-001" not in ids(analyze(detail(name="a"), lines("see docs: required FOO_BAR")))


def test_dns_proxy_dependency_config():
    f = ids(analyze(None, lines("getaddrinfo ENOTFOUND db", "upstream timed out while reading", "ModuleNotFoundError: No module named x", "yaml.scanner.ScannerError")))
    assert {"DOP-DNS-001", "DOP-PROXY-001", "DOP-DEP-001", "DOP-CFG-001"} <= f


def test_http_5xx_and_4xx():
    logs = ['"GET /a HTTP/1.1" 502 -'] * 3 + ['"GET /b HTTP/1.1" 404 -'] * 5
    f = analyze(None, lines(*logs))
    assert {"DOP-HTTP-5XX", "DOP-HTTP-4XX"} <= ids(f)


def test_log_lines_get_rule_ids_for_linking():
    ls = lines("ok", "getaddrinfo ENOTFOUND db")
    analyze(None, ls)
    assert ls[1].rule_ids == ["DOP-DNS-001"] and ls[0].rule_ids == []


def test_every_finding_has_required_fields():
    for f in analyze(detail(name="w", status="restarting", restart_count=5, health="unhealthy"), lines("FATAL x", "Traceback (most recent call last)")):
        assert f.rule_id.startswith("DOP-") and f.title and f.evidence and f.possible_causes and f.next_steps and f.severity
