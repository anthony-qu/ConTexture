// ConTexture page. Plain JavaScript, no build step. The server only ever reads a run's folder,
// so this page polls: the run list every few seconds, and the open run every two seconds.
"use strict";

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ decoration

// A hexagonal array of spots, coloured in bands like tissue domains on a spatial slide.
function spotMap(rings) {
  const colors = ["var(--accent)", "var(--C)", "var(--G)", "var(--T)"];
  const sp = 10, r = 3.9, R = rings * sp;
  let circles = "";
  for (let q = -rings; q <= rings; q++) {
    for (let s = -rings; s <= rings; s++) {
      if (Math.abs(q + s) > rings) continue;
      const x = sp * (q + s / 2), y = sp * (s * Math.sqrt(3) / 2);
      const t = (y + 0.55 * (x * x) / R - 0.2 * x) / R;          // curved, layered bands
      const band = Math.max(0, Math.min(3, Math.floor((t + 1.05) * 1.9)));
      circles += `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${r}" style="fill:${colors[band]}"/>`;
    }
  }
  const h = R + sp;
  return `<svg viewBox="${-h} ${-h} ${2 * h} ${2 * h}" aria-hidden="true">${circles}</svg>`;
}

function sequence(n) {
  const bases = "ACGT";
  let seed = 7, out = "";
  for (let i = 0; i < n; i++) {
    // Math.imul keeps the product in 32 bits; a plain multiply loses the low bits in a double.
    seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
    const b = bases[(seed >>> 16) % 4];
    out += `<span class="${b}">${b}</span>`;
  }
  return out;
}

// ------------------------------------------------------------------ helpers

async function api(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...options });
  if (res.status === 403) {
    document.body.innerHTML = "<p style='font-family:system-ui;margin:15vh auto;max-width:32rem'>" +
      "The access code has expired. Open the full address printed by <code>serve.py</code>.</p>";
    throw new Error("forbidden");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

const fileUrl = (id, path, download) =>
  `/api/runs/${encodeURIComponent(id)}/files/${path.split("/").map(encodeURIComponent).join("/")}` +
  (download ? "?download=1" : "");

function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function duration(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min ${String(s).padStart(2, "0")} s` : `${s} s`;
}

function size(bytes) {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (bytes >= 1024 && i < u.length - 1) { bytes /= 1024; i++; }
  return `${bytes < 10 && i ? bytes.toFixed(1) : Math.round(bytes)} ${u[i]}`;
}

const tokens = (n) => n >= 1e6 ? `${(n / 1e6).toFixed(1)} M` : n >= 1e3 ? `${Math.round(n / 1e3)} k` : `${n}`;

const STATUS_TEXT = {
  running: "Running", stopping: "Stopping", finished: "Finished",
  failed: "Failed", stopped: "Stopped", ended: "Ended unexpectedly",
};

function who(agent) {
  if (!agent) return "";
  const spec = /special/i.test(agent);
  const label = spec ? "Specialist" : /orchestr/i.test(agent) ? "Main agent" : agent;
  return `<span class="who${spec ? " spec" : ""}">${esc(label)}</span>`;
}

// A small Python highlighter: comments, strings, numbers, keywords, called names.
const KEYWORDS = new Set(("False None True and as assert async await break class continue def " +
  "del elif else except finally for from global if import in is lambda nonlocal not or pass " +
  "raise return try while with yield").split(" "));
function highlight(src) {
  const re = /(#[^\n]*)|((?:[rRbBfFuU]{1,2})?(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))|(\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|([A-Za-z_]\w*)(?=\s*\()|([A-Za-z_]\w*)/g;
  let out = "", last = 0, m;
  while ((m = re.exec(src))) {
    out += esc(src.slice(last, m.index));
    if (m[1]) out += `<span class="tk-c">${esc(m[1])}</span>`;
    else if (m[2]) out += `<span class="tk-s">${esc(m[2])}</span>`;
    else if (m[3]) out += `<span class="tk-n">${esc(m[3])}</span>`;
    else if (m[4]) out += KEYWORDS.has(m[4]) ? `<span class="tk-k">${m[4]}</span>` : `<span class="tk-f">${m[4]}</span>`;
    else out += KEYWORDS.has(m[5]) ? `<span class="tk-k">${m[5]}</span>` : m[5];
    last = re.lastIndex;
  }
  return out + esc(src.slice(last));
}

// ------------------------------------------------------------------ transcript entries

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function stateSummary(text) {
  const line = text.split("\n").find((l) => l.trim() && !/^=+$/.test(l.trim()) &&
    !l.startsWith("[STATE]") && !/descriptors read|neg\/non-neg|int\/frac/.test(l));
  return line ? line.trim().replace(/\s+/g, " ").slice(0, 110) : "";
}

function renderSection(s, view) {
  const t = s.text || "";
  switch (s.kind) {
    case "CODE": {
      view.cell += 1;
      const lines = t.split("\n").length;
      const long = lines > 26;
      const node = el(`<div class="entry k-code"><div class="cell${long ? " long" : ""}"><div class="cell-head">
        <span>In [${view.cell}]</span>${who(s.agent)}</div><pre><code>${highlight(t)}</code></pre>
        ${long ? `<button class="more" type="button">Show all ${lines} lines</button>` : ""}</div></div>`);
      if (long) {
        const cell = node.querySelector(".cell"), btn = node.querySelector(".more");
        btn.addEventListener("click", () => {
          const open = cell.classList.toggle("long");
          btn.textContent = open ? `Show all ${lines} lines` : "Show less";
        });
      }
      return node;
    }
    case "OUTPUT": {
      const err = /Traceback \(most recent call last\)|^\w*Error\b/m.test(t);
      const empty = !t.trim();
      const node = el(`<div class="entry k-output out${err ? " err" : ""}${empty ? " empty" : ""}">
        <pre>${empty ? "(no printed output)" : esc(t)}</pre></div>`);
      const prev = view.last;
      if (prev && prev.classList.contains("k-code")) {
        prev.querySelector(".cell").classList.add("joined");
        if (err) prev.classList.add("k-error");
      }
      return node;
    }
    case "AGENT":
      return el(`<div class="entry k-message message"><div class="msg-head">${who(s.agent) || "ConTexture"}</div>
        <div class="md">${s.html || esc(t)}</div></div>`);
    case "STATE":
      return el(`<details class="entry fold state"><summary>Object state changed
        <span class="muted">${esc(stateSummary(t))}</span></summary><pre>${esc(t)}</pre></details>`);
    case "SKILL": {
      if (t.startsWith("MENU")) return el(`<div class="entry k-skill"><span class="pill"><i></i>Read the skill menu ${who(s.agent)}</span></div>`);
      const loaded = t.match(/^LOADED:\s*(.+)$/m);
      if (loaded) return el(`<div class="entry k-skill"><span class="pill"><i></i>Loaded skill <b>${esc(loaded[1])}</b> ${who(s.agent)}</span></div>`);
      return el(`<div class="entry k-skill"><span class="pill warn"><i></i>${esc(t.split("\n")[0])}</span></div>`);
    }
    case "TOOL": {
      const name = (t.match(/^([\w.-]+)\(/) || [])[1] || "";
      if (!name || name === "execute_python" || name === "get_skill") return null;
      let ask = "";
      try { ask = JSON.parse(t.slice(t.indexOf("\n") + 1, t.lastIndexOf(")"))).input || ""; } catch (e) { /* show raw */ }
      return el(`<details class="entry fold"><summary>Handed a task to a specialist
        <span class="muted">${esc((ask || name).slice(0, 120))}</span></summary><pre>${esc(ask || t)}</pre></details>`);
    }
    case "AGENT-START":
      return el(`<div class="entry divider">${who(t.trim())} starts</div>`);
    case "ROUTING":
      return el(`<div class="entry notice"><b>Routing.</b> ${esc(t)}</div>`);
    case "BUDGET":
      return el(`<div class="entry notice warn">${esc(t.replace(/^\[BUDGET\]\s*/, ""))}</div>`);
    case "USAGE":
      return el(`<div class="entry notice"><b>Model usage.</b> ${esc(t)}</div>`);
    case "SESSION":
      return el(`<details class="entry fold"><summary>Session details</summary><pre>${esc(t)}</pre></details>`);
    default:
      return el(`<details class="entry fold"><summary>${esc(s.kind.toLowerCase())}</summary><pre>${esc(t)}</pre></details>`);
  }
}

// ------------------------------------------------------------------ app state

const app = { config: null, runs: [], view: null, listTimer: null };

async function loadConfig() {
  app.config = await api("/api/config");
  const c = app.config;
  $("#f-model").value = c.default_model;
  $("#f-turns").value = c.default_turns;
  $("#model-list").innerHTML = c.models.map((m) => `<option value="${esc(m)}">`).join("");
  $("#runs-dir-note").textContent = `Saved in ${c.runs_dir}`;
  const note = $("#key-note");
  if (c.keys.length) {
    note.classList.remove("missing");
    note.innerHTML = "API keys found: " + c.keys.map((k) => `<span class="pill">${esc(k)}</span>`).join("");
  } else {
    note.classList.add("missing");
    note.textContent = "No API key found. Put one in the .env file next to agent.py, then restart the page.";
  }
}

async function refreshList() {
  try {
    const { runs } = await api("/api/runs");
    app.runs = runs;
    const current = app.view && app.view.id;
    $("#run-list").innerHTML = runs.length ? runs.map((r) => `
      <li><a href="#/run/${esc(r.id)}" class="${r.id === current ? "active" : ""}" title="${esc(r.goal)}">
        <span class="dot s-${r.status}"></span>
        <span class="rl-goal">${esc(r.goal.split("\n")[0])}</span>
        <span class="rl-meta">${esc(STATUS_TEXT[r.status] || r.status)} · ${esc(ago(r.created))} · ${esc(r.model.split("/").pop())}</span>
      </a></li>`).join("") : `<li class="empty">No analyses yet.</li>`;
  } catch (e) { /* keep the last list */ }
}

// ------------------------------------------------------------------ views

function show(name) {
  $("#view-new").hidden = name !== "new";
  $("#view-run").hidden = name !== "run";
}

function route() {
  const m = location.hash.match(/^#\/run\/([\w-]+)$/);
  if (m) openRun(m[1]);
  else { closeRun(); show("new"); $("#f-data").focus(); }
  refreshList();
}

function closeRun() {
  if (app.view) { clearTimeout(app.view.timer); clearInterval(app.view.clock); }
  app.view = null;
}

function openRun(id) {
  if (app.view && app.view.id === id) return;
  closeRun();
  const view = app.view = { id, total: 0, cell: 0, last: null, figSig: "", fileSig: "",
                            info: null, timer: null, clock: null, finalPass: false };
  $("#timeline").innerHTML = "";
  $("#gallery").innerHTML = "";
  $("#file-rows").innerHTML = "";
  $("#console").hidden = true;
  $("#r-goal").classList.remove("open");
  $("#r-log").href = fileUrl(id, "dialog_log.txt");
  selectTab("transcript");
  show("run");
  view.clock = setInterval(() => renderMeta(view), 1000);
  tick(view);
}

function nearBottom() {
  return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 200;
}

async function tick(view) {
  let info, log;
  try {
    [info, log] = await Promise.all([
      api(`/api/runs/${encodeURIComponent(view.id)}`),
      api(`/api/runs/${encodeURIComponent(view.id)}/log?since=${view.total}`),
    ]);
  } catch (e) {
    if (app.view !== view) return;
    if (e.message === "No such run.") { $("#r-goal").textContent = "This run no longer exists."; return; }
    view.timer = setTimeout(() => tick(view), 4000);
    return;
  }
  if (app.view !== view) return;                 // the user opened another run meanwhile
  view.info = info;
  renderHeader(view);
  const follow = nearBottom();
  const timeline = $("#timeline");
  for (const s of log.sections) {
    const node = renderSection(s, view);
    if (node) { timeline.appendChild(node); view.last = node; }
  }
  view.total = log.total;
  if (log.sections.length) {
    if (follow) window.scrollTo({ top: document.documentElement.scrollHeight });
    else if (info.active) $("#to-latest").hidden = false;
  }
  renderFigures(view);
  renderFiles(view);
  $("#waiting").hidden = !info.active;
  if (info.console_tail && info.console_tail.trim()) {
    $("#console").innerHTML = `<span class="label">Last lines the run printed</span><pre>${esc(info.console_tail)}</pre>`;
    $("#console").hidden = false;
  }
  if (info.active) view.timer = setTimeout(() => tick(view), 2000);
  else if (!view.finalPass) { view.finalPass = true; view.timer = setTimeout(() => tick(view), 1500); }
}

function renderHeader(view) {
  const r = view.info;
  const chip = $("#r-status");
  chip.className = `status-chip s-${r.status}`;
  chip.lastElementChild.textContent = STATUS_TEXT[r.status] || r.status;
  if ($("#r-goal").dataset.id !== view.id) { $("#r-goal").textContent = r.goal; $("#r-goal").dataset.id = view.id; }
  $("#r-stop").hidden = r.status !== "running";
  $("#r-progress").hidden = !r.active;
  $("#r-note").hidden = !r.note;
  $("#r-note").textContent = r.note || "";
  renderMeta(view);
}

function renderMeta(view) {
  const r = view.info;
  if (!r) return;
  const end = r.ended || Date.now() / 1000;
  const u = r.usage || {};
  const name = r.data_path.split("/").pop();
  $("#r-meta").innerHTML = [
    `<span><b>${esc(r.model)}</b></span>`,
    `<span class="path" title="${esc(r.data_path)}">${esc(name)}</span>`,
    `<span>${esc(duration(end - r.created))}</span>`,
    `<span>${u.model_calls || 0} model calls · ${tokens(u.input_tokens || 0)} tokens in · ${tokens(u.output_tokens || 0)} out</span>`,
    `<span>turn budget ${esc(r.max_turns)}</span>`,
  ].join("");
}

function renderFigures(view) {
  const figs = view.info.figures || [];
  $("#n-fig").textContent = figs.length;
  const sig = figs.map((f) => f.path + f.mtime).join("|");
  if (sig === view.figSig) return;
  view.figSig = sig;
  $("#gallery").innerHTML = figs.length ? figs.slice().reverse().map((f) => `
    <a class="fig" href="${fileUrl(view.id, f.path)}" target="_blank" rel="noopener">
      <div class="img"><img loading="lazy" src="${fileUrl(view.id, f.path)}?v=${Math.round(f.mtime)}" alt="${esc(f.path)}"></div>
      <div class="cap" title="${esc(f.path)}">${esc(f.path)}</div></a>`).join("")
    : `<div class="empty-state"><div class="mini-map">${spotMap(3)}</div>No figures yet.</div>`;
}

const isResult = (p) => /\.(h5ad|h5mu)$/i.test(p) || /(^|\/)(results\.json|analysis\.md)$/i.test(p);

function renderFiles(view) {
  const files = view.info.files || [];
  $("#n-files").textContent = files.length;
  const sig = files.map((f) => f.path + f.size + f.mtime).join("|");
  if (sig === view.fileSig) return;
  view.fileSig = sig;
  const sorted = files.slice().sort((a, b) => (isResult(b.path) - isResult(a.path)) || a.path.localeCompare(b.path));
  $("#file-rows").innerHTML = sorted.map((f) => `
    <tr class="${isResult(f.path) ? "result" : ""}">
      <td class="name"><a href="${fileUrl(view.id, f.path)}" target="_blank" rel="noopener">${esc(f.path)}</a></td>
      <td class="num">${size(f.size)}</td><td class="num">${esc(ago(f.mtime))}</td>
      <td class="num"><a href="${fileUrl(view.id, f.path, true)}">Download</a></td></tr>`).join("");
}

function selectTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  for (const p of ["transcript", "figures", "files"]) $(`#p-${p}`).hidden = p !== name;
}

// ------------------------------------------------------------------ events

$("#new-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("#f-start"), err = $("#form-error");
  err.hidden = true;
  btn.disabled = true;
  try {
    const { id } = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        data_path: $("#f-data").value, goal: $("#f-goal").value,
        model: $("#f-model").value, max_turns: Number($("#f-turns").value),
      }),
    });
    $("#f-goal").value = "";
    location.hash = `#/run/${id}`;
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
});

$("#r-stop").addEventListener("click", async () => {
  const view = app.view;
  if (!view || !confirm("Stop this analysis? Work saved so far is kept.")) return;
  $("#r-stop").hidden = true;
  try { await api(`/api/runs/${encodeURIComponent(view.id)}/stop`, { method: "POST" }); }
  catch (e) { alert(e.message); }
  clearTimeout(view.timer);
  view.finalPass = false;
  tick(view);
});

$("#r-goal").addEventListener("click", () => $("#r-goal").classList.toggle("open"));
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
$("#to-latest").addEventListener("click", () => {
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  $("#to-latest").hidden = true;
});
window.addEventListener("scroll", () => { if (nearBottom()) $("#to-latest").hidden = true; });
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ start

document.querySelectorAll("[data-spotmap]").forEach((n) => { n.innerHTML = spotMap(Number(n.dataset.spotmap)); });
$(".seq").innerHTML = sequence(40);
loadConfig().catch(() => {});
route();
app.listTimer = setInterval(refreshList, 4000);
