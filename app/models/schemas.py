"""Pydantic models shared by the API, services and MCP tools."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]


class LogLine(BaseModel):
    index: int
    timestamp: Optional[str] = None
    level: Literal["error", "warning", "info", "debug"] = "info"
    text: str
    rule_ids: list[str] = []


class LogWindow(BaseModel):
    container_id: str
    lines: list[LogLine]
    truncated: bool = False  # True when byte/line limits cut the window
    requested_tail: int


class ContainerSummary(BaseModel):
    id: str
    name: str
    image: str
    status: str
    health: Optional[str] = None
    uptime_seconds: Optional[int] = None
    restart_count: Optional[int] = None
    exit_code: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_bytes: Optional[int] = None
    memory_limit_bytes: Optional[int] = None


class ContainerDetail(ContainerSummary):
    full_id: str
    created: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    oom_killed: bool = False
    restart_policy: Optional[str] = None
    command: list[str] = []
    ports: dict[str, list[str]] = {}
    env: list[dict] = []
    mounts: list[str] = []
    networks: list[str] = []
    health_log: list[str] = []


class Finding(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence: list[str]  # verified facts: metadata values and log excerpts
    possible_causes: list[str]  # hypotheses, never proven
    next_steps: list[str]
    commands: list[dict] = []  # read-only commands the user may run: {command, note}
    references: list[str] = []  # e.g. "metadata:State.ExitCode", "log:#12"
    log_refs: list[int] = []
    source: Literal["docker", "aws"] = "docker"


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    container_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CommandSuggestion(BaseModel):
    command: str
    note: str = ""
    destructive: bool = False


class TroubleshootResponse(BaseModel):
    mode: Literal["ai", "rules_only"]
    ai_error: Optional[str] = None
    question: str
    targets: list[str]
    summary: str
    observed_evidence: list[str]  # verified, from Docker/AWS and the rule engine
    findings: list[Finding]
    likely_causes: list[dict]  # {cause, confidence, hypothesis: true}
    investigation_steps: list[str]
    potential_solutions: list[str]
    risks: list[str]
    commands: list[CommandSuggestion]
    information_needed: list[str]
    notice: str = "Nothing was executed. Commands are suggestions to review before you run them."


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    container_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    question: Optional[str] = Field(default=None, max_length=4000)


class StatusUpdate(BaseModel):
    status: Literal["open", "investigating", "resolved"]
    confirm: bool = False  # resolving requires an explicit confirmation
    note: Optional[str] = Field(default=None, max_length=1000)
