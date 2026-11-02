// Pure dock geometry + themes shared by the VIDEO (gold) and IMAGE (blue) step panels. No DOM — tested with node.
// The panels live ONLY inside ComfyUI's graph-canvas region: between the left tool bar / open side panel and
// the right side panel, below the workflow tabs and the Run/queue action bar.

export const MODES = ["top", "right", "collapsed"];
export const MODE_LABEL = { top: "TRÊN", right: "PHẢI", collapsed: "THU GỌN" };
export const GAP = 8;
export const MIN_PANEL_H = 170;
export const MIN_PANEL_W = 320;
export const DEFAULT_PREFS = Object.freeze({ mode: "top", topFrac: 0.45, rightFrac: 0.4, card: false });
// Stacking. ComfyUI 1.55 draws every overlay of the canvas (Run/queue bar, the "N active" job popover, side panels,
// canvas toolbar) inside ONE layer "div.pointer-events-none.absolute.z-999" (measured 31/10); PrimeVue dialogs,
// toasts and LiteGraph context menus sit higher still. The dock must stay above the canvas but BELOW all of them.
export const COMFY_OVERLAY_Z = 999;
export const Z = Object.freeze({ highlight: 994, panel: 995, bar: 996, handle: 997 });
const TOP_RANGE = [0.15, 0.5];
const RIGHT_RANGE = [0.25, 0.5];

// Theme tokens. gold = user exception 2026-10-31 for the VIDEO panel only; blue = Blue Web (image panel).
export const THEMES = {
  gold: {
    acc: "#F5B700", accs: "#F5B700", acc2: "#FFD34D", on: "#120E00", accl: "rgba(245,183,0,.42)", accf: "rgba(245,183,0,.10)",
    ink: "#0B0B0C", card: "#141413", text: "#F3EAD3", mute: "#A39878", line: "rgba(245,183,0,.16)",
    ok: "#96E072", bad: "#FF5A4F",
  },
  blue: {
    acc: "#5B9BF5", accs: "#0B4FD9", acc2: "#9D9BF5", on: "#F7FAFD", accl: "rgba(91,155,245,.40)", accf: "rgba(11,79,217,.18)",
    ink: "#07111F", card: "#0A1A30", text: "#F7FAFD", mute: "#A9B8D8", line: "#5C6795",
    ok: "#3E8914", bad: "#D00000",
  },
};
const NO_WARM = /#(F5B700|FFD34D|FF6B00|FFB347|FFA500|FFC107)|rgba\(245,\s*183/iu;

export function themeVars(name) {
  const t = THEMES[name];
  if (!t) throw new Error(`unknown theme ${name}`);
  return Object.entries(t).map(([k, v]) => `--${k}:${v}`).join(";");
}

export function themeHasWarm(name) {
  return NO_WARM.test(themeVars(name));
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

function num(v, lo, hi, d) {
  return typeof v === "number" && Number.isFinite(v) ? clamp(v, lo, hi) : d;
}

// localStorage value -> prefs (bad JSON / unknown values fall back to defaults; never throws).
export function parsePrefs(raw) {
  let o = {};
  try { o = typeof raw === "string" && raw ? JSON.parse(raw) : {}; } catch { o = {}; }
  if (!o || typeof o !== "object") o = {};
  return {
    mode: MODES.includes(o.mode) ? o.mode : DEFAULT_PREFS.mode,
    topFrac: num(o.topFrac, ...TOP_RANGE, DEFAULT_PREFS.topFrac),
    rightFrac: num(o.rightFrac, ...RIGHT_RANGE, DEFAULT_PREFS.rightFrac),
    card: typeof o.card === "boolean" ? o.card : DEFAULT_PREFS.card,
  };
}

export function withPrefs(prefs, patch) {
  return parsePrefs(JSON.stringify({ ...prefs, ...patch }));
}

function visible(r) {
  return Boolean(r && r.right - r.left > 1 && r.bottom - r.top > 1);
}

// Measured rects -> the free canvas region. m: {vw, vh, tabs, action, nested, sideTool, sidePanel, rightPanel}.
// nested = ComfyUI's ".p-splitterpanel-nested" (the column between the left side panel and the right panel).
export function canvasRegion(m) {
  const vw = m.vw;
  const vh = m.vh;
  let left = visible(m.nested) ? m.nested.left : visible(m.sideTool) ? m.sideTool.right : 0;
  if (visible(m.sideTool)) left = Math.max(left, m.sideTool.right);
  if (visible(m.sidePanel)) left = Math.max(left, m.sidePanel.right);
  let right = visible(m.nested) ? m.nested.right : vw;
  if (visible(m.rightPanel) && m.rightPanel.left > left) right = Math.min(right, m.rightPanel.left);
  let top = Math.max(visible(m.tabs) ? m.tabs.bottom : 0, visible(m.nested) ? m.nested.top : 0);
  if (visible(m.action) && m.action.left < right && m.action.right > left && m.action.top < top + 80) {
    top = Math.max(top, m.action.bottom);
  }
  // Step aside for ComfyUI's own panels that open under the Run bar (the "N active" job/queue popover): while one
  // is open the dock ends before its left edge instead of sitting under it.
  for (const o of m.overlays || []) {
    if (visible(o) && o.left > left + 200 && o.left < right && o.bottom > top) right = Math.min(right, o.left);
  }
  const bottom = visible(m.nested) ? Math.min(vh, m.nested.bottom) : vh;
  return {
    left: Math.round(clamp(left + GAP, 0, vw)), top: Math.round(clamp(top + GAP, 0, vh)),
    right: Math.round(clamp(right - GAP, 0, vw)), bottom: Math.round(clamp(bottom - GAP, 0, vh)),
  };
}

function area(r) {
  return r ? Math.max(0, r.right - r.left) * Math.max(0, r.bottom - r.top) : 0;
}

// Bar always spans the region top. top: panel below the bar, height capped so the graph keeps >= 50% of the
// region height; right: drawer capped at 50% of the region width; collapsed: bar only.
export function dockLayout(mode, region, barH, prefs = DEFAULT_PREFS) {
  const W = region.right - region.left;
  const H = region.bottom - region.top;
  const bar = { left: region.left, top: region.top, right: region.right, bottom: region.top + barH };
  const below = bar.bottom + GAP;
  let panel = null;
  let free = { left: region.left, top: below, right: region.right, bottom: region.bottom };
  if (mode === "top") {
    const maxH = Math.max(80, H * 0.5 - barH - 2 * GAP);
    const h = Math.round(clamp(prefs.topFrac * H, Math.min(MIN_PANEL_H, maxH), maxH));
    panel = { left: region.left, top: below, right: region.right, bottom: below + h };
    free = { ...free, top: panel.bottom + GAP };
  } else if (mode === "right") {
    const maxW = W * 0.5;
    const w = Math.round(clamp(prefs.rightFrac * W, Math.min(MIN_PANEL_W, maxW), maxW));
    panel = { left: region.right - w, top: below, right: region.right, bottom: region.bottom };
    free = { ...free, right: panel.left - GAP };
  }
  return { bar, panel, free, share: area(region) ? area(free) / area(region) : 0, regionArea: area(region) };
}

// Pointer position during a handle drag -> new fraction (clamped to the allowed range).
export function fracFromDrag(mode, region, pointer) {
  if (mode === "top") return clamp((pointer.y - region.top) / Math.max(1, region.bottom - region.top), ...TOP_RANGE);
  if (mode === "right") return clamp((region.right - pointer.x) / Math.max(1, region.right - region.left), ...RIGHT_RANGE);
  return null;
}

// LiteGraph: screen = (graph + offset) * scale. Fit bounding into the free rect (screen coords).
export function fitInto(b, canvasRect, free, margin = 24) {
  const availW = Math.max(80, free.right - free.left - 2 * margin);
  const availH = Math.max(80, free.bottom - free.top - 2 * margin);
  const scale = clamp(Math.min(availW / b[2], availH / b[3]), 0.05, 2);
  const sx = free.left - canvasRect.left + margin + (availW - b[2] * scale) / 2;
  const sy = free.top - canvasRect.top + margin + (availH - b[3] * scale) / 2;
  return { scale, offset: [sx / scale - b[0], sy / scale - b[1]] };
}

export function screenRect(b, canvasRect, ds) {
  const x = (b[0] + ds.offset[0]) * ds.scale + canvasRect.left;
  const y = (b[1] + ds.offset[1]) * ds.scale + canvasRect.top;
  return { left: x, top: y, right: x + b[2] * ds.scale, bottom: y + b[3] * ds.scale };
}

export function mediaHeight(mode, panel) {
  if (!panel) return 0;
  const h = panel.bottom - panel.top;
  return Math.max(110, Math.round(mode === "top" ? h - 150 : Math.min(360, h * 0.42)));
}
