# Hackathon notes and demo guide

## Deadline (check the official page, times can change)
Amazon Developer Hackathon "Build, Ship, Shape" listed the submission deadline as **23 October 2026, 12:00 PM PT**. That is **12:30 AM IST on 24 October**. Confirm on the official page and read the track rules before submitting.

## Track fit (be honest in the submission)
- The Alexa+ track is described as Agent Skills, MCP-based experiences or simulated Alexa+ experiences. Alexa+ MCP requires Streamable HTTP and a remote URL, and certification looks at voice and multi-modal behaviour. This project's MCP server supports Streamable HTTP but has not been tested with Alexa+. Do not claim Alexa+ compatibility.
- Amazon Bedrock is supported as the AI provider (`DOP_AI_PROVIDER=bedrock`), AWS read-only diagnostics are optional, and the project is a developer tool, so describe it as such and pick the track the official rules say fits.

## Before recording (10 minutes)
1. `python -m app` (or `docker compose up --build`), open http://127.0.0.1:8000.
2. `.\scripts\create_demo_containers.ps1` to create real failing containers. Say on camera that they are demo containers created by a script.
3. Optional AI: configure Bedrock or an OpenAI-compatible key in `.env` and restart. If you skip it, show the "rules only" mode honestly.
4. Close other windows, set the browser zoom to 110%, hide bookmarks and tokens. Make sure no real secrets appear on screen.

## 3-minute script
| Time | Show | Say |
|---|---|---|
| 0:00 | Overview page | "Engineers lose time jumping between docker logs, inspect and guesswork. DevOpsPilot reads real Docker data and explains failures with evidence." |
| 0:20 | Containers table, filter `exited` | Real status, health, uptime. Point out "unavailable" for metrics Docker did not report. |
| 0:40 | Open `dop-demo-crash`, Run diagnostics | Show the green "Observed evidence" block versus the dashed "hypotheses" block. Mention confidence. |
| 1:10 | Log explorer: filter errors, click a rule tag | Jumps from log line to the finding. Mention redaction and bounded retrieval. |
| 1:30 | Assistant: "Why is my Docker container restarting repeatedly?" | Evidence is collected first. AI (or rules) explain; commands are copy-only, nothing executes. |
| 2:00 | Save as incident, mark resolved (confirm dialog), download report | Incident history, Markdown/JSON report, secrets redacted. |
| 2:20 | MCP: in an MCP client ask "which containers are unhealthy?" | Same real tools exposed read-only over MCP. |
| 2:45 | Integrations page | Optional AWS read-only and Bedrock. Close with security: socket proxy, no command execution. |

## How to record and show the video
1. Windows 11: press **Win+Shift+S → Screen record** (Snipping Tool) or install OBS Studio (Display Capture + microphone). Record at 1080p.
2. Record the dashboard in one take using the script above; trim mistakes in Clipchamp (built into Windows 11).
3. Export MP4. Upload to **YouTube as Public or Unlisted** (or Vimeo) and test the link in a private window.
4. In the hackathon submission form, paste the video link and the repository link. Many hackathons cap video length (commonly about 3 minutes); check the rules and keep within them.
5. Put the same link in your README. Add 3 screenshots to the repository.

## Submission checklist
- Public repo with README, `.env.example` (no real keys), docs, tests.
- Run `python -m pytest` and paste the real result in the submission.
- State clearly: no real Docker engine was available while this code was written, so the real-Docker integration test (`DOP_INTEGRATION=1`) should be run by you on Docker Desktop before recording.
