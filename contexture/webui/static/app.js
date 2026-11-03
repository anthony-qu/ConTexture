// ConTexture page. Plain JavaScript, no build step. The server only ever reads a run's folder,
// so this page polls: the run list every few seconds, and the open run every two seconds.
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ background

// A honeycomb behind the page: hexagonal cells drawn as thin outlines in a colour a shade off
// the page. A few small patches of neighbouring cells breathe slowly in the logo's purple and
// blue, like spatial domains on a section: each patch brightens and dims twice over about
// twenty seconds, its centre brightest, then fades out and a new patch appears elsewhere.
// Nothing follows the cursor.
function startLattice() {
  const canvas = $("#bg-lattice");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Pointy-top hexagons: R is the centre-to-corner distance; cells are W wide, rows ROW apart,
  // and every other row is shifted by half a cell.
  const R = 22, W_CELL = Math.sqrt(3) * R, ROW = 1.5 * R;
  const PATCHES = 3, BREATH = 9000, BREATHS = 2, GAP = [1500, 5000];   // milliseconds
  let W = 0, H = 0, cols = 0, rows = 0, colours = null, grid = null, patches = [];

  // The page's colours, re-read whenever the theme changes.
  function palette() {
    const css = getComputedStyle(document.documentElement);
    const rgb = (v) => {
      const h = css.getPropertyValue(v).trim().replace("#", "");
      return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    };
    colours = { base: rgb("--lattice"), a: rgb("--accent"), b: rgb("--blue") };
  }
  const mix = (p, q, t) => p.map((v, i) => Math.round(v + (q[i] - v) * t));
  const centre = (i, j) => [i * W_CELL + (j % 2 ? W_CELL / 2 : 0), j * ROW + R];
  const neighbours = (i, j) => {
    const o = j % 2 ? 1 : -1;
    return [[i - 1, j], [i + 1, j], [i, j - 1], [i, j + 1], [i + o, j - 1], [i + o, j + 1]]
      .filter(([a, b]) => a >= 0 && a < cols && b >= 0 && b < rows);
  };

  function hexPath(path, x, y, r) {
    for (let k = 0; k < 6; k++) {
      const a = Math.PI / 6 + (k * Math.PI) / 3;        // pointy top
      const px = x + r * Math.cos(a), py = y + r * Math.sin(a);
      if (k === 0) path.moveTo(px, py); else path.lineTo(px, py);
    }
    path.closePath();
  }

  // The still honeycomb is drawn once per size and theme into an offscreen canvas.
  function drawGrid() {
    const dpr = window.devicePixelRatio || 1;
    grid = document.createElement("canvas");
    grid.width = canvas.width; grid.height = canvas.height;
    const g = grid.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const path = new Path2D();
    for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) { const [x, y] = centre(i, j); hexPath(path, x, y, R); }
    const [r, gg, b] = colours.base;
    g.strokeStyle = `rgb(${r},${gg},${b})`; g.lineWidth = 1; g.stroke(path);
  }

  // A patch: a seed cell and 16-34 neighbours grown from it, each weighted by its distance
  // from the seed; born at `born`, it lives BREATHS breaths and is then replaced.
  function makePatch(now) {
    const si = Math.floor(Math.random() * cols), sj = Math.floor(Math.random() * rows);
    const [sx, sy] = centre(si, sj);
    const cells = new Map([[`${si},${sj}`, [si, sj]]]);
    const frontier = [[si, sj]];
    const size = 16 + Math.floor(Math.random() * 19);
    for (let n = 0; n < size; n++) {
      const [a, b] = frontier[Math.floor(Math.random() * frontier.length)];
      const free = neighbours(a, b).filter(([x, y]) => !cells.has(`${x},${y}`));
      if (!free.length) continue;
      const c = free[Math.floor(Math.random() * free.length)];
      cells.set(`${c[0]},${c[1]}`, c); frontier.push(c);
    }
    const weighted = [...cells.values()].map(([i, j]) => {
      const [x, y] = centre(i, j);
      return { x, y, w: Math.max(0.3, 1 - Math.hypot(x - sx, y - sy) / (R * 8)) };
    });
    const born = now + GAP[0] + Math.random() * (GAP[1] - GAP[0]);
    return { cells: weighted, born, dies: born + BREATH * BREATHS };
  }

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(W / W_CELL) + 2; rows = Math.ceil(H / ROW) + 2;
    const now = performance.now();
    patches = Array.from({ length: PATCHES }, () => makePatch(now));
    // Start the patches at different points of their lives, so they do not breathe in step.
    patches.forEach((p, k) => { const shift = (k / PATCHES) * BREATH * BREATHS; p.born -= shift; p.dies -= shift; });
    drawGrid();
    draw(now);
  }

  function draw(now) {
    if (!colours) palette();
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(grid, 0, 0, W, H);
    patches.forEach((p, k) => {
      if (now >= p.dies) { patches[k] = p = makePatch(now); }
      if (now < p.born) return;
      // One breath: 0 -> 1 -> 0 as a raised cosine, so it starts and ends without a step.
      const breath = (1 - Math.cos((2 * Math.PI * (now - p.born)) / BREATH)) / 2;
      for (const c of p.cells) {
        const e = breath * c.w;
        if (e < 0.02) continue;
        // purple at the top left, blue at the bottom right, as in the logo's gradient
        const [r, g, b] = mix(colours.a, colours.b, (c.x / W + c.y / H) / 2);
        const path = new Path2D();
        hexPath(path, c.x, c.y, R - 1);
        ctx.fillStyle = `rgba(${r},${g},${b},${0.03 + 0.28 * e})`; ctx.fill(path);
        ctx.strokeStyle = `rgba(${r},${g},${b},${0.12 + 0.6 * e})`; ctx.lineWidth = 1.2; ctx.stroke(path);
      }
    });
  }

  function frame(now) {
    draw(now);                     // every display frame, so the breathing has no visible steps
    requestAnimationFrame(frame);
  }

  palette();
  resize();
  window.addEventListener("resize", resize);
  new MutationObserver(() => { palette(); drawGrid(); draw(performance.now()); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (!still) requestAnimationFrame(frame);
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

const STAGE_NAMES = {
  REPORTER: "Data reporter", MAKER: "Skill maker", PLANNER: "Planner",
  SCOUT: "Method discovery agent", DISCOVERY: "Method discovery",
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

// The pre-analysis agents, each the owner of a group of transcript entries.
const GROUPS = {
  reporter: "Data reporter", maker: "Skill maker", planner: "Planner", scout: "Method discovery agent",
};
function stageOf(kind) {
  if (kind === "REPORTER" || kind === "REPORT-CODE" || kind === "REPORT-OUTPUT") return "reporter";
  if (kind === "MAKER") return "maker";
  if (kind === "PLANNER" || kind === "PLAN-CODE" || kind === "PLAN-OUTPUT") return "planner";
  if (kind === "SCOUT") return "scout";
  return null;
}
function openGroup(view, key, timeline) {
  const node = el(`<details class="entry stage-group working" open><summary><b>${esc(GROUPS[key])}</b>
    <span class="muted status">working</span></summary><div class="group-body"></div></details>`);
  timeline.appendChild(node);
  view.group = { key, node, body: node.querySelector(".group-body"), n: 0 };
}
function closeGroup(view) {
  const g = view.group;
  g.node.open = false;
  g.node.classList.remove("working");
  g.node.querySelector(".status").textContent = `done · ${g.n} ${g.n === 1 ? "entry" : "entries"}`;
  view.group = null;
}

function renderSection(s, view) {
  const t = s.text || "";
  if (["CODE", "SESSION", "AGENT-START", "ROUTING"].includes(s.kind)) view.analysisStarted = true;
  switch (s.kind) {
    case "CODE": case "REPORT-CODE": case "PLAN-CODE": {
      // REPORT-CODE and PLAN-CODE are the data reporter's and the planner's own code, run on
      // the data before the analysis; they are not numbered with the analysis cells.
      const stage = s.kind === "REPORT-CODE" ? "Data reporter" : s.kind === "PLAN-CODE" ? "Planner" : "";
      if (!stage) view.cell += 1;
      const lines = t.split("\n").length;
      const long = lines > 26;
      const node = el(`<div class="entry k-code${stage ? " pre" : ""}"><div class="cell${long ? " long" : ""}"><div class="cell-head">
        <span>${stage ? esc(stage) : `In [${view.cell}]`}</span>${who(s.agent)}</div><pre><code>${highlight(t)}</code></pre>
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
    case "OUTPUT": case "REPORT-OUTPUT": case "PLAN-OUTPUT": {
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
    case "REPORTER": case "MAKER": case "PLANNER": case "SCOUT": case "DISCOVERY": {
      // Progress lines of the stages that run before the analysis (method discovery).
      const name = STAGE_NAMES[s.kind];
      const [first, ...more] = t.split("\n");
      const rest = more.join("\n").trim();
      const head = esc(first.replace(/\s+/g, " ").slice(0, 160));
      if (!rest) return el(`<div class="entry notice stage"><b>${name}.</b> ${head}</div>`);
      return el(`<details class="entry fold stage"><summary><b>${name}</b> <span class="muted">${head}</span></summary><pre>${esc(t)}</pre></details>`);
    }
    default:
      return el(`<details class="entry fold"><summary>${esc(s.kind.toLowerCase())}</summary><pre>${esc(t)}</pre></details>`);
  }
}

// ------------------------------------------------------------------ app state

const app = { config: null, runs: [], view: null, listTimer: null };

async function loadConfig(first) {
  app.config = await api("/api/config");
  const c = app.config;
  renderModelChoices(c);
  renderKeyNote();
  // The toggle's hover text ends with where a discovered method will be installed.
  if (c.discovery && c.discovery.explain) {
    const sw = $(".switch");
    sw.title = sw.title.split("\n")[0] + "\n" + c.discovery.explain;
  }
  $("#pick-btns").hidden = !c.can_pick;    // no screen (a remote server): type the path
  if (first && !c.keys.length) openKeys();
}

// The computer's own file window, opened by the server, fills the Data field with the
// chosen path. A page may not learn a path from the browser's own file dialog.
async function pickPath(kind) {
  const btn = $(kind === "folder" ? "#pick-folder" : "#pick-file"), err = $("#form-error");
  const label = btn.innerHTML;
  err.hidden = true;
  $$(".pick-btns button").forEach((b) => { b.disabled = true; });
  btn.innerHTML = "Choosing…";
  try {
    const { path } = await api("/api/pick", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, start: $("#f-data").value }),
    });
    if (path) { $("#f-data").value = path; $("#f-goal").focus(); }
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.innerHTML = label;
    $$(".pick-btns button").forEach((b) => { b.disabled = false; });
  }
}

// The two switches: skill evolution runs inside method discovery, so it is offered only then.
// The model dropdown: one group per provider whose key is set, from the server's hand-kept
// table, plus "Another model" for a name typed by hand. The current choice survives a rebuild
// when it is still offered; otherwise the first model of the first key is selected.
const OTHER = "__other__";
function renderModelChoices(c) {
  const sel = $("#f-model"), groups = c.model_groups || [];
  const sig = JSON.stringify(groups);
  if (sig === app.modelSig) return;
  app.modelSig = sig;
  const current = sel.value;
  sel.innerHTML = groups.map((g) => `<optgroup label="${esc(g.provider)}">${
    g.models.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("")}</optgroup>`).join("") +
    `<optgroup label="Other"><option value="${OTHER}">Another model (type its name)</option></optgroup>`;
  const offered = [...sel.options].some((o) => o.value === current);
  sel.value = offered ? current : (groups.length ? c.default_model : OTHER);
  if (!offered && groups.length) $("#f-model-other").value = "";
  syncModelOther();
  // The same choices for the discovery agents, with "same as the analysis model" first.
  const dsel = $("#f-dmodel"), dcur = dsel.value;
  dsel.innerHTML = `<option value="">Same as the analysis model</option>` + groups.map((g) =>
    `<optgroup label="${esc(g.provider)}">${g.models.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("")}</optgroup>`).join("");
  dsel.value = [...dsel.options].some((o) => o.value === dcur) ? dcur : "";
  syncMoreDot();
}

// The three-dots menu in the form's corner: the turn budget, the agent layout and the model
// for the discovery agents. A dot on the button shows when any of them is off its default.
function syncMoreDot() {
  const changed = String($("#f-turns").value) !== "30" || $("#f-topology").value !== "adaptive" ||
    ($("#f-discovery").checked && $("#f-dmodel").value !== "");
  $("#more-dot").hidden = !changed;
  $("#f-dmodel-field").classList.toggle("off", !$("#f-discovery").checked);
}
function toggleMore(open) {
  const pop = $("#more-pop"), btn = $("#more-btn");
  const show = open === undefined ? pop.hidden : open;
  pop.hidden = !show;
  btn.setAttribute("aria-expanded", String(show));
  btn.classList.toggle("open", show);
}
function syncModelOther() {
  const other = $("#f-model").value === OTHER;
  $("#f-model-other").hidden = !other;
  $("#f-model-other").required = other;
}
function chosenModel() {
  const v = $("#f-model").value;
  return v === OTHER ? $("#f-model-other").value.trim() : v;
}

function renderKeyNote() {
  const c = app.config, has = c.keys.length > 0, note = $("#key-note");
  note.hidden = has;
  note.classList.toggle("missing", !has);
  note.innerHTML = `No model API key yet. <button type="button" class="linkish" data-open-keys>Add a key</button>
     to start an analysis.`;
  $("#f-start").disabled = !has;
  $("#keys-dot").classList.toggle("on", has);
  $("#keys-dot").classList.toggle("off", !has);
}

// ------------------------------------------------------------------ model keys panel

const SOURCE_TEXT = {
  settings: "Saved on this computer",
  environment: "From your shell environment",
  env_file: "From the .env file in this folder",
};

async function openKeys() {
  $("#keys-error").hidden = true;
  await refreshKeys();
  if (!$("#keys-dialog").open) $("#keys-dialog").showModal();
  // Put the cursor in the first empty key box, not on the close button.
  const empty = [...document.querySelectorAll("#keys-rows .kd-row:not(.has) input")][0];
  (empty || $("#keys-rows input")).focus();
}

async function refreshKeys() {
  const data = await api("/api/keys");
  $("#keys-file").textContent = data.file;
  const rows = $("#keys-rows");
  rows.innerHTML = "";
  for (const k of data.keys) rows.appendChild(keyRow(k));
}

function keyRow(k) {
  const on = Boolean(k.source);
  const node = el(`<div class="kd-row${on ? " has" : ""}">
    <div class="kd-name"><b>${esc(k.label)}</b>
      <span class="kd-status${on ? " on" : ""}">${on ? `${esc(SOURCE_TEXT[k.source] || "Set")} · ${esc(k.hint)}` : "Not set"}</span></div>
    <div class="kd-input">
      <input type="password" autocomplete="off" aria-label="${esc(k.label)} key"
             placeholder="${on ? "Paste a new key to replace it" : "Paste your key"}">
      <button class="btn btn-primary btn-sm" type="button" data-act="save">Save</button>
      ${k.source === "settings" ? `<button class="btn btn-ghost btn-sm" type="button" data-act="remove">Remove</button>` : ""}
    </div></div>`);
  const input = node.querySelector("input");
  node.querySelector('[data-act="save"]').addEventListener("click", () => saveKey(k.var, input));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") saveKey(k.var, input); });
  const remove = node.querySelector('[data-act="remove"]');
  if (remove) remove.addEventListener("click", () => removeKey(k.var, k.label));
  return node;
}

async function saveKey(name, input) {
  const err = $("#keys-error");
  err.hidden = true;
  const hadNone = !app.config || !app.config.keys.length;
  try {
    await api("/api/keys", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ var: name, value: input.value }),
    });
    input.value = "";
    await refreshKeys();
    await loadConfig(false);
    if (hadNone && app.config.keys.length) {         // the first key: straight on to the form
      $("#keys-dialog").close();
      $("#f-data").focus();
    }
    return true;
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    return false;
  }
}

async function removeKey(name, label) {
  if (!confirm(`Remove the saved ${label} key from this computer?`)) return;
  try {
    await api(`/api/keys/${encodeURIComponent(name)}`, { method: "DELETE" });
    await refreshKeys();
    await loadConfig(false);
  } catch (e) {
    $("#keys-error").textContent = e.message;
    $("#keys-error").hidden = false;
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
  const view = app.view = { id, total: 0, cell: 0, last: null, figSig: "", fileSig: "", discSig: "",
                            analysisStarted: false, info: null, timer: null, clock: null, finalPass: false, group: null };
  $("#timeline").innerHTML = "";
  $("#gallery").innerHTML = "";
  $("#file-rows").innerHTML = "";
  $("#stages").innerHTML = "";
  $("#disc-docs").innerHTML = "";
  $("#tab-discovery").hidden = true;
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
    if (!node) continue;
    // Everything one pre-analysis agent writes goes into its own group, open while it works
    // and folded as soon as the next agent (or the analysis) begins.
    const stage = stageOf(s.kind);
    if (view.group && view.group.key !== stage) closeGroup(view);
    if (stage && !view.group) openGroup(view, stage, timeline);
    (view.group ? view.group.body : timeline).appendChild(node);
    if (view.group) view.group.n += 1;
    view.last = node;
  }
  if (!info.active && view.group) closeGroup(view);
  view.total = log.total;
  if (log.sections.length) {
    if (follow) window.scrollTo({ top: document.documentElement.scrollHeight });
    else if (info.active) $("#to-latest").hidden = false;
  }
  renderFigures(view);
  renderFiles(view);
  if (info.discovery) {
    $("#tab-discovery").hidden = false;
    try { renderDiscovery(view, await api(`/api/runs/${encodeURIComponent(view.id)}/discovery`)); }
    catch (e) { /* shown on the next tick */ }
    if (app.view !== view) return;
  }
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
    r.topology && r.topology !== "adaptive" ? `<span>${esc(r.topology)} layout</span>` : "",
    r.discovery ? `<span>discovery mode${r.evolve ? "" : " (method discovery only)"}${
      r.discovery_model ? ` · discovery agents on <b>${esc(r.discovery_model)}</b>` : ""}</span>` : "",
  ].join("");
}

// ------------------------------------------------------------------ the Discovery tab

function renderDiscovery(view, d) {
  const r = view.info;
  const sig = JSON.stringify(d) + (view.analysisStarted ? "A" : "") + r.status;
  if (sig === view.discSig) return;
  view.discSig = sig;
  const nReq = Array.isArray(d.requests) ? d.requests.length : null;
  // Each stage: [label, done, detail, failed]. The first stage not done is the one running.
  const stages = [["Data report", d.report !== null, ""]];
  if (r.evolve) {
    const ev = d.evolution;
    stages.push(["Skill maker", ev !== null,
      ev ? (ev.status === "ok" ? `composed ${d.skills.length} skill${d.skills.length === 1 ? "" : "s"}` : ev.status || "") : "",
      ev && ev.status && ev.status !== "ok" && ev.status !== "no_target"]);
  }
  stages.push(["Plan", d.plan !== null, nReq === null ? "" : nReq ? `${nReq} method request${nReq === 1 ? "" : "s"}` : "no method request"]);
  const m = d.method;
  if (nReq || (m && m.status !== "no_request")) {
    stages.push(["Method discovery agent", m !== null,
      m ? (m.chosen ? `installed ${m.chosen}` : m.status || "") : "", m && m.status && !m.chosen]);
  }
  stages.push(["Analysis", view.analysisStarted, ""]);
  let nowSeen = false;
  $("#stages").innerHTML = stages.map(([label, done, detail, failed]) => {
    let cls = done ? "done" : "";
    if (!done && !nowSeen && r.active) { cls = "now"; nowSeen = true; }
    if (failed) cls = "failed";
    return `<li class="${cls}"><i></i>${esc(label)}${detail ? ` <span class="muted">· ${esc(detail)}</span>` : ""}</li>`;
  }).join("");

  const docs = [];
  const doc = (title, sub, body, open) =>
    `<details class="doc"${open ? " open" : ""}><summary>${esc(title)}${sub ? ` <span class="muted">${esc(sub)}</span>` : ""}</summary><div class="body md">${body}</div></details>`;
  if (d.report !== null) docs.push(doc("Data report", "what the data reporter found", d.report, false));
  for (const s of d.skills) docs.push(doc(`Composed skill: ${s.name}`, "written by the skill maker for this run", s.html, false));
  if (d.evolution && !d.skills.length)
    docs.push(doc("Skill maker", d.evolution.status || "", `<p>${esc(d.evolution.error || "No skill was composed.")}</p>`, true));
  if (d.plan !== null) docs.push(doc("Plan", "written by the planner before the analysis", d.plan, true));
  if (nReq) docs.push(doc("Method requests", `${nReq} from the plan`, `<pre>${esc(JSON.stringify(d.requests, null, 2))}</pre>`, false));
  if (m && m.status !== "no_request") {
    const rows = (m.candidates || []).map((c) => `<tr class="${c.name === m.chosen ? "chosen" : ""}">
      <td>${c.rank ?? ""}</td><td><b>${esc(c.name || "")}</b>${c.repo ? `<br><a href="${esc(c.url || `https://github.com/${c.repo}`)}" target="_blank" rel="noopener">${esc(c.repo)}</a>` : ""}</td>
      <td class="num">${c.stars ?? ""}</td><td class="num">${c.last_push ? esc(String(c.last_push).slice(0, 10)) : ""}</td>
      <td class="num">${c.fit_score ?? ""}</td><td>${esc(c.fit_notes || "")}</td></tr>`).join("");
    const head = m.chosen
      ? `<p><b>${esc(m.chosen)}</b> was chosen and ${m.install_status === "ok" || m.install_status === "installed" ? "installed" : `installation ended with status "${esc(m.install_status || m.status || "")}"`}.${m.import_name ? ` Import name: <code>${esc(m.import_name)}</code>.` : ""}</p>`
      : `<p>No method was installed (status: ${esc(m.status || "")}${m.error ? `; ${esc(m.error)}` : ""}).</p>`;
    const reason = m.choice_reason ? `<p>${esc(m.choice_reason)}</p>` : "";
    const table = rows ? `<table class="cands"><thead><tr><th>Rank</th><th>Candidate</th><th>Stars</th><th>Last update</th><th>Fit (0-5)</th><th>Notes</th></tr></thead><tbody>${rows}</tbody></table>` : "";
    docs.push(doc("Method discovery", m.model ? `agent on ${m.model}` : "", head + reason + table, true));
  }
  $("#disc-docs").innerHTML = docs.join("") ||
    `<div class="empty-state"><div class="mini-logo"><img src="/static/icon.svg" alt=""></div>Nothing written yet. The data reporter is reading the data.</div>`;
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
    : `<div class="empty-state"><div class="mini-logo"><img src="/static/icon.svg" alt=""></div>No figures yet.</div>`;
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
  for (const p of ["transcript", "discovery", "figures", "files"]) $(`#p-${p}`).hidden = p !== name;
}

// ------------------------------------------------------------------ events

$$(".pick-btns button").forEach((b) => b.addEventListener("click", () => pickPath(b.dataset.kind)));

// Discovery mode: the card itself shows the change (gradient edge, the button's wording), so
// the page needs no explanation text.
function syncDiscovery() {
  const on = $("#f-discovery").checked;
  $("#new-form").classList.toggle("discovery", on);
  $("#f-start-label").textContent = on ? "Start discovery" : "Start analysis";
  syncMoreDot();
}
$("#f-discovery").addEventListener("change", syncDiscovery);
$("#f-model").addEventListener("change", syncModelOther);
$("#more-btn").addEventListener("click", (ev) => { ev.stopPropagation(); toggleMore(); });
$("#more-pop").addEventListener("click", (ev) => ev.stopPropagation());
document.addEventListener("click", () => { if (!$("#more-pop").hidden) toggleMore(false); });
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("#more-pop").hidden) toggleMore(false); });
["#f-turns", "#f-topology", "#f-dmodel"].forEach((id) => $(id).addEventListener("input", syncMoreDot));

// Light or dark: the choice is kept in this browser; without one the system's setting is used
// (set before the first paint by the small script in the page head).
$("#theme-btn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("contexture-theme", next); } catch (e) { /* private window */ }
});

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
        model: chosenModel(),
        // One switch turns method discovery and skill evolution on together; the discovery
        // agents use the analysis model (the terminal's --discovery-model can set another).
        max_turns: $("#f-turns").value, topology: $("#f-topology").value,
        discovery: $("#f-discovery").checked, evolve: $("#f-discovery").checked,
        discovery_model: $("#f-discovery").checked ? $("#f-dmodel").value : "",
      }),
    });
    $("#f-goal").value = "";
    location.hash = `#/run/${id}`;
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    btn.disabled = !(app.config && app.config.keys.length);
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
$("#open-keys").addEventListener("click", () => openKeys());
$("#close-keys").addEventListener("click", () => $("#keys-dialog").close());
$("#keys-dialog").addEventListener("click", (ev) => {
  // Only a click on the dimmed backdrop closes it. A click on the panel's own padding also
  // targets the dialog element, so test the position, not just the target.
  const d = $("#keys-dialog"), r = d.getBoundingClientRect();
  const outside = ev.clientX < r.left || ev.clientX > r.right || ev.clientY < r.top || ev.clientY > r.bottom;
  if (ev.target === d && outside) d.close();
});
document.addEventListener("click", (ev) => {
  if (ev.target.closest("[data-open-keys]")) openKeys();
});
$("#other-save").addEventListener("click", async () => {
  const name = $("#other-var").value.trim().toUpperCase();
  if (await saveKey(name, $("#other-val"))) $("#other-var").value = "";
});
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
$("#to-latest").addEventListener("click", () => {
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  $("#to-latest").hidden = true;
});
window.addEventListener("scroll", () => { if (nearBottom()) $("#to-latest").hidden = true; });
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ start

startLattice();
loadConfig(true).catch(() => {});
route();
app.listTimer = setInterval(refreshList, 4000);
