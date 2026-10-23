import json

from app.services import report_service
from app.services.incident_service import IncidentService


def test_incident_persistence_across_instances(tmp_path):
    path = str(tmp_path / "x.db")
    first = IncidentService(path).create("Crash", "api", "why", ["e1"], [{"rule_id": "R", "evidence": ["x"]}], ["a1"])
    again = IncidentService(path).get(first["id"])
    assert again["title"] == "Crash" and again["findings"][0]["rule_id"] == "R"


def test_secrets_and_size_limits_in_storage(tmp_path):
    s = IncidentService(str(tmp_path / "x.db"))
    inc = s.create("t password=abc", "r", "token=zzz1234", ["line password=hunter2 " + "x" * 1000] * 100, [], [])
    assert len(inc["evidence"]) == 30 and all(len(e) <= 300 for e in inc["evidence"])
    assert "hunter2" not in json.dumps(inc) and "abc" not in inc["title"]


def test_search_and_status(tmp_path):
    s = IncidentService(str(tmp_path / "x.db"))
    a = s.create("Redis timeout", "cache", None, [], [], [])
    s.create("Nginx 502", "proxy", None, [], [], [])
    assert [i["id"] for i in s.search("redis")] == [a["id"]]
    assert s.search("", status="resolved") == []
    try:
        s.set_status(a["id"], "resolved", False, None)
        assert False
    except ValueError:
        pass
    assert s.set_status(a["id"], "resolved", True, "done")["status"] == "resolved"
    assert s.set_status("nope", "open", False, None) is None


def test_activity_log(tmp_path):
    s = IncidentService(str(tmp_path / "x.db"))
    s.record_activity("diagnose", "api", "2 findings")
    assert s.recent_activity()[0]["target"] == "api"


def test_reports_markdown_json_and_redaction(services):
    inv = services.investigator.investigate("api")
    report = report_service.from_investigation(inv)
    report["evidence"].append("Authorization: Bearer abcdef1234567890")
    md, js = report_service.to_markdown(report), report_service.to_json(report)
    assert "# Diagnostic report: api" in md and "Possible causes (hypotheses)" in md
    assert "abcdef1234567890" not in md + js and json.loads(js)["resource"] == "api"


def test_incident_report_shows_user_confirmed_status(tmp_path):
    s = IncidentService(str(tmp_path / "x.db"))
    i = s.create("T", "r", None, ["e"], [], ["step"])
    md = report_service.to_markdown(report_service.from_incident(i))
    assert "Status: open" in md and "step" in md
