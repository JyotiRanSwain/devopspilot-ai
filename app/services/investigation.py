"""Combines Docker evidence with the rule engine. Used by the API, the AI assistant and MCP tools."""
from dataclasses import dataclass
from typing import Optional

from app.models.schemas import ContainerDetail, ContainerSummary, Finding, LogWindow
from app.services import diagnostic_engine
from app.services.docker_service import DockerService, DockerUnavailable
from app.services.incident_service import IncidentService


@dataclass
class Investigation:
    container: ContainerDetail
    window: LogWindow
    findings: list[Finding]


class InvestigationService:
    def __init__(self, docker: DockerService, incidents: Optional[IncidentService] = None):
        self.docker = docker
        self.incidents = incidents

    def investigate(self, ref: str, tail: int = 300, since_minutes: Optional[int] = None) -> Investigation:
        container = self.docker.get_container(ref, include_stats=False)
        window = self.docker.get_log_window(ref, tail=tail, since_minutes=since_minutes)
        findings = diagnostic_engine.analyze(container, window.lines)
        if self.incidents:
            self.incidents.record_activity("diagnose", container.name, f"{len(findings)} finding(s)")
        return Investigation(container, window, findings)

    def problem_containers(self, limit: int = 3) -> list[ContainerSummary]:
        """Containers that are failing right now, worst first."""
        def is_problem(c: ContainerSummary) -> bool:
            return (c.status == "restarting" or c.health == "unhealthy"
                    or (c.status in ("exited", "dead") and c.exit_code not in (0, None)))
        return [c for c in self.docker.list_containers() if is_problem(c)][:limit]

    def overview(self) -> dict:
        connected, message = self.docker.ping()
        data = {"docker": {"connected": connected, "message": message}, "counts": None,
                "recent_incidents": [], "activity": []}
        if self.incidents:
            data["recent_incidents"] = [
                {k: i[k] for k in ("id", "title", "created_at", "status", "resource")} for i in self.incidents.search(limit=5)]
            data["activity"] = self.incidents.recent_activity()
        if connected:
            try:
                containers = self.docker.list_containers()
            except DockerUnavailable as exc:
                data["docker"] = {"connected": False, "message": str(exc)}
                return data
            data["counts"] = {
                "total": len(containers),
                "running": sum(c.status == "running" for c in containers),
                "stopped": sum(c.status in ("exited", "dead", "created") for c in containers),
                "unhealthy": sum(c.health == "unhealthy" for c in containers),
                "restarting": sum(c.status == "restarting" for c in containers),
            }
        return data
