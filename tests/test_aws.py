import pytest

from app.core.config import Settings
from app.services.aws_service import AwsService, AwsUnavailable


class Creds: pass


class FakeSession:
    def __init__(self, creds=Creds()):
        self.creds, self.calls = creds, []

    def get_credentials(self): return self.creds

    def client(self, name):
        outer = self
        class C:
            def filter_log_events(self, **kw):
                outer.calls.append(("filter_log_events", kw))
                return {"events": [{"timestamp": 1, "logStreamName": "s", "message": "boom password=hunter2"}]}
            def describe_alarms(self, **kw):
                outer.calls.append(("describe_alarms", kw))
                return {"MetricAlarms": [{"AlarmName": "cpu", "StateValue": "ALARM", "StateReason": "x", "MetricName": "CPU"}]}
            def describe_instance_status(self, **kw):
                return {"InstanceStatuses": [{"InstanceState": {"Name": "running"}, "InstanceStatus": {"Status": "ok"}, "SystemStatus": {"Status": "ok"}}]}
        return C()


def test_disabled_by_default_with_instructions():
    st = AwsService(Settings()).status()
    assert st["enabled"] is False and "DOP_AWS_ENABLED" in st["how_to_enable"]
    with pytest.raises(AwsUnavailable):
        AwsService(Settings()).alarms()


def test_enabled_needs_region_and_credentials():
    assert "DOP_AWS_REGION" in AwsService(Settings(aws_enabled=True)).status()["message"]
    s = AwsService(Settings(aws_enabled=True, aws_region="ap-south-1"), session_factory=lambda: FakeSession(creds=None))
    assert s.status()["configured"] is False and "credentials" in s.status()["message"]


def test_read_only_calls_and_redaction():
    sess = FakeSession()
    s = AwsService(Settings(aws_enabled=True, aws_region="ap-south-1"), session_factory=lambda: sess)
    out = s.log_events("/ecs/app", "ERROR", minutes=10)
    assert out["source"] == "aws" and "hunter2" not in out["events"][0]["message"]
    assert s.alarms()["alarms"][0]["name"] == "cpu"
    assert s.ec2_status("i-0123456789abcdef0")["state"] == "running"
    assert all(name in {"filter_log_events", "describe_alarms"} for name, _ in sess.calls)


def test_input_validation():
    s = AwsService(Settings(aws_enabled=True, aws_region="x"), session_factory=lambda: FakeSession())
    for bad in (lambda: s.log_events("bad group!"), lambda: s.ec2_status("not-an-instance"), lambda: s.ecs_service("c c", "s")):
        with pytest.raises(ValueError):
            bad()
