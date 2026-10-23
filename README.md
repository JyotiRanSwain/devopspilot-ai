# DevOpsPilot AI

Monitor Docker containers, read logs, diagnose failures with evidence-backed rules, ask an AI assistant about the evidence, save incidents, export reports, and expose the same read-only tools over MCP.

- Works without an AI key. Docker monitoring and rule-based diagnostics are always available.
- Observed evidence and AI hypotheses are shown separately. Nothing is ever executed for you.
- Secrets are redacted in logs, environment values, incidents, reports and AI prompts.

## Quick start on Windows 11 (PowerShell)

Requires Python 3.12+ and Docker Desktop (running).

```powershell
cd devopspilot-ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m app
```

Open http://127.0.0.1:8000. The pill at the top shows whether Docker is connected.

Create real failing containers to diagnose (optional, removed with the second command):

```powershell
.\scripts\create_demo_containers.ps1
.\scripts\remove_demo_containers.ps1
```

Run the tests (no Docker or cloud account needed):

```powershell
python -m pytest
$env:DOP_INTEGRATION = "1"; python -m pytest -m integration   # needs Docker Desktop
```

## Docker Compose (recommended deployment)

```powershell
Copy-Item .env.example .env      # then set DOP_API_TOKEN to a long random value
docker compose up --build        # dashboard on http://127.0.0.1:8000
docker compose --profile mcp up  # also starts the MCP server on 127.0.0.1:8765
```

The dashboard reads Docker through a read-only socket proxy, not the raw socket. See [docs/security.md](docs/security.md).

## Optional AI

Set in `.env`, then restart:

| Provider | Settings |
|---|---|
| OpenAI-compatible | `DOP_AI_PROVIDER=openai`, `DOP_AI_MODEL=<model>`, `DOP_AI_API_KEY=<key>`, optional `DOP_AI_BASE_URL` |
| Amazon Bedrock | `DOP_AI_PROVIDER=bedrock`, `DOP_AI_MODEL=<model or inference profile ID>`, `DOP_AWS_REGION`, AWS credentials via role, SSO or `DOP_AWS_PROFILE` |

If the provider times out or returns invalid output, the answer falls back to rule-based results and says so.

## Optional AWS (read-only)

Set `DOP_AWS_ENABLED=true`, `DOP_AWS_REGION`, and provide credentials through a role or profile. Attach [docs/aws-iam-policy.json](docs/aws-iam-policy.json). The Integrations page then offers CloudWatch Logs, alarms, ECS service and EC2 status checks. Nothing is created or modified.

## MCP server

```powershell
python -m app.mcp.server                                              # stdio
python -m app.mcp.server --transport streamable-http --port 8765      # http://127.0.0.1:8765/mcp
```

Tools, client configuration and testing: [docs/mcp.md](docs/mcp.md).

## Documentation

- [Architecture](docs/architecture.md) · [Security](docs/security.md) · [MCP](docs/mcp.md)
- [Linux deployment](docs/deployment-linux.md) · [Hackathon notes and demo guide](docs/demo-guide.md)

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Docker disconnected" | Start Docker Desktop, wait for the whale icon to settle, refresh. |
| `Refusing to bind ... without DOP_API_TOKEN` | Set `DOP_API_TOKEN`, or keep `DOP_HOST=127.0.0.1`. |
| Script execution blocked | `Set-ExecutionPolicy -Scope Process Bypass`, then re-run the script. |
| `docker compose` says DOP_API_TOKEN is required | Add it to `.env`. |
| Dashboard asks for a token | Enter the value of `DOP_API_TOKEN` via "Set API token" (kept in session storage). |
| AI says "not configured" | Check the Integrations page for the exact missing setting. |
| Port 8000 busy | Set `DOP_PORT` to another port. |
