import asyncio
import json

import pytest
from mcp import Client

from app.mcp.server import build_server

EXPECTED = {"list_containers", "get_container_details", "get_container_logs", "get_container_stats", "inspect_docker_health",
            "analyze_container_errors", "get_docker_environment_info", "search_incident_history", "generate_diagnostic_report"}


def run(coro):
    return asyncio.run(coro)


async def call(services, name, args=None):
    async with Client(build_server(services)) as c:
        return await c.call_tool(name, args or {})


def payload(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def test_all_documented_tools_are_registered_and_read_only(services):
    async def go():
        async with Client(build_server(services)) as c:
            return (await c.list_tools()).tools
    tools = run(go())
    assert {t.name for t in tools} == EXPECTED
    for t in tools:
        assert t.description and t.input_schema["type"] == "object"
        assert t.annotations.read_only_hint is True


def test_schemas_validate_inputs(services):
    async def go():
        async with Client(build_server(services)) as c:
            return {t.name: t.input_schema for t in (await c.list_tools()).tools}
    schemas = run(go())
    logs = schemas["get_container_logs"]
    assert logs["required"] == ["container"] and logs["properties"]["tail"]["maximum"] == 1000
    assert "pattern" in logs["properties"]["container"]


def test_tools_call_real_services(services):
    out = payload(run(call(services, "analyze_container_errors", {"container": "api"})))
    assert out["container"] == "api" and any(f["rule_id"] == "DOP-EXIT-001" for f in out["findings"])
    assert payload(run(call(services, "inspect_docker_health")))["counts"]["total"] == 3
    logs = payload(run(call(services, "get_container_logs", {"container": "api", "level": "error"})))
    assert logs["lines"] and all(l["level"] == "error" for l in logs["lines"])
    assert "hunter2" not in json.dumps(payload(run(call(services, "get_container_details", {"container": "api"}))))
    assert payload(run(call(services, "get_docker_environment_info")))["server_version"] == "27.0"
    assert payload(run(call(services, "get_container_stats", {"container": "web"})))["available"] is True
    assert len(payload(run(call(services, "list_containers", {"status": "exited"})))["containers"]) == 1


def test_report_and_history_tools(services):
    services.incidents.create("Disk full", "web", None, ["e"], [], [])
    assert payload(run(call(services, "search_incident_history", {"query": "disk"})))["incidents"][0]["title"] == "Disk full"
    rep = payload(run(call(services, "generate_diagnostic_report", {"container": "api", "format": "json"})))
    assert json.loads(rep["report"])["resource"] == "api"


def test_missing_container_is_reported_not_crashed(services):
    assert payload(run(call(services, "get_container_details", {"container": "ghost"})))["error"] == "container_not_found"


def test_invalid_arguments_are_rejected(services):
    async def go():
        async with Client(build_server(services)) as c:
            return await c.call_tool("get_container_logs", {"container": "x; rm -rf /"})
    result = run(go())
    assert result.is_error and "should match pattern" in result.content[0].text
