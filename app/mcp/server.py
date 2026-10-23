"""DevOpsPilot MCP server (official Python MCP SDK 2.x, MCPServer).

stdio (default):      python -m app.mcp.server
streamable HTTP:      python -m app.mcp.server --transport streamable-http --port 8765
Never print to stdout in stdio mode; stdout carries the protocol.
"""
import argparse
import logging
import sys
from typing import Annotated, Literal, Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.core.config import get_settings
from app.core.services import Services, build_services
from app.mcp.tools import DevOpsTools

ContainerRef = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", description="Container name or ID")]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def build_server(services: Optional[Services] = None) -> MCPServer:
    services = services or build_services(get_settings())
    tools = DevOpsTools(services)
    server = MCPServer("devopspilot-ai", instructions=(
        "Read-only Docker diagnostics. Findings are rule-based evidence; causes are hypotheses. "
        "No tool changes containers or cloud resources."))

    @server.tool(annotations=READ_ONLY)
    def list_containers(status: Optional[Literal["running", "exited", "restarting", "paused", "created", "dead"]] = None,
                        include_stats: bool = False) -> dict:
        """List Docker containers with status, health and uptime. include_stats adds CPU/memory (slower)."""
        return tools.list_containers(status, include_stats)

    @server.tool(annotations=READ_ONLY)
    def get_container_details(container: ContainerRef) -> dict:
        """Inspect one container: state, restart count, ports, mounts, networks, and redacted environment."""
        return tools.get_container_details(container)

    @server.tool(annotations=READ_ONLY)
    def get_container_logs(container: ContainerRef, tail: Annotated[int, Field(ge=1, le=1000)] = 100,
                           since_minutes: Annotated[Optional[int], Field(ge=1, le=10080)] = None,
                           level: Optional[Literal["error", "warning", "info", "debug"]] = None,
                           search: Annotated[Optional[str], Field(max_length=200)] = None) -> dict:
        """Fetch a bounded, secret-redacted log window, optionally filtered by level or text."""
        return tools.get_container_logs(container, tail, since_minutes, level, search)

    @server.tool(annotations=READ_ONLY)
    def get_container_stats(container: ContainerRef) -> dict:
        """CPU and memory for a running container; values are null/unavailable when Docker cannot report them."""
        return tools.get_container_stats(container)

    @server.tool(annotations=READ_ONLY)
    def inspect_docker_health() -> dict:
        """Docker connectivity plus container counts (running, stopped, unhealthy, restarting) and recent incidents."""
        return tools.inspect_docker_health()

    @server.tool(annotations=READ_ONLY)
    def analyze_container_errors(container: ContainerRef, tail: Annotated[int, Field(ge=10, le=1000)] = 300) -> dict:
        """Run the deterministic diagnostic rules on a container's metadata and logs. Returns evidence-backed findings."""
        return tools.analyze_container_errors(container, tail)

    @server.tool(annotations=READ_ONLY)
    def get_docker_environment_info() -> dict:
        """Docker engine version, OS, CPU/memory totals and container counts."""
        return tools.get_docker_environment_info()

    @server.tool(annotations=READ_ONLY)
    def search_incident_history(query: Annotated[str, Field(max_length=100)] = "",
                                status: Optional[Literal["open", "investigating", "resolved"]] = None,
                                limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict:
        """Search locally stored incidents by title, resource, summary or finding text."""
        return tools.search_incident_history(query, status, limit)

    @server.tool(annotations=READ_ONLY)
    def generate_diagnostic_report(container: ContainerRef, format: Literal["markdown", "json"] = "markdown") -> dict:
        """Generate a redacted diagnostic report for a container as Markdown or JSON text."""
        return tools.generate_diagnostic_report(container, format)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="DevOpsPilot MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server = build_server()
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
