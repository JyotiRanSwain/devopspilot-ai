import pytest

from app.core.config import Settings
from app.services.docker_service import ContainerNotFound, DockerService, DockerUnavailable, cpu_percent, parse_docker_time
from tests.conftest import STATS, FakeClient, FakeContainer, make_attrs


def test_unavailable_docker_gives_helpful_error():
    def boom():
        raise FileNotFoundError("no socket")
    svc = DockerService(Settings(), client_factory=boom)
    with pytest.raises(DockerUnavailable, match="Docker Desktop"):
        svc.list_containers()
    ok, msg = svc.ping()
    assert not ok and "Cannot reach" in msg


def test_list_and_detail(services):
    names = {c.name: c for c in services.docker.list_containers()}
    assert names["web"].uptime_seconds >= 3500 and names["web"].health == "healthy"
    assert names["api"].exit_code == 1 and names["api"].uptime_seconds is None
    detail = services.docker.get_container("api")
    assert {e["name"]: e["value"] for e in detail.env}["DB_PASSWORD"] == "[REDACTED]"


def test_unknown_container(services):
    with pytest.raises(ContainerNotFound):
        services.docker.get_container("nope")


def test_stats_math_and_unavailable_metrics():
    assert cpu_percent(STATS) == 20.0
    assert cpu_percent({}) is None


def test_stats_unavailable_not_fabricated(settings):
    c = FakeContainer(make_attrs("quiet"), stats=None)
    svc = DockerService(settings, client_factory=lambda: FakeClient([c]))
    assert svc.list_containers(include_stats=True)[0].cpu_percent is None
    assert svc.get_stats("quiet")["available"] is False


def test_stopped_container_has_no_stats(services):
    assert services.docker.get_stats("api")["available"] is False


def test_logs_are_bounded_and_redacted(settings):
    big = "\n".join(f"line {i} password=hunter2" for i in range(5000))
    s = Settings(db_path=settings.db_path, log_max_lines=50, log_max_bytes=2000)
    svc = DockerService(s, client_factory=lambda: FakeClient([FakeContainer(make_attrs("x"), big)]))
    w = svc.get_log_window("x", tail=99999)
    assert w.requested_tail == 50 and w.truncated and len(w.lines) < 50
    assert all("hunter2" not in l.text for l in w.lines)


def test_log_levels(services):
    w = services.docker.get_log_window("worker")
    assert [l.level for l in w.lines] == ["error", "error"]


def test_parse_docker_time():
    assert parse_docker_time("2026-10-01T10:00:00.123456789Z").year == 2026
    assert parse_docker_time("0001-01-01T00:00:00Z") is None
