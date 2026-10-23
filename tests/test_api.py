from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.services import build_services
from app.main import create_app
from app.services.docker_service import DockerService


def test_health_and_index(client):
    assert client.get("/api/health").json()["docker"]["connected"] is True
    assert "DevOpsPilot" in client.get("/").text


def test_overview_counts(client):
    o = client.get("/api/overview").json()
    assert o["counts"] == {"total": 3, "running": 1, "stopped": 1, "unhealthy": 0, "restarting": 1}


def test_docker_down_overview_is_200_with_disconnected_state(tmp_path):
    def boom():
        raise ConnectionError("x")
    s = Settings(db_path=str(tmp_path / "d.db"))
    c = TestClient(create_app(s, build_services(s, docker=DockerService(s, client_factory=boom))))
    o = c.get("/api/overview")
    assert o.status_code == 200 and o.json()["docker"]["connected"] is False and o.json()["counts"] is None
    r = c.get("/api/containers")
    assert r.status_code == 503 and r.json()["error"] == "docker_unavailable"


def test_container_filtering(client):
    assert [c["name"] for c in client.get("/api/containers?status=exited").json()["containers"]] == ["api"]
    assert [c["name"] for c in client.get("/api/containers?search=WEB").json()["containers"]] == ["web"]


def test_validation_rejects_bad_ids_and_params(client):
    assert client.get("/api/containers/..%2Fetc").status_code in (404, 422)
    assert client.get("/api/containers/bad id").status_code == 422
    assert client.get("/api/containers/web/logs?tail=999999").status_code == 422
    assert client.get("/api/containers/web/logs?level=nonsense").status_code == 422
    assert client.post("/api/assistant/ask", json={"question": "x"}).status_code == 422
    assert client.get("/api/containers/missing").status_code == 404


def test_logs_filter_pagination_and_links(client):
    d = client.get("/api/containers/api/logs?limit=2").json()
    assert d["total_matching"] == 4 and len(d["lines"]) == 2
    assert any(l["rule_ids"] for l in client.get("/api/containers/api/logs").json()["lines"])
    only_err = client.get("/api/containers/api/logs?level=error").json()
    assert all(l["level"] == "error" for l in only_err["lines"])
    assert client.get("/api/containers/api/logs?search=databasE_url").json()["total_matching"] >= 1


def test_diagnose_and_downloads(client):
    d = client.get("/api/containers/api/diagnose").json()
    assert d["findings"]
    md = client.get("/api/containers/api/report?format=md")
    assert md.headers["content-disposition"].startswith("attachment") and "## Findings" in md.text
    assert "hunter2" not in client.get("/api/containers/api/report?format=json").text
    assert client.get("/api/containers/api/logs/download").headers["content-type"].startswith("text/plain")


def test_auth_required_when_token_set(settings, services):
    s = Settings(db_path=settings.db_path, api_token="secret-token")
    c = TestClient(create_app(s, services))
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer secret-token"}).status_code == 200


def test_request_size_limit(client):
    r = client.post("/api/assistant/ask", content=b"x" * 70_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_cors_only_for_configured_origins(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:8000"})
    bad = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8000"
    assert "access-control-allow-origin" not in bad.headers


def test_unsafe_binding_refused():
    import pytest
    with pytest.raises(SystemExit):
        Settings(host="0.0.0.0", api_token="").check_safe_binding()
    Settings(host="0.0.0.0", api_token="t").check_safe_binding()


def test_incident_flow(client):
    created = client.post("/api/incidents", json={"title": "API crashed", "container_id": "api"}).json()
    iid = created["id"]
    assert created["status"] == "open" and created["findings"]
    assert client.get(f"/api/incidents?q=crashed").json()["incidents"][0]["id"] == iid
    assert client.patch(f"/api/incidents/{iid}/status", json={"status": "resolved"}).status_code == 400
    done = client.patch(f"/api/incidents/{iid}/status", json={"status": "resolved", "confirm": True, "note": "fixed env"}).json()
    assert done["status"] == "resolved" and done["resolved_at"]
    assert "API crashed" in client.get(f"/api/incidents/{iid}/report").text
    assert client.get("/api/incidents/aaaaaaaaaaaa").status_code == 404
    assert client.get("/api/incidents/not-valid").status_code == 422


def test_aws_disabled_by_default(client):
    assert client.get("/api/settings").json()["aws"]["enabled"] is False
    assert client.get("/api/aws/alarms").status_code == 409
