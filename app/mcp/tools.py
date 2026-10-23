"""MCP tool implementations. Each calls the same real backend services as the dashboard.

Every tool is read-only. Failures are returned as {"error": ...} so an MCP client can show them.
"""
from typing import Callable

from app.core.services import Services
from app.services import report_service
from app.services.docker_service import ContainerNotFound, DockerUnavailable


def _safe(fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except DockerUnavailable as exc:
        return {"error": "docker_unavailable", "message": str(exc)}
    except ContainerNotFound as exc:
        return {"error": "container_not_found", "message": str(exc)}


class DevOpsTools:
    def __init__(self, services: Services):
        self.s = services

    def list_containers(self, status: str | None = None, include_stats: bool = False) -> dict:
        def run():
            items = self.s.docker.list_containers(include_stats=include_stats)
            if status:
                items = [c for c in items if c.status == status]
            return {"containers": [c.model_dump() for c in items]}
        return _safe(run)

    def get_container_details(self, container: str) -> dict:
        return _safe(lambda: self.s.docker.get_container(container).model_dump())

    def get_container_logs(self, container: str, tail: int = 100, since_minutes: int | None = None,
                           level: str | None = None, search: str | None = None) -> dict:
        def run():
            window = self.s.docker.get_log_window(container, tail=tail, since_minutes=since_minutes)
            lines = window.lines
            if level:
                lines = [l for l in lines if l.level == level]
            if search:
                lines = [l for l in lines if search.lower() in l.text.lower()]
            return {"container": container, "truncated": window.truncated, "lines": [l.model_dump(exclude={"rule_ids"}) for l in lines]}
        return _safe(run)

    def get_container_stats(self, container: str) -> dict:
        return _safe(lambda: self.s.docker.get_stats(container))

    def inspect_docker_health(self) -> dict:
        return _safe(lambda: self.s.investigator.overview())

    def analyze_container_errors(self, container: str, tail: int = 300) -> dict:
        def run():
            inv = self.s.investigator.investigate(container, tail=tail)
            return {"container": inv.container.name, "status": inv.container.status, "log_lines_inspected": len(inv.window.lines),
                    "findings": [f.model_dump() for f in inv.findings],
                    "note": "Findings are rule-based. Causes are hypotheses, not proven root causes."}
        return _safe(run)

    def get_docker_environment_info(self) -> dict:
        return _safe(self.s.docker.environment_info)

    def search_incident_history(self, query: str = "", status: str | None = None, limit: int = 10) -> dict:
        found = self.s.incidents.search(query, status, limit)
        return {"incidents": [{k: i[k] for k in ("id", "title", "created_at", "status", "resource", "summary")} for i in found]}

    def generate_diagnostic_report(self, container: str, format: str = "markdown") -> dict:
        def run():
            report = report_service.from_investigation(self.s.investigator.investigate(container))
            body = report_service.to_json(report) if format == "json" else report_service.to_markdown(report)
            return {"format": format, "report": body}
        return _safe(run)
