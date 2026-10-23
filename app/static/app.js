/* DevOpsPilot dashboard. All dynamic text is inserted with textContent (never innerHTML) because logs are untrusted. */
"use strict";
const view = document.getElementById("view");
const NA = () => h("span", { class: "na" }, "unavailable");

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}

// ---- API ---------------------------------------------------------------
let token = sessionStorage.getItem("dop_token") || "";
async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (token) headers.Authorization = "Bearer " + token;
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch("/api" + path, { ...opts, headers });
  if (res.status === 401) { document.getElementById("token-btn").hidden = false; throw new Error("This server needs an API token. Select “Set API token” at the top right."); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.message || j.detail || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res;
}
const getJSON = async (p) => (await api(p)).json();
async function download(path, filename) {
  const blob = await (await api(path)).blob();
  const a = h("a", { href: URL.createObjectURL(blob), download: filename }); a.click(); URL.revokeObjectURL(a.href);
}
function toast(msg) { const t = h("div", { class: "toast", role: "status" }, msg); document.body.append(t); setTimeout(() => t.remove(), 2500); }
async function copy(text) { try { await navigator.clipboard.writeText(text); toast("Copied"); } catch (_) { toast("Copy failed"); } }

document.getElementById("token-btn").onclick = () => {
  const t = prompt("API token (DOP_API_TOKEN)"); if (t != null) { token = t.trim(); sessionStorage.setItem("dop_token", token); route(); }
};

// ---- formatting --------------------------------------------------------
const fmtUptime = (s) => s == null ? NA() : s < 60 ? s + "s" : s < 3600 ? Math.floor(s / 60) + "m" : s < 86400 ? Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m" : Math.floor(s / 86400) + "d " + Math.floor((s % 86400) / 3600) + "h";
const fmtBytes = (b) => b == null ? NA() : b > 2 ** 30 ? (b / 2 ** 30).toFixed(2) + " GiB" : (b / 2 ** 20).toFixed(1) + " MiB";
const status = (s) => h("span", { class: "st" }, h("span", { class: "dot " + s }), s);
const loading = () => h("p", { class: "muted" }, "Loading…");
const failure = (e) => h("div", { class: "banner bad", role: "alert" }, e.message);
const empty = (msg) => h("div", { class: "empty" }, msg);
const when = (iso) => iso ? new Date(iso).toLocaleString() : "";

function show(...nodes) { view.replaceChildren(...nodes); }
async function load(render) {
  show(loading());
  try { show(...[await render()].flat()); } catch (e) { show(failure(e)); }
}

// ---- shared pieces -----------------------------------------------------
function cmdBlock(c) {
  return h("div", { class: "cmd" + (c.destructive ? " destructive" : "") },
    h("div", { style: "flex:1" }, h("code", {}, c.command), c.note || c.destructive ? h("small", {}, (c.destructive ? "Changes or deletes things. Review carefully. " : "") + (c.note || "")) : null),
    h("button", { class: "btn", onclick: () => copy(c.command) }, "Copy"));
}
function findingCard(f, onLine) {
  return h("article", { class: "finding", id: "f-" + f.rule_id },
    h("header", {}, h("strong", {}, f.title), h("span", { class: "sev " + f.severity }, f.severity), h("span", { class: "muted" }, "confidence: " + f.confidence), h("span", { class: "mono muted" }, f.rule_id)),
    h("div", { class: "evidence" }, h("h3", {}, "Observed evidence (verified)"),
      h("ul", {}, f.evidence.map((e) => h("li", { class: "mono" }, e))),
      onLine && f.log_refs.length ? h("button", { class: "tag", onclick: () => onLine(f.log_refs[0]) }, "show in logs") : null),
    h("div", { class: "hypo" }, h("h3", {}, "Possible causes (hypotheses, not proven)"), h("ul", {}, f.possible_causes.map((c) => h("li", {}, c)))),
    h("strong", {}, "Next steps"), h("ul", {}, f.next_steps.map((s) => h("li", {}, s))),
    f.commands.map(cmdBlock));
}

// ---- views -------------------------------------------------------------
const views = {};

views.overview = () => load(async () => {
  const o = await getJSON("/overview");
  const out = [h("h1", {}, "Overview")];
  if (!o.docker.connected) out.push(h("div", { class: "banner bad", role: "alert" }, h("strong", {}, "Docker is not connected. "), o.docker.message));
  const c = o.counts;
  out.push(h("div", { class: "tiles" },
    [["Total", c?.total], ["Running", c?.running], ["Stopped", c?.stopped], ["Unhealthy", c?.unhealthy, 1], ["Restarting", c?.restarting, 1]].map(([label, n, warn]) =>
      h("div", { class: "tile" + (warn && n > 0 ? " bad" : "") }, h("b", {}, n ?? "—"), h("span", {}, label)))));
  const firstRun = [];
  const s = await getJSON("/settings").catch(() => null);
  if (s && !s.ai.configured) firstRun.push(h("li", {}, "AI is off. Rule-based diagnostics work without it. ", h("a", { href: "#/integrations" }, "How to enable AI")));
  if (s && !s.aws.enabled) firstRun.push(h("li", {}, "AWS integration is off (optional). ", h("a", { href: "#/integrations" }, "How to enable it")));
  if (firstRun.length) out.push(h("h2", {}, "Setup"), h("ul", {}, firstRun));
  out.push(h("h2", {}, "Recent incidents"));
  out.push(o.recent_incidents.length ? h("ul", {}, o.recent_incidents.map((i) => h("li", {}, h("a", { href: "#/incidents/" + i.id }, i.title), " ", h("span", { class: "muted" }, i.status + " · " + when(i.created_at))))) : empty("No incidents saved yet. Run a diagnosis and save it from the Assistant or a container page."));
  out.push(h("h2", {}, "Latest diagnostic activity"));
  out.push(o.activity.length ? h("ul", {}, o.activity.map((a) => h("li", {}, h("span", { class: "muted" }, when(a.at) + " "), a.kind + (a.target ? " · " + a.target : "") + " · " + a.detail))) : empty("No diagnostics run yet."));
  return out;
});

views.containers = (arg) => arg ? containerDetail(arg) : containerList();

function containerList() {
  const search = h("input", { type: "search", placeholder: "Search name, image, ID", "aria-label": "Search containers" });
  const filter = h("select", { "aria-label": "Filter by status" }, ["", "running", "exited", "restarting", "paused", "created", "unhealthy"].map((v) => h("option", { value: v }, v || "All statuses")));
  const body = h("div", {});
  let withStats = false;
  const refresh = async () => {
    body.replaceChildren(loading());
    try {
      const qs = new URLSearchParams({ search: search.value, include_stats: withStats }); if (filter.value) qs.set("status", filter.value);
      const { containers } = await getJSON("/containers?" + qs);
      body.replaceChildren(containers.length ? h("div", { class: "tablewrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Name", "ID", "Image", "Status", "Health", "Uptime", "Restarts", "CPU", "Memory"].map((t) => h("th", {}, t)))),
        h("tbody", {}, containers.map((c) => h("tr", { class: "click", tabindex: 0, onclick: () => (location.hash = "#/containers/" + c.id), onkeydown: (e) => e.key === "Enter" && (location.hash = "#/containers/" + c.id) },
          h("td", {}, c.name), h("td", { class: "mono" }, c.id), h("td", {}, c.image), h("td", {}, status(c.status)), h("td", {}, c.health ? status(c.health) : "—"),
          h("td", {}, fmtUptime(c.uptime_seconds)), h("td", {}, c.restart_count ?? NA()),
          h("td", {}, c.cpu_percent != null ? c.cpu_percent + "%" : NA()), h("td", {}, fmtBytes(c.memory_bytes))))))) : empty("No containers match. Start one with `docker run` or see scripts/create_demo_containers for ready-made failing examples."));
    } catch (e) { body.replaceChildren(failure(e)); }
  };
  search.oninput = debounce(refresh, 250); filter.onchange = refresh;
  const statsBtn = h("button", { class: "btn", onclick: () => { withStats = true; statsBtn.disabled = true; refresh(); } }, "Load CPU and memory");
  show(h("h1", {}, "Containers"), h("div", { class: "bar" }, search, filter, h("button", { class: "btn", onclick: refresh }, "Refresh"), statsBtn), body);
  refresh();
}

async function containerDetail(ref) {
  await load(async () => {
    const c = await getJSON("/containers/" + encodeURIComponent(ref));
    const dl = (pairs) => h("dl", {}, pairs.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v ?? NA())]));
    const diag = h("div", {});
    return [
      h("p", {}, h("a", { href: "#/containers" }, "← All containers")), h("h1", {}, c.name),
      h("div", { class: "bar" },
        h("a", { class: "btn", href: "#/logs/" + c.id }, "View logs"),
        h("button", { class: "btn primary", onclick: async () => { diag.replaceChildren(loading()); try { const d = await getJSON("/containers/" + c.id + "/diagnose"); diag.replaceChildren(h("h2", {}, d.findings.length + " finding(s) from " + d.log_lines_inspected + " log lines"), d.findings.length ? d.findings.map((f) => findingCard(f)) : empty("No known failure patterns found. That does not prove the container is healthy.")); } catch (e) { diag.replaceChildren(failure(e)); } } }, "Run diagnostics"),
        h("button", { class: "btn", onclick: () => saveIncident(c) }, "Save as incident"),
        h("button", { class: "btn", onclick: () => download("/containers/" + c.id + "/report?format=md", c.name + "-report.md") }, "Report (.md)"),
        h("button", { class: "btn", onclick: () => download("/containers/" + c.id + "/report?format=json", c.name + "-report.json") }, "Report (.json)")),
      h("div", { class: "grid2" },
        h("div", { class: "card" }, h("h3", {}, "State"), dl([["Status", status(c.status)], ["Health", c.health || "no health check"], ["Uptime", fmtUptime(c.uptime_seconds)], ["Restarts", c.restart_count], ["Exit code", c.exit_code], ["OOM killed", c.oom_killed ? "yes" : "no"], ["Docker error", c.error], ["Started", c.started_at], ["Finished", c.finished_at]])),
        h("div", { class: "card" }, h("h3", {}, "Resources"), dl([["CPU", c.cpu_percent != null ? c.cpu_percent + "%" : null], ["Memory", c.memory_bytes != null ? fmtBytes(c.memory_bytes) + " of " + fmtBytes(c.memory_limit_bytes) : null]])),
        h("div", { class: "card" }, h("h3", {}, "Config"), dl([["ID", h("span", { class: "mono" }, c.id)], ["Image", c.image], ["Restart policy", c.restart_policy], ["Command", h("span", { class: "mono" }, c.command.join(" "))], ["Networks", c.networks.join(", ")], ["Mounts", c.mounts.join("; ")], ["Ports", Object.entries(c.ports).map(([p, b]) => p + (b.length ? " → " + b.join(", ") : "")).join("; ")]])),
        h("div", { class: "card" }, h("h3", {}, "Environment (sensitive values masked)"), c.env.length ? dl(c.env.map((e) => [e.name, h("span", { class: "mono" }, e.value)])) : h("span", { class: "na" }, "none"))),
      c.health_log.length ? [h("h2", {}, "Recent health probe output"), h("pre", { class: "logs mono", style: "padding:8px 12px" }, c.health_log.join("\n"))] : null,
      diag];
  });
}

async function saveIncident(c) {
  const title = prompt("Incident title", "Investigate " + c.name); if (!title) return;
  try { const i = await (await api("/incidents", { method: "POST", body: JSON.stringify({ title, container_id: c.id }) })).json(); location.hash = "#/incidents/" + i.id; }
  catch (e) { toast(e.message); }
}

views.logs = async (arg) => {
  let containers = [];
  try { containers = (await getJSON("/containers")).containers; } catch (e) { return show(h("h1", {}, "Log explorer"), failure(e)); }
  if (!containers.length) return show(h("h1", {}, "Log explorer"), empty("No containers found."));
  const pick = h("select", { "aria-label": "Container" }, containers.map((c) => h("option", { value: c.id, selected: c.id === arg || c.name === arg }, c.name)));
  const tail = h("select", { "aria-label": "Lines to fetch" }, [100, 300, 1000].map((n) => h("option", { value: n }, "last " + n + " lines")));
  const since = h("select", { "aria-label": "Time window" }, [["", "any time"], ["15", "last 15 min"], ["60", "last hour"], ["1440", "last 24 h"]].map(([v, t]) => h("option", { value: v }, t)));
  const level = h("select", { "aria-label": "Severity" }, [["", "all levels"], ["error", "errors"], ["warning", "warnings"], ["info", "info"], ["debug", "debug"]].map(([v, t]) => h("option", { value: v }, t)));
  const search = h("input", { type: "search", placeholder: "Search logs", "aria-label": "Search logs" });
  const out = h("div", {}); let offset = 0; const limit = 200; let lastText = "";
  const run = async (resetOffset = true) => {
    if (resetOffset) offset = 0; out.replaceChildren(loading());
    try {
      const qs = new URLSearchParams({ tail: tail.value, search: search.value, limit, offset }); if (since.value) qs.set("since_minutes", since.value); if (level.value) qs.set("level", level.value);
      const d = await getJSON("/containers/" + encodeURIComponent(pick.value) + "/logs?" + qs);
      lastText = d.lines.map((l) => (l.timestamp || "") + " " + l.text).join("\n");
      const ids = (l) => l.rule_ids.map((r) => h("button", { class: "tag", title: "Jump to diagnostic result", onclick: () => document.getElementById("f-" + r)?.scrollIntoView({ block: "center" }) }, r));
      out.replaceChildren(
        d.window_truncated ? h("p", { class: "muted" }, "The fetched window was limited, so older lines may exist. Increase the line count or narrow the time window.") : null,
        d.lines.length ? h("div", { class: "logs", role: "log" }, d.lines.map((l) => h("div", { class: "logline " + l.level, id: "L" + l.index }, h("span", { class: "ts" }, l.timestamp ? l.timestamp.slice(11, 19) : ""), h("span", {}, l.text, ids(l))))) : empty("No log lines match these filters."),
        h("div", { class: "bar", style: "margin-top:10px" }, h("button", { class: "btn", disabled: offset === 0, onclick: () => { offset = Math.max(0, offset - limit); run(false); } }, "Previous"),
          h("span", { class: "muted" }, d.total_matching ? (d.offset + 1) + "–" + (d.offset + d.lines.length) + " of " + d.total_matching : "0 lines"),
          h("button", { class: "btn", disabled: offset + limit >= d.total_matching, onclick: () => { offset += limit; run(false); } }, "Next")),
        h("h2", {}, "Detected patterns"),
        d.detected.length ? d.detected.map((f) => findingCard(f, (i) => { const el = document.getElementById("L" + i); if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1500); } else toast("That line is on another page or filtered out."); })) : empty("No known failure patterns detected in this window."));
    } catch (e) { out.replaceChildren(failure(e)); }
  };
  [pick, tail, since, level].forEach((el) => (el.onchange = () => run())); search.oninput = debounce(() => run(), 300);
  show(h("h1", {}, "Log explorer"), h("div", { class: "bar" }, pick, tail, since, level, search,
    h("button", { class: "btn", onclick: () => copy(lastText) }, "Copy"),
    h("button", { class: "btn", onclick: () => download("/containers/" + encodeURIComponent(pick.value) + "/logs/download?tail=" + tail.value, pick.selectedOptions[0].text + "-logs.txt") }, "Download")), out);
  run();
};

const EXAMPLES = ["Why did my container stop?", "Why is my application returning HTTP 502?", "Why is my Docker container restarting repeatedly?", "What should I investigate after a failed deployment?", "How can I safely investigate a database connection failure?"];

views.assistant = async () => {
  let containers = []; try { containers = (await getJSON("/containers")).containers; } catch (_) {}
  const target = h("select", { "aria-label": "Container" }, h("option", { value: "" }, "Detect automatically"), containers.map((c) => h("option", { value: c.id }, c.name)));
  const q = h("textarea", { placeholder: "Describe the problem, or paste an error or traceback.", maxlength: 4000, "aria-label": "Question" });
  const out = h("div", {}); const ask = h("button", { class: "btn primary" }, "Ask");
  ask.onclick = async () => {
    if (q.value.trim().length < 3) return toast("Type a question first.");
    ask.disabled = true; out.replaceChildren(loading());
    try { const r = await (await api("/assistant/ask", { method: "POST", body: JSON.stringify({ question: q.value, container_id: target.value || null }) })).json(); out.replaceChildren(...renderAnswer(r, q.value, target.value)); }
    catch (e) { out.replaceChildren(failure(e)); } finally { ask.disabled = false; }
  };
  show(h("h1", {}, "Assistant"), h("div", { class: "chips" }, EXAMPLES.map((e) => h("button", { class: "chip", onclick: () => { q.value = e; q.focus(); } }, e))), h("div", { class: "bar" }, target), q, h("div", { class: "bar", style: "margin-top:8px" }, ask), out);
};

function renderAnswer(r, question, containerId) {
  const list = (items, mono) => h("ul", {}, items.map((i) => h("li", { class: mono ? "mono" : "" }, i)));
  return [
    r.mode === "rules_only" ? h("div", { class: "banner" }, r.ai_error ? r.ai_error : "AI is off. These results come from the built-in rules only.") : h("div", { class: "banner", style: "border-left-color:var(--ok)" }, "AI explanation based on the evidence below."),
    h("h2", {}, "Problem summary"), h("p", {}, r.summary),
    h("div", { class: "evidence" }, h("h3", {}, "Evidence observed (verified from Docker and the rules)"), r.observed_evidence.length ? list(r.observed_evidence, true) : h("p", { class: "na" }, "No evidence was collected.")),
    h("div", { class: "hypo" }, h("h3", {}, "Likely causes (hypotheses)"), r.likely_causes.length ? h("ul", {}, r.likely_causes.map((c) => h("li", {}, c.cause + " ", h("span", { class: "muted" }, "(confidence: " + c.confidence + ")")))) : h("p", { class: "na" }, "Not enough evidence to rank causes.")),
    r.investigation_steps.length ? [h("h2", {}, "Recommended investigation steps"), list(r.investigation_steps)] : null,
    r.potential_solutions.length ? [h("h2", {}, "Potential solutions"), list(r.potential_solutions)] : null,
    h("h2", {}, "Risks and side effects"), list(r.risks),
    r.commands.length ? [h("h2", {}, "Commands to review before running"), r.commands.map(cmdBlock)] : null,
    r.information_needed.length ? [h("h2", {}, "Information still needed"), list(r.information_needed)] : null,
    r.findings.length ? [h("h2", {}, "Rule findings"), r.findings.map((f) => findingCard(f))] : null,
    h("p", { class: "muted" }, r.notice),
    h("button", { class: "btn", onclick: async () => { const title = prompt("Incident title", question.slice(0, 80)); if (!title) return; try { const i = await (await api("/incidents", { method: "POST", body: JSON.stringify({ title, container_id: containerId || null, question }) })).json(); location.hash = "#/incidents/" + i.id; } catch (e) { toast(e.message); } } }, "Save as incident")];
}

views.incidents = (arg) => arg ? incidentDetail(arg) : incidentList();

function incidentList() {
  const q = h("input", { type: "search", placeholder: "Search incidents", "aria-label": "Search incidents" }); const body = h("div", {});
  const run = async () => {
    body.replaceChildren(loading());
    try {
      const { incidents } = await getJSON("/incidents?q=" + encodeURIComponent(q.value));
      body.replaceChildren(incidents.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Title", "Resource", "Status", "Created"].map((t) => h("th", {}, t)))),
        h("tbody", {}, incidents.map((i) => h("tr", { class: "click", tabindex: 0, onclick: () => (location.hash = "#/incidents/" + i.id), onkeydown: (e) => e.key === "Enter" && (location.hash = "#/incidents/" + i.id) }, h("td", {}, i.title), h("td", {}, i.resource || "—"), h("td", {}, i.status), h("td", {}, when(i.created_at))))))) : empty("No incidents found. Save one from a container page or an Assistant answer."));
    } catch (e) { body.replaceChildren(failure(e)); }
  };
  q.oninput = debounce(run, 250); show(h("h1", {}, "Incidents"), h("div", { class: "bar" }, q), body); run();
}

function incidentDetail(id) {
  return load(async () => {
    const i = await getJSON("/incidents/" + id);
    const setStatus = async (status, confirm) => { try { await api("/incidents/" + id + "/status", { method: "PATCH", body: JSON.stringify({ status, confirm, note: status === "resolved" ? prompt("Resolution note (optional)") || null : null }) }); incidentDetail(id); } catch (e) { toast(e.message); } };
    return [h("p", {}, h("a", { href: "#/incidents" }, "← All incidents")), h("h1", {}, i.title),
      h("p", { class: "muted" }, "Status: " + i.status + " · created " + when(i.created_at) + (i.resource ? " · " + i.resource : "")),
      h("div", { class: "bar" },
        i.status !== "investigating" ? h("button", { class: "btn", onclick: () => setStatus("investigating", false) }, "Mark investigating") : null,
        i.status !== "resolved" ? h("button", { class: "btn", onclick: () => confirm("Mark this incident as resolved? Only do this if you have verified the fix.") && setStatus("resolved", true) }, "Mark resolved") : null,
        h("button", { class: "btn", onclick: () => download("/incidents/" + id + "/report?format=md", "incident-" + id + ".md") }, "Report (.md)"),
        h("button", { class: "btn", onclick: () => download("/incidents/" + id + "/report?format=json", "incident-" + id + ".json") }, "Report (.json)")),
      i.summary ? h("p", {}, i.summary) : null, i.resolution_note ? h("div", { class: "banner" }, "Resolution note: " + i.resolution_note) : null,
      h("div", { class: "evidence" }, h("h3", {}, "Evidence at the time"), h("ul", {}, i.evidence.map((e) => h("li", { class: "mono" }, e)))),
      h("h2", {}, "Findings"), i.findings.length ? i.findings.map((f) => findingCard(f)) : empty("No findings were recorded."),
      h("h2", {}, "Recommended actions"), h("ul", {}, i.actions.map((a) => h("li", {}, a)))];
  });
}

views.integrations = () => load(async () => {
  const s = await getJSON("/settings");
  const out = [h("h1", {}, "Integrations"),
    h("div", { class: "card" }, h("h3", {}, "AI provider"), h("p", {}, s.ai.configured ? "Ready: " + s.ai.provider + (s.ai.model ? " / " + s.ai.model : "") : s.ai.message), h("p", { class: "muted" }, "Set in .env: DOP_AI_PROVIDER (openai or bedrock), DOP_AI_MODEL, and DOP_AI_API_KEY for openai. Restart the server after changes.")),
    h("div", { class: "card", style: "margin-top:16px" }, h("h3", {}, "AWS (read-only, optional)"), h("p", {}, s.aws.message), s.aws.how_to_enable ? h("p", { class: "muted" }, s.aws.how_to_enable) : null)];
  if (s.aws.configured) {
    const res = h("pre", { class: "logs mono", style: "padding:10px 12px;margin-top:10px", hidden: true });
    const call = async (path) => { res.hidden = false; res.textContent = "Loading…"; try { res.textContent = JSON.stringify(await getJSON(path), null, 2); } catch (e) { res.textContent = e.message; } };
    const lg = h("input", { placeholder: "CloudWatch log group, e.g. /ecs/my-app" }), cl = h("input", { placeholder: "ECS cluster" }), sv = h("input", { placeholder: "ECS service" }), ec = h("input", { placeholder: "EC2 instance ID (i-…)" });
    out.push(h("h2", {}, "AWS findings (shown separately from local Docker)"),
      h("div", { class: "bar" }, lg, h("button", { class: "btn", onclick: () => call("/aws/logs?log_group=" + encodeURIComponent(lg.value)) }, "Recent log events")),
      h("div", { class: "bar" }, h("button", { class: "btn", onclick: () => call("/aws/alarms") }, "Alarms in ALARM state")),
      h("div", { class: "bar" }, cl, sv, h("button", { class: "btn", onclick: () => call("/aws/ecs?cluster=" + encodeURIComponent(cl.value) + "&service=" + encodeURIComponent(sv.value)) }, "ECS service status")),
      h("div", { class: "bar" }, ec, h("button", { class: "btn", onclick: () => call("/aws/ec2?instance_id=" + encodeURIComponent(ec.value)) }, "EC2 status")), res);
  }
  return out;
});

// ---- router ------------------------------------------------------------
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function route() {
  const [name, arg] = (location.hash.replace(/^#\//, "") || "overview").split("/");
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
  (views[name] || views.overview)(arg ? decodeURIComponent(arg) : undefined);
}
async function pollHealth() {
  const pill = document.getElementById("docker-pill");
  try { const j = await (await fetch("/api/health")).json(); pill.className = "pill " + (j.docker.connected ? "pill-ok" : "pill-bad"); pill.textContent = j.docker.connected ? "Docker connected" : "Docker disconnected"; pill.title = j.docker.message; if (j.auth_required && !token) document.getElementById("token-btn").hidden = false; }
  catch (_) { pill.className = "pill pill-bad"; pill.textContent = "Server unreachable"; }
}
window.addEventListener("hashchange", route); pollHealth(); setInterval(pollHealth, 15000); route();
