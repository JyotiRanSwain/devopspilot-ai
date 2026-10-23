"""Wires services together once; shared by the web app and the MCP server."""
from dataclasses import dataclass
from typing import Optional

from app.core.config import Settings
from app.services.ai_service import AIService
from app.services.aws_service import AwsService
from app.services.docker_service import DockerService
from app.services.incident_service import IncidentService
from app.services.investigation import InvestigationService


@dataclass
class Services:
    settings: Settings
    docker: DockerService
    incidents: IncidentService
    investigator: InvestigationService
    ai: AIService
    aws: AwsService


def build_services(settings: Settings, docker: Optional[DockerService] = None, ai: Optional[AIService] = None,
                   aws: Optional[AwsService] = None) -> Services:
    docker = docker or DockerService(settings)
    incidents = IncidentService(settings.db_path)
    investigator = InvestigationService(docker, incidents)
    return Services(settings, docker, incidents, investigator, ai or AIService(settings, investigator), aws or AwsService(settings))
