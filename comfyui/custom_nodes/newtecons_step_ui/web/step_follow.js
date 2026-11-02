// Step-follow + agent a11y for every step bar (the dock for NEWTECONS image/video AND the generic nt-step-bar used by
// other domains). One singleton: one set of ComfyUI event listeners, one live status element, one title mirror.
// Reads app.graph / api events only; never writes the graph, never queues a prompt.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import * as F from "./step_follow_logic.js";

export const FOLLOW_CSS = `
.ntd-tab.ntf-run,.nt-tab.ntf-run{border-color:#0B4FD9!important;animation:ntf-pulse 1.1s ease-in-out infinite}
.ntd-tab.ntf-done::after,.nt-tab.ntf-done::after{content:"\\2713";color:#96E072;font-weight:800;margin-left:4px}
.ntd-tab.ntf-err,.nt-tab.ntf-err{border-color:#D00000!important;box-shadow:0 0 0 2px rgba(208,0,0,.45)}
.ntd-tab.ntf-err::after,.nt-tab.ntf-err::after{content:"!";color:#D00000;font-weight:800;margin-left:4px}
@keyframes ntf-pulse{0%,100%{box-shadow:0 0 0 1px #0B4FD9,0 0 4px #0B4FD9}50%{box-shadow:0 0 0 3px #5B9BF5,0 0 14px #0B4FD9}}
@media (prefers-reduced-motion:reduce){.ntd-tab.ntf-run,.nt-tab.ntf-run{animation:none;box-shadow:0 0 0 3px #5B9BF5}}
.ntf-head{font:700 11px/1.2 Inter,sans-serif;letter-spacing:.03em;color:#5B9BF5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;margin-top:2px}
.ntf-head.err{color:#D00000}
.ntf-head[hidden]{display:none}
.ntf-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ntf-toggle.on{background:#0B4FD9!important;border-color:#0B4FD9!important;color:#F7FAFD!important}
`;

const QUEUE_POLL_MS = 2500;
const entries = [];
let state = F.INITIAL;
let followOn = true;
let localPrompt = null;
let faded = false;
let fadeTimer = null;
let baseTitle = null;
let model = { at: 0, steps: [], nodePos: new Map() };
let head = null;
let statusEl = null;
let lastForeign = null;
let queueRemaining = 0;
let started = false;

try { followOn = F.parseFollowPref(localStorage.getItem(F.FOLLOW_KEY)); } catch { followOn = true; }

function node(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}

// Current workflow: steps from group titles + node positions by id. Cached 400 ms (progress events are frequent).
function currentModel() {
  const t = Date.now();
  if (t - model.at < 400) return model;
  const g = app.graph;
  const groups = (g?._groups || g?.groups || []).map((gr) => {
    const b = gr._bounding || gr.boundingRect || gr.bounding || [gr.pos?.[0], gr.pos?.[1], gr.size?.[0], gr.size?.[1]];
    return { title: gr.title, bounding: Array.from(b || [], Number) };
  });
  const nodePos = new Map();
  for (const n of g?._nodes || g?.nodes || []) if (n?.pos) nodePos.set(String(n.id), [n.pos[0], n.pos[1]]);
  model = { at: t, steps: F.stepsFromGroups(groups), nodePos };
  return model;
}

function dispatch(evt) {
  const m = currentModel();
  const prev = state;
  state = F.reduce(state, evt, { steps: m.steps, nodePos: m.nodePos, now: Date.now() });
  if (state === prev) return;
  faded = false;
  clearTimeout(fadeTimer);
  if (state.phase === "complete" || state.phase === "error") {
    fadeTimer = setTimeout(() => { faded = true; paint(); }, F.IDLE_RESTORE_MS);
  }
  paint();
  const target = F.followTarget(prev, state, followOn);
  if (target) switchTo(target);
}

function visible(e) {
  return Boolean(e && e.getClientRects().length > 0);
}

function userIsEditing(root) {
  const a = document.activeElement;
  return Boolean(a && root?.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/u.test(a.tagName));
}

function switchTo(code) {
  for (const en of entries) {
    const bar = en.bar();
    if (!visible(bar)) continue;
    const tab = [...bar.querySelectorAll(en.tabSel)].find((t) => t.dataset.code === code);
    if (!tab || tab.classList.contains("on") || userIsEditing(en.panel?.())) continue;
    tab.click();
  }
}

function ensureLive() {
  if (!head) {
    head = node("div", { class: "ntf-head", "data-testid": "ntc-step-header", hidden: "" });
    statusEl = node("div", { class: "ntf-sr", role: "status", "aria-live": "polite", "data-testid": "ntc-step-status" }, F.statusText(state));
  }
}

function placeLive() {
  ensureLive();
  const host = entries.map((en) => en.brand?.()).find((b) => b && visible(b));
  if (!host) return;
  if (head.parentNode !== host) host.append(head);
  if (statusEl.parentNode !== host) host.append(statusEl);
}

function paintTitle() {
  const t = faded ? "" : F.titleText(state);
  if (t) {
    if (document.title !== t) document.title = t;
  } else if (document.title.startsWith("NTC ") && baseTitle != null) {
    document.title = baseTitle; // restore the pre-job title (kept up to date while idle)
  }
}

function paint() {
  ensureLive();
  decorateAll();
  placeLive();
  const h = faded ? "" : F.headerText(state);
  head.textContent = h;
  head.hidden = !h;
  head.classList.toggle("err", state.phase === "error");
  statusEl.textContent = F.statusText(state);
  paintTitle();
}

function decorate(en) {
  const bar = en.bar();
  if (!bar) return;
  bar.setAttribute("role", "tablist");
  if (!bar.getAttribute("aria-label")) bar.setAttribute("aria-label", "Các bước của workflow");
  bar.setAttribute("data-testid", "ntc-step-bar");
  for (const tab of bar.querySelectorAll(en.tabSel)) {
    const code = tab.dataset.code;
    if (!code) continue;
    const st = F.tabStatus(state, code);
    const label = tab.querySelector("span")?.textContent || "";
    tab.classList.toggle("ntf-run", st === "running");
    tab.classList.toggle("ntf-done", st === "done");
    tab.classList.toggle("ntf-err", st === "error");
    tab.setAttribute("data-testid", F.testIdFor("tab", code));
    tab.setAttribute("data-status", st || "idle");
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-label", `Bước ${code} ${label}${st ? ` · ${{ running: "đang chạy", done: "xong", error: "lỗi" }[st]}` : ""}`.trim());
  }
}

function decorateAll() {
  for (const en of entries) decorate(en);
}

// Panel annotation: VÀO/RA slots and Run buttons get stable ids per step (agents / JEV).
function annotatePanel(en) {
  const panel = en.panel?.();
  const bar = en.bar();
  if (!panel || !bar) return;
  const code = bar.querySelector(`${en.tabSel}.on`)?.dataset.code;
  if (!code) return;
  panel.setAttribute("data-testid", `ntc-step-panel-${code}`);
  panel.setAttribute("aria-label", `Bảng bước ${code}`);
  const counts = {};
  const next = (kind) => (counts[kind] = (counts[kind] || 0) + 1);
  for (const s of panel.querySelectorAll(".ntd-slot, .nt-slot")) {
    const lbl = s.querySelector(":scope > .ntd-lbl, :scope > .nt-lbl");
    const kind = F.slotKind(lbl?.querySelector(".ntd-badge")?.textContent ?? lbl?.firstChild?.textContent);
    if (!kind) continue;
    s.setAttribute("data-testid", F.testIdFor(kind, code, next(kind)));
    s.setAttribute("role", "group");
    s.setAttribute("aria-label", `${kind === "vao" ? "VÀO" : "RA"} bước ${code}`);
  }
  for (const b of panel.querySelectorAll("button")) {
    const text = b.textContent || "";
    const kind = F.classifyButton({ text, act: b.dataset.act || "", inJob: Boolean(b.closest(".ntd-step-job")) });
    if (kind === "other") { if (!b.getAttribute("aria-label") && text.trim()) b.setAttribute("aria-label", text.trim()); continue; }
    b.setAttribute("data-testid", F.testIdFor(kind, code, next(kind)));
    b.setAttribute("aria-label", `${text.trim()} (bước ${code})`);
  }
}

function toggleNode(className) {
  const b = node("button", { type: "button", class: `${className} ntf-toggle${followOn ? " on" : ""}`, "data-testid": "ntc-step-follow-toggle",
    "aria-label": "Tự theo bước đang chạy", "aria-pressed": String(followOn), title: "Tự theo bước đang chạy: tab tự chuyển sang bước đang chạy" }, "TỰ THEO BƯỚC");
  b.addEventListener("click", () => {
    followOn = !followOn;
    try { localStorage.setItem(F.FOLLOW_KEY, followOn ? "1" : "0"); } catch { /* storage blocked: keep in memory */ }
    document.querySelectorAll(".ntf-toggle").forEach((x) => { x.classList.toggle("on", followOn); x.setAttribute("aria-pressed", String(followOn)); });
    if (followOn && state.phase === "running" && state.step) switchTo(state.step);
  });
  return b;
}

// Jobs queued by ANOTHER client never emit executing/progress to this tab, so poll /queue (only while the status
// event says something is queued, plus a slow sanity check) and follow the running prompt if its nodes are in this workflow.
async function pollQueue() {
  if (localPrompt && state.phase === "running" && !state.foreign) return;
  try {
    const res = await api.fetchApi("/queue", { cache: "no-store" });
    if (!res.ok) return;
    const q = await res.json();
    const running = Array.isArray(q.queue_running) ? q.queue_running[0] : null;
    if (!running) {
      if (lastForeign) { lastForeign = null; dispatch({ type: "foreign_end" }); }
      return;
    }
    const promptId = String(running[1] || "");
    if (running[3]?.client_id && running[3].client_id === api.clientId) return; // ours: events cover it
    if (promptId === lastForeign) return;
    lastForeign = promptId;
    dispatch({ type: "foreign", promptId, nodeIds: Object.keys(running[2] || {}) });
  } catch { /* server busy: next tick */ }
}

function start() {
  if (started) return;
  started = true;
  const on = (name, fn) => { try { api.addEventListener(name, (ev) => { try { fn(ev.detail); } catch (err) { console.warn("[ntc-follow]", name, err); } }); } catch { /* old frontend */ } };
  on("execution_start", (d) => { localPrompt = d?.prompt_id || "local"; lastForeign = null; dispatch({ type: "start", promptId: d?.prompt_id }); });
  on("executing", (d) => {
    const id = d && typeof d === "object" ? d.node ?? d.display_node : d;
    dispatch({ type: "executing", node: id ?? null, promptId: d?.prompt_id });
  });
  on("progress", (d) => dispatch({ type: "progress", value: d?.value, max: d?.max, node: d?.node }));
  on("executed", (d) => dispatch({ type: "executed", node: d?.node, output: d?.output }));
  on("execution_success", () => { localPrompt = null; dispatch({ type: "success" }); });
  on("execution_interrupted", () => { localPrompt = null; dispatch({ type: "error", node: null, message: "đã dừng (interrupted)" }); });
  on("execution_error", (d) => { localPrompt = null; dispatch({ type: "error", node: d?.node_id, message: d?.exception_message || d?.exception_type }); });
  on("status", (d) => { queueRemaining = Number(d?.status?.exec_info?.queue_remaining ?? d?.exec_info?.queue_remaining ?? 0); if (queueRemaining > 0) pollQueue(); });
  setInterval(pollQueue, QUEUE_POLL_MS * 4);
  setInterval(() => {
    if (!F.titleText(state) || faded) { if (!document.title.startsWith("NTC ")) baseTitle = document.title; }
    paintTitle(); // ComfyUI rewrites the title on progress: re-assert ours while a job is shown
  }, 1000);
  baseTitle = document.title;
}

export const follow = {
  // entry: {bar:()=>Element, tabSel, panel?:()=>Element, brand?:()=>Element}
  register(entry) { entries.push(entry); start(); },
  decorateAll,
  annotatePanel(bar) { const en = entries.find((x) => x.bar() === bar); if (en) annotatePanel(en); },
  toggleNode,
  refresh: paint,
  get state() { return state; },
};
