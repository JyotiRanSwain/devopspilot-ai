# MCP server

Built with the official Python SDK (`mcp` 2.x, `MCPServer`). All tools are read-only (`readOnlyHint: true`) and call the same services as the dashboard.

| Tool | Purpose |
|---|---|
| `list_containers` | Containers with status, health, uptime; optional CPU/memory |
| `get_container_details` | State, restart count, ports, mounts, networks, redacted env |
| `get_container_logs` | Bounded, redacted log window; filter by level/text/time |
| `get_container_stats` | CPU/memory for running containers; unavailable values reported as such |
| `inspect_docker_health` | Docker connectivity, counts, recent incidents |
| `analyze_container_errors` | Rule-based findings with evidence, causes (hypotheses), next steps |
| `get_docker_environment_info` | Engine version, OS, CPUs, memory, counts |
| `search_incident_history` | Search saved incidents |
| `generate_diagnostic_report` | Redacted Markdown or JSON report |

Container arguments must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`; numeric limits are enforced by the schema.

## Run
```powershell
python -m app.mcp.server                                          # stdio
python -m app.mcp.server --transport streamable-http --port 8765  # http://127.0.0.1:8765/mcp
```
In stdio mode nothing is printed to stdout (it carries the protocol); logs go to stderr.

## Client configuration (stdio, e.g. Claude Desktop on Windows)
```json
{
  "mcpServers": {
    "devopspilot": {
      "command": "C:\\path\\to\\devopspilot-ai\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp.server"],
      "cwd": "C:\\path\\to\\devopspilot-ai"
    }
  }
}
```
Restart the client, then ask: "Which of my containers are unhealthy and why?"

## Test
- Automated: `python -m pytest tests/test_mcp.py` (in-memory protocol client against a fake Docker).
- Manual stdio check: use the MCP Inspector (`npx @modelcontextprotocol/inspector python -m app.mcp.server`) and call `inspect_docker_health`.

## Alexa+
The Alexa+ MCP documentation lists Streamable HTTP and a **remote URL** as requirements, and certification criteria around voice and multi-modal behaviour. This server speaks Streamable HTTP, but it is a localhost developer tool with no authentication and no voice-oriented design. It has not been tested with Alexa+ and nothing here claims compatibility. Read the current Alexa+ MCP quickstart before choosing that track.
