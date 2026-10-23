# Security

## What the application does
- Read-only: it calls Docker list, inspect, logs, stats, info and version only. No exec, start, stop or delete.
- Never executes AI-suggested commands and has no shell input. Suggestions are text; commands matching destructive patterns are flagged red.
- Redacts authorization headers, bearer tokens, JWTs, AWS key IDs, GitHub/OpenAI/Slack-style tokens, URL credentials, private keys, cookies, and values of sensitive-looking keys, before display, storage, export, or sending to an AI.
- Environment values are masked when the variable name looks sensitive. Raw logs are not stored in incidents (30 bounded, redacted evidence lines at most).
- Optional bearer token on all `/api` routes except `/api/health`. The server refuses to listen on a non-loopback address without a token.
- CORS limited to `DOP_ALLOWED_ORIGINS`. Request bodies over `DOP_MAX_REQUEST_BYTES` get 413. Inputs validated by pattern and length.
- AWS is off until enabled, uses the default credential chain, and the policy in `aws-iam-policy.json` is read-only. No keys are stored.

## Docker socket access
Anyone who can talk to the Docker socket can usually take over the host (start a privileged container mounting `/`). Mounting it `:ro` does **not** make the API read-only; it only protects the socket file itself.

Compose therefore puts a filtering proxy (`docker-socket-proxy`) in front of the socket with `POST=0`, on an internal network that only the dashboard and MCP services join. The dashboard container has no socket mount. The proxy container still holds the socket, so keep it off any network an untrusted party can reach.

## Before production
- Put the dashboard behind HTTPS (reverse proxy) and a real identity provider; a single shared bearer token is a minimum, not a full access model.
- The MCP streamable HTTP endpoint has no authentication. Keep it on localhost, or place an authenticating gateway in front.
- Pin image tags and dependency versions; run `pip audit` and image scanning.
- Restrict who can read the SQLite volume. Redaction is pattern-based and can miss unusual secret formats; treat logs as sensitive anyway.
- Add rate limiting at the proxy. Request size limits here only check the declared Content-Length.
- Log shipping: this app avoids logging secrets, but verify your proxy does too.
- Any future remediation feature must be separate from diagnosis, authorised per user, and confirmed explicitly.

## Known limitations
Severity detection in logs is keyword-based. Rules are heuristics: findings are hypotheses with a stated confidence, not proof of root cause.
