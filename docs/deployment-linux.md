# Linux Docker host deployment

1. Install Docker Engine and the Compose plugin; create a non-root user in the `docker` group only if you accept that this is root-equivalent.
2. `git clone <repo> && cd devopspilot-ai && cp .env.example .env`
3. Set `DOP_API_TOKEN` to a long random value: `openssl rand -hex 32`.
4. Optional: `DOP_AI_*`, `DOP_AWS_*` (prefer an instance role over keys).
5. `docker compose up -d --build`
6. Reach it through an HTTPS reverse proxy (Caddy, nginx, Traefik). The compose file publishes only on `127.0.0.1:8000`.
7. Back up the `pilot-data` volume (SQLite database).
8. Firewall: do not expose ports 8000, 8765 or the Docker API to the internet.

Without Compose (systemd):
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
DOP_HOST=127.0.0.1 python -m app
```
The user running it needs read access to `/var/run/docker.sock`; see [security.md](security.md) for what that implies.
