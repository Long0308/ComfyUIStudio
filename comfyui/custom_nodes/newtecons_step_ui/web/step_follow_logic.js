// Pure logic: step tabs FOLLOW the running ComfyUI job + agent-readable status text. No DOM — tested with node.
// Domain-neutral: steps come from workflow group titles "NN[A] LABEL" (NEWTECONS image/video and JennieJoy alike).

export const STEP_TITLE = /^(\d{2})([A-Z]?)\s+(.+)$/u;
export const IDLE_RESTORE_MS = 30000;
export const FOLLOW_KEY = "newtecons.dock.follow";

// groups [{title, bounding:[x,y,w,h]}] -> [{code,label,bounding}] (same title rule as parseSteps of image/video/step UI).
export function stepsFromGroups(groups) {
  const out = [];
  for (const g of groups || []) {
    const m = STEP_TITLE.exec(String(g?.title || "").trim());
    if (!m || !Array.isArray(g.bounding) || g.bounding.length < 4) continue;
    out.push({ code: m[1] + m[2], label: m[3], bounding: g.bounding.slice(0, 4).map(Number) });
  }
  return out;
}

function inside(pos, b) {
  return Array.isArray(pos) && pos[0] >= b[0] && pos[0] < b[0] + b[2] && pos[1] >= b[1] && pos[1] < b[1] + b[3];
}

function posOf(nodePos, id) {
  return nodePos instanceof Map ? nodePos.get(id) : nodePos?.[id];
}

// Node id (number | "12" | subgraph "12:5") -> step code, via the node position inside the group box.
// Overlapping groups: the smallest box wins. Unknown node -> null.
export function stepForNode(nodeId, steps, nodePos) {
  if (nodeId == null) return null;
  const sid = String(nodeId);
  for (const id of [sid, sid.split(":")[0]]) {
    const pos = posOf(nodePos, id);
    if (!pos) continue;
    let best = null;
    for (const s of steps || []) {
      if (inside(pos, s.bounding) && (!best || s.bounding[2] * s.bounding[3] < best.bounding[2] * best.bounding[3])) best = s;
    }
    return best ? best.code : null;
  }
  return null;
}

// Prompt (API format, keys = node ids) -> {known, step}: how many ids exist in the open workflow, and the step with most hits.
export function promptOverlap(promptNodeIds, nodePos, steps) {
  let known = 0;
  const hits = new Map();
  for (const id of promptNodeIds || []) {
    const sid = String(id);
    if (!posOf(nodePos, sid) && !posOf(nodePos, sid.split(":")[0])) continue;
    known += 1;
    const code = stepForNode(sid, steps, nodePos);
    if (code) hits.set(code, (hits.get(code) || 0) + 1);
  }
  let step = null;
  let top = 0;
  for (const [code, n] of hits) if (n > top) { top = n; step = code; }
  return { known, step };
}

export const INITIAL = Object.freeze({
  phase: "idle", promptId: null, foreign: false, step: null, node: null, pct: null,
  stepStatus: {}, file: "", msg: "", changedAt: 0,
});

const short = (id) => String(id || "").slice(0, 8);
const withStatus = (s, code, v) => (code ? { ...s.stepStatus, [code]: v } : s.stepStatus);

function finish(state, now) {
  const step = state.step;
  const stepStatus = step && state.stepStatus[step] !== "error" ? { ...state.stepStatus, [step]: "done" } : state.stepStatus;
  return { ...state, phase: "complete", pct: null, stepStatus, changedAt: now };
}

// Event reducer. evt: {type, ...}; ctx: {steps, nodePos, now}. Never mutates; never throws on odd payloads.
export function reduce(state, evt, ctx = {}) {
  const now = ctx.now ?? 0;
  const stepOf = (id) => stepForNode(id, ctx.steps, ctx.nodePos);
  switch (evt?.type) {
    case "start":
      return { ...INITIAL, phase: "running", promptId: evt.promptId ?? null, changedAt: now };
    case "executing": {
      if (evt.node == null) return state.phase === "running" && !state.foreign ? finish(state, now) : state;
      const step = stepOf(evt.node);
      let stepStatus = state.stepStatus;
      if (state.step && step !== state.step && stepStatus[state.step] !== "error") stepStatus = { ...stepStatus, [state.step]: "done" };
      if (step) stepStatus = { ...stepStatus, [step]: "running" };
      return { ...state, phase: "running", foreign: false, promptId: evt.promptId ?? state.promptId, step: step ?? state.step,
        node: String(evt.node), pct: null, stepStatus, changedAt: now };
    }
    case "progress": {
      const v = Number(evt.value);
      const m = Number(evt.max);
      const pct = Number.isFinite(v) && Number.isFinite(m) && m > 0 ? Math.max(0, Math.min(100, Math.round((v / m) * 100))) : state.pct;
      const node = evt.node != null ? String(evt.node) : state.node;
      const step = (evt.node != null ? stepOf(evt.node) : null) ?? state.step;
      const keep = step && state.stepStatus[step] === "error" ? "error" : "running";
      return { ...state, phase: state.phase === "idle" ? "running" : state.phase, step, node, pct,
        stepStatus: withStatus(state, step, keep), changedAt: now };
    }
    case "executed": {
      const out = evt.output || {};
      const imgs = out.images || out.gifs || out.video || [];
      const file = imgs.length ? String(imgs[imgs.length - 1]?.filename || "") : "";
      return file ? { ...state, file } : state;
    }
    case "success":
      return state.phase === "running" || state.phase === "idle" ? finish(state, now) : state;
    case "error": {
      const step = stepOf(evt.node) ?? state.step;
      return { ...state, phase: "error", step, node: evt.node != null ? String(evt.node) : state.node,
        stepStatus: withStatus(state, step, "error"), msg: String(evt.message || "lỗi").slice(0, 120), changedAt: now };
    }
    case "foreign": {
      // Job queued by another client: follow it only if its node ids exist in the open workflow.
      const o = promptOverlap(evt.nodeIds, ctx.nodePos, ctx.steps);
      const step = o.known > 0 ? o.step : null;
      return { ...INITIAL, phase: "running", foreign: o.known === 0, promptId: evt.promptId, step,
        stepStatus: step ? { [step]: "running" } : {}, changedAt: now };
    }
    case "foreign_end":
      return state.phase === "running" ? finish(state, now) : state;
    case "reset":
      return INITIAL;
    default:
      return state;
  }
}

const pad = (code) => (code == null ? "--" : code);

// One short machine-readable line for agents: "STEP 07 RUNNING 45%", "STEP 07 COMPLETE x.png", "STEP 07 ERROR msg".
export function statusText(s) {
  if (!s || s.phase === "idle") return "STEP IDLE";
  if (s.foreign) return `OTHER JOB RUNNING ${short(s.promptId)}`;
  const head = `STEP ${pad(s.step)}`;
  if (s.phase === "running") return `${head} RUNNING${s.pct != null ? ` ${s.pct}%` : ""}`;
  if (s.phase === "complete") return `${head} COMPLETE${s.file ? ` ${s.file}` : ""}`;
  if (s.phase === "error") return `${head} ERROR ${s.msg || ""}`.trim();
  return "STEP IDLE";
}

// Human line for the dock header.
export function headerText(s) {
  if (!s || s.phase === "idle") return "";
  if (s.foreign) return `Đang chạy job khác (prompt ${short(s.promptId)})`;
  const n = s.node != null ? ` · node ${s.node}` : "";
  if (s.phase === "running") return `Đang chạy bước ${pad(s.step)}${n}${s.pct != null ? ` · ${s.pct}%` : ""}`;
  if (s.phase === "complete") return `Xong bước ${pad(s.step)}${s.file ? ` · ${s.file}` : ""}`;
  return `LỖI bước ${pad(s.step)}${n}${s.msg ? ` · ${s.msg}` : ""}`;
}

// document.title mirror: only while a job runs / just finished / failed; "" = restore the original title.
export function titleText(s) {
  if (!s || s.phase === "idle") return "";
  if (s.foreign) return "NTC OTHER JOB RUNNING";
  const word = s.phase === "running" ? "RUNNING" : s.phase === "complete" ? "COMPLETE" : "ERROR";
  return `NTC STEP ${pad(s.step)} ${word}`;
}

// Tab state for one code: "running" | "done" | "error" | "".
export function tabStatus(s, code) {
  return (s?.stepStatus && s.stepStatus[code]) || "";
}

// Auto-switch decision: the code to switch to, or null.
export function followTarget(prev, next, enabled) {
  if (!enabled || next.phase !== "running" || !next.step) return null;
  return prev.step !== next.step || prev.phase !== "running" ? next.step : null;
}

export function parseFollowPref(raw) {
  return !(raw === "0" || raw === "false");
}

// Button role from its text / data-act / container -> "run" | "auto" | "autostop" | "other".
export function classifyButton({ text = "", act = "", inJob = false } = {}) {
  const t = String(text).trim().toLowerCase();
  if (/^stop\b/u.test(t)) return "autostop";
  if (/^chạy/u.test(t) && /tự động/u.test(t)) return "auto";
  if (act === "run-n" || (/^chạy/u.test(t) && inJob)) return "run";
  return "other";
}

// Badge text -> slot kind for the VÀO / RA panels.
export function slotKind(badgeText) {
  const t = String(badgeText || "").trim().toUpperCase().split(/\s+/u)[0];
  return t === "VÀO" ? "vao" : t === "RA" ? "ra" : null;
}

export function testIdFor(kind, code, n = 1) {
  return `ntc-step-${kind}-${code}${n > 1 ? `-${n}` : ""}`;
}
