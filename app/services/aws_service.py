"""Optional, read-only AWS diagnostics (CloudWatch Logs/metrics/alarms, ECS, EC2). Disabled until configured."""
import re
import time
from typing import Callable, Optional

from app.core.config import Settings
from app.core.redaction import redact

_LOG_GROUP = re.compile(r"^[\w./#-]{1,512}$")
_NAME = re.compile(r"^[\w:/.-]{1,255}$")
_INSTANCE = re.compile(r"^i-[0-9a-f]{8,17}$")

HOW_TO_ENABLE = ("Set DOP_AWS_ENABLED=true and DOP_AWS_REGION. Provide credentials through an IAM role, "
                 "AWS SSO, or a named profile (DOP_AWS_PROFILE). Attach the read-only policy in docs/aws-iam-policy.json.")


class AwsUnavailable(Exception):
    pass


class AwsService:
    def __init__(self, settings: Settings, session_factory: Optional[Callable] = None):
        self._s = settings
        self._session_factory = session_factory
        self._session = None

    def status(self) -> dict:
        if not self._s.aws_enabled:
            return {"enabled": False, "configured": False, "message": "AWS integration is off.", "how_to_enable": HOW_TO_ENABLE}
        if not self._s.aws_region:
            return {"enabled": True, "configured": False, "message": "DOP_AWS_REGION is not set.", "how_to_enable": HOW_TO_ENABLE}
        try:
            creds = self._get_session().get_credentials()
        except Exception as exc:
            return {"enabled": True, "configured": False, "message": f"AWS session failed ({type(exc).__name__}).", "how_to_enable": HOW_TO_ENABLE}
        if creds is None:
            return {"enabled": True, "configured": False, "message": "No AWS credentials were found.", "how_to_enable": HOW_TO_ENABLE}
        return {"enabled": True, "configured": True, "message": f"Ready (region {self._s.aws_region}). Read-only calls only.", "how_to_enable": None}

    def _get_session(self):
        if self._session is None:
            if self._session_factory:
                self._session = self._session_factory()
            else:
                import boto3
                self._session = boto3.Session(profile_name=self._s.aws_profile or None, region_name=self._s.aws_region or None)
        return self._session

    def _client(self, name: str):
        st = self.status()
        if not st["configured"]:
            raise AwsUnavailable(st["message"] + " " + (st["how_to_enable"] or ""))
        return self._get_session().client(name)

    @staticmethod
    def _check(value: str, pattern: re.Pattern, what: str) -> str:
        if not pattern.match(value):
            raise ValueError(f"Invalid {what}.")
        return value

    def log_events(self, log_group: str, filter_pattern: str = "", minutes: int = 30, limit: int = 100) -> dict:
        self._check(log_group, _LOG_GROUP, "log group name")
        client = self._client("logs")
        start = int((time.time() - max(1, min(minutes, 1440)) * 60) * 1000)
        resp = client.filter_log_events(logGroupName=log_group, startTime=start,
                                        filterPattern=filter_pattern[:200], limit=max(1, min(limit, 200)))
        events = [{"timestamp": e["timestamp"], "stream": e.get("logStreamName"), "message": redact(e["message"])[:500]}
                  for e in resp.get("events", [])]
        return {"source": "aws", "service": "cloudwatch-logs", "log_group": log_group, "events": events}

    def alarms(self) -> dict:
        resp = self._client("cloudwatch").describe_alarms(StateValue="ALARM", MaxRecords=50)
        alarms = [{"name": a["AlarmName"], "state": a["StateValue"], "reason": redact(a.get("StateReason", ""))[:300],
                   "metric": a.get("MetricName")} for a in resp.get("MetricAlarms", [])]
        return {"source": "aws", "service": "cloudwatch-alarms", "alarms": alarms}

    def ecs_service(self, cluster: str, service: str) -> dict:
        self._check(cluster, _NAME, "cluster name")
        self._check(service, _NAME, "service name")
        ecs = self._client("ecs")
        svc = ecs.describe_services(cluster=cluster, services=[service]).get("services", [])
        if not svc:
            return {"source": "aws", "service": "ecs", "found": False}
        s = svc[0]
        stopped_arns = ecs.list_tasks(cluster=cluster, serviceName=service, desiredStatus="STOPPED", maxResults=5).get("taskArns", [])
        stopped = []
        if stopped_arns:
            for t in ecs.describe_tasks(cluster=cluster, tasks=stopped_arns).get("tasks", []):
                stopped.append({"stopped_reason": redact(t.get("stoppedReason", "")), "containers": [
                    {"name": c.get("name"), "exit_code": c.get("exitCode"), "reason": redact(c.get("reason", ""))} for c in t.get("containers", [])]})
        return {"source": "aws", "service": "ecs", "found": True, "status": s.get("status"), "desired": s.get("desiredCount"),
                "running": s.get("runningCount"), "pending": s.get("pendingCount"),
                "recent_events": [redact(e.get("message", ""))[:300] for e in s.get("events", [])[:5]], "stopped_tasks": stopped}

    def ec2_status(self, instance_id: str) -> dict:
        self._check(instance_id, _INSTANCE, "instance ID")
        ec2 = self._client("ec2")
        st = ec2.describe_instance_status(InstanceIds=[instance_id], IncludeAllInstances=True).get("InstanceStatuses", [])
        if not st:
            return {"source": "aws", "service": "ec2", "found": False}
        s = st[0]
        return {"source": "aws", "service": "ec2", "found": True, "state": s["InstanceState"]["Name"],
                "instance_check": s.get("InstanceStatus", {}).get("Status"), "system_check": s.get("SystemStatus", {}).get("Status")}
