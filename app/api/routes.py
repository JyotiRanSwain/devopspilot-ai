"""HTTP API. Thin layer: validation and serialisation only; logic lives in services."""
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from app.core.security import require_auth
from app.core.services import Services
from app.models.schemas import AskRequest, IncidentCreate, StatusUpdate
from app.services import report_service
from app.services.aws_service import AwsUnavailable

CONTAINER_REF = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
router = APIRouter(prefix="/api")
protected = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def svc(request: Request) -> Services:
    return request.app.state.services


@router.get("/health")
def health(s: Services = Depends(svc)):
    ok, message = s.docker.ping()
    return {"status": "ok", "docker": {"connected": ok, "message": message}, "auth_required": bool(s.settings.api_token)}


@protected.get("/overview")
def overview(s: Services = Depends(svc)):
    return s.investigator.overview()


@protected.get("/environment")
def environment(s: Services = Depends(svc)):
    return s.docker.environment_info()


@protected.get("/settings")
def settings_status(s: Services = Depends(svc)):
    st = s.settings
    return {"ai": s.ai.status(), "aws": s.aws.status(),
            "limits": {"log_max_lines": st.log_max_lines, "log_max_bytes": st.log_max_bytes, "max_containers": st.max_containers},
            "auth_required": bool(st.api_token)}


@protected.get("/containers")
def containers(search: str = Query("", max_length=100), status: Optional[str] = Query(None, max_length=20),
               include_stats: bool = False, s: Services = Depends(svc)):
    items = s.docker.list_containers(include_stats=include_stats)
    if search:
        q = search.lower()
        items = [c for c in items if q in c.name.lower() or q in c.image.lower() or c.id.startswith(q)]
    if status:
        items = [c for c in items if c.status == status or (status == "unhealthy" and c.health == "unhealthy")]
    return {"containers": items}


@protected.get("/containers/{ref}")
def container_detail(ref: str = CONTAINER_REF, s: Services = Depends(svc)):
    return s.docker.get_container(ref)


@protected.get("/containers/{ref}/stats")
def container_stats(ref: str = CONTAINER_REF, s: Services = Depends(svc)):
    return s.docker.get_stats(ref)


@protected.get("/containers/{ref}/logs")
def container_logs(ref: str = CONTAINER_REF, tail: int = Query(300, ge=1, le=5000), since_minutes: Optional[int] = Query(None, ge=1, le=10080),
                   search: str = Query("", max_length=200), level: Optional[Literal["error", "warning", "info", "debug"]] = None,
                   limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0), s: Services = Depends(svc)):
    inv = s.investigator.investigate(ref, tail=tail, since_minutes=since_minutes)
    lines = inv.window.lines
    if level:
        lines = [l for l in lines if l.level == level]
    if search:
        q = search.lower()
        lines = [l for l in lines if q in l.text.lower()]
    page = lines[offset:offset + limit]
    return {"container": inv.container.name, "total_matching": len(lines), "offset": offset, "limit": limit,
            "window_truncated": inv.window.truncated, "lines": page, "detected": inv.findings}


@protected.get("/containers/{ref}/logs/download")
def download_logs(ref: str = CONTAINER_REF, tail: int = Query(500, ge=1, le=5000), s: Services = Depends(svc)):
    window = s.docker.get_log_window(ref, tail=tail)
    body = "\n".join(f"{l.timestamp or ''} {l.text}".strip() for l in window.lines)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", ref)
    return Response(body, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{safe}-logs.txt"'})


@protected.get("/containers/{ref}/diagnose")
def diagnose(ref: str = CONTAINER_REF, s: Services = Depends(svc)):
    inv = s.investigator.investigate(ref)
    return {"container": inv.container, "findings": inv.findings, "log_lines_inspected": len(inv.window.lines)}


def _report_response(report: dict, fmt: str, name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    if fmt == "json":
        return Response(report_service.to_json(report), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.json"'})
    return Response(report_service.to_markdown(report), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.md"'})


@protected.get("/containers/{ref}/report")
def container_report(ref: str = CONTAINER_REF, format: Literal["md", "json"] = "md", s: Services = Depends(svc)):
    return _report_response(report_service.from_investigation(s.investigator.investigate(ref)), format, f"report-{ref}")


@protected.post("/assistant/ask")
def ask(body: AskRequest, s: Services = Depends(svc)):
    result = s.ai.ask(body)
    s.incidents.record_activity("assistant", ", ".join(result.targets) or None, f"mode={result.mode}; {len(result.findings)} finding(s)")
    return result


@protected.post("/incidents", status_code=201)
def create_incident(body: IncidentCreate, s: Services = Depends(svc)):
    """Save an incident from a fresh, verified investigation (or an assistant question)."""
    if body.container_id:
        inv = s.investigator.investigate(body.container_id)
        findings = [f.model_dump() for f in inv.findings]
        report = report_service.from_investigation(inv)
        return s.incidents.create(body.title, inv.container.name, body.question, report["evidence"], findings, report["actions"], report["summary"])
    answer = s.ai.ask(AskRequest(question=body.question or body.title))
    return s.incidents.create(body.title, ", ".join(answer.targets) or None, body.question, answer.observed_evidence,
                              [f.model_dump() for f in answer.findings], answer.investigation_steps, answer.summary)


@protected.get("/incidents")
def list_incidents(q: str = Query("", max_length=100), status: Optional[Literal["open", "investigating", "resolved"]] = None,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), s: Services = Depends(svc)):
    return {"incidents": s.incidents.search(q, status, limit, offset)}


@protected.get("/incidents/{incident_id}")
def get_incident(incident_id: str = Path(pattern=r"^[a-f0-9]{12}$"), s: Services = Depends(svc)):
    incident = s.incidents.get(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found.")
    return incident


@protected.patch("/incidents/{incident_id}/status")
def update_status(body: StatusUpdate, incident_id: str = Path(pattern=r"^[a-f0-9]{12}$"), s: Services = Depends(svc)):
    try:
        incident = s.incidents.set_status(incident_id, body.status, body.confirm, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not incident:
        raise HTTPException(404, "Incident not found.")
    return incident


@protected.get("/incidents/{incident_id}/report")
def incident_report(incident_id: str = Path(pattern=r"^[a-f0-9]{12}$"), format: Literal["md", "json"] = "md", s: Services = Depends(svc)):
    incident = s.incidents.get(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found.")
    return _report_response(report_service.from_incident(incident), format, f"incident-{incident_id}")


# --- optional AWS (read-only) --------------------------------------------------

def _aws(call):
    try:
        return call()
    except AwsUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@protected.get("/aws/logs")
def aws_logs(log_group: str = Query(max_length=512), filter_pattern: str = Query("", max_length=200),
             minutes: int = Query(30, ge=1, le=1440), s: Services = Depends(svc)):
    return _aws(lambda: s.aws.log_events(log_group, filter_pattern, minutes))


@protected.get("/aws/alarms")
def aws_alarms(s: Services = Depends(svc)):
    return _aws(s.aws.alarms)


@protected.get("/aws/ecs")
def aws_ecs(cluster: str = Query(max_length=255), service: str = Query(max_length=255), s: Services = Depends(svc)):
    return _aws(lambda: s.aws.ecs_service(cluster, service))


@protected.get("/aws/ec2")
def aws_ec2(instance_id: str = Query(max_length=32), s: Services = Depends(svc)):
    return _aws(lambda: s.aws.ec2_status(instance_id))
