// node --experimental-vm-modules tests/test_step_dock_logic.mjs — shared dock geometry + themes (video gold / image blue).
import assert from "node:assert/strict";
import * as D from "../web/step_dock_logic.js";
import { SourceTextModule } from "node:vm";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../web");

const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}

// Rects measured in the live ComfyUI 1680×1000 (2026-10-31): Workflows sidebar closed / open, right panel open.
const CLOSED = { vw: 1680, vh: 1000, tabs: { left: 0, top: 0, right: 1680, bottom: 38 }, action: { left: 1035, top: 54, right: 1336, bottom: 86 },
  nested: { left: 56, top: 38, right: 1353, bottom: 1000 }, sideTool: { left: 0, top: 38, right: 56, bottom: 1000 }, sidePanel: null };
const OPEN = { ...CLOSED, action: { left: 1101, top: 54, right: 1402, bottom: 86 }, nested: { left: 372, top: 38, right: 1419, bottom: 1000 },
  sidePanel: { left: 56, top: 38, right: 368, bottom: 1000 } };

test("region stays inside the canvas column: never over sidebar tree, tabs or Run bar", () => {
  const r = D.canvasRegion(CLOSED);
  assert.deepEqual(r, { left: 64, top: 94, right: 1345, bottom: 992 });
  const o = D.canvasRegion(OPEN);
  assert.ok(o.left >= 368 + D.GAP, `left ${o.left} must clear the Workflows panel (368)`);
  assert.ok(o.top >= 86, "below the Run/queue bar");
  assert.ok(o.right <= 1419, "before the right panel");
});

test("opening the sidebar shrinks the dock instead of overlapping", () => {
  const a = D.dockLayout("top", D.canvasRegion(CLOSED), 44);
  const b = D.dockLayout("top", D.canvasRegion(OPEN), 44);
  assert.ok(b.panel.left > a.panel.left && b.panel.right - b.panel.left < a.panel.right - a.panel.left);
  assert.ok(b.bar.left >= 376);
});

test("fallback without the nested splitter uses tool bar + side panel", () => {
  const r = D.canvasRegion({ vw: 1200, vh: 800, sideTool: { left: 0, top: 0, right: 50, bottom: 800 }, sidePanel: { left: 50, top: 0, right: 300, bottom: 800 } });
  assert.equal(r.left, 308);
  assert.equal(r.right, 1192);
});

test("default TRÊN ≈45% and the graph keeps ≥ 50% of the canvas height (both sidebar states)", () => {
  for (const m of [CLOSED, OPEN]) {
    const region = D.canvasRegion(m);
    const lay = D.dockLayout("top", region, 44, D.DEFAULT_PREFS);
    const H = region.bottom - region.top;
    const freeH = lay.free.bottom - lay.free.top;
    assert.ok(freeH >= H * 0.5 - 1e-6, `free ${freeH} of ${H}`);
    assert.ok(lay.share >= 0.5 - 1e-6, `share ${lay.share}`);
    const ph = lay.panel.bottom - lay.panel.top;
    assert.ok(ph >= D.MIN_PANEL_H && ph <= H * 0.5, `panel ${ph}`);
  }
});

test("dragging cannot push TRÊN past half the canvas", () => {
  const region = D.canvasRegion(CLOSED);
  const f = D.fracFromDrag("top", region, { x: 500, y: 990 });
  assert.equal(f, 0.5);
  const lay = D.dockLayout("top", region, 44, D.withPrefs(D.DEFAULT_PREFS, { topFrac: f }));
  assert.ok(lay.free.bottom - lay.free.top >= (region.bottom - region.top) * 0.5 - 1e-6);
  assert.equal(D.fracFromDrag("top", region, { x: 0, y: 0 }), 0.15);
});

test("PHẢI drawer ≈40% width, max 50%, graph keeps the left part", () => {
  const region = D.canvasRegion(CLOSED);
  const W = region.right - region.left;
  const lay = D.dockLayout("right", region, 44, D.DEFAULT_PREFS);
  const w = lay.panel.right - lay.panel.left;
  assert.ok(Math.abs(w - 0.4 * W) <= 1, `w ${w}`);
  assert.equal(lay.free.right, lay.panel.left - D.GAP);
  assert.ok(lay.share >= 0.5);
  assert.equal(D.fracFromDrag("right", region, { x: region.left, y: 300 }), 0.5);
  const narrow = D.dockLayout("right", { left: 0, top: 0, right: 500, bottom: 600 }, 44, D.DEFAULT_PREFS);
  assert.ok(narrow.panel.right - narrow.panel.left <= 250);
});

test("THU GỌN keeps only the bar; graph gets everything below it", () => {
  const region = D.canvasRegion(CLOSED);
  const lay = D.dockLayout("collapsed", region, 44);
  assert.equal(lay.panel, null);
  assert.equal(lay.free.top, region.top + 44 + D.GAP);
  assert.equal(D.fracFromDrag("collapsed", region, { x: 1, y: 1 }), null);
});

test("prefs parse: bad JSON / unknown mode / out-of-range fractions fall back", () => {
  assert.deepEqual(D.parsePrefs(null), { ...D.DEFAULT_PREFS });
  assert.deepEqual(D.parsePrefs("{oops"), { ...D.DEFAULT_PREFS });
  const p = D.parsePrefs(JSON.stringify({ mode: "left", topFrac: 0.9, rightFrac: 0.1, card: "yes" }));
  assert.deepEqual(p, { mode: "top", topFrac: 0.5, rightFrac: 0.25, card: false });
  assert.equal(D.withPrefs(p, { mode: "right" }).mode, "right");
});

test("fitInto puts the group inside the free rect; screenRect inverts it", () => {
  const free = { left: 64, top: 520, right: 1345, bottom: 992 };
  const canvas = { left: 0, top: 0 };
  const b = [5440, 0, 1360, 2200];
  const ds = D.fitInto(b, canvas, free);
  const r = D.screenRect(b, canvas, ds);
  assert.ok(r.left >= free.left - 1e-6 && r.right <= free.right + 1e-6, JSON.stringify(r));
  assert.ok(r.top >= free.top - 1e-6 && r.bottom <= free.bottom + 1e-6, JSON.stringify(r));
});

test("themes: video gold, image blue has no orange/yellow; tokens complete", () => {
  assert.equal(D.themeHasWarm("blue"), false);
  assert.equal(D.themeHasWarm("gold"), true);
  for (const k of Object.keys(D.THEMES.gold)) assert.ok(D.THEMES.blue[k], k);
  assert.equal(D.THEMES.blue.accs, "#0B4FD9");
  assert.equal(D.THEMES.blue.acc, "#5B9BF5");
  assert.equal(D.THEMES.blue.acc2, "#9D9BF5");
  assert.equal(D.THEMES.blue.ok, "#3E8914");
  assert.equal(D.THEMES.blue.bad, "#D00000");
  assert.throws(() => D.themeVars("pink"));
});

test("stacking: every dock layer is below ComfyUI's overlay layer (z-999: job popover, Run bar, side panels)", () => {
  assert.equal(D.COMFY_OVERLAY_Z, 999);
  for (const [k, z] of Object.entries(D.Z)) assert.ok(Number.isInteger(z) && z > 0 && z < D.COMFY_OVERLAY_Z, `${k}=${z}`);
  assert.ok(D.Z.highlight < D.Z.panel && D.Z.panel < D.Z.bar && D.Z.bar < D.Z.handle);
  const css = readFileSync(path.join(WEB, "step_dock.js"), "utf8");
  const hard = [...css.matchAll(/z-index:\s*(\d+)/gu)].map((m) => Number(m[1])).filter((z) => z >= D.COMFY_OVERLAY_Z);
  assert.deepEqual(hard, [], "no hard-coded z-index at/above ComfyUI's overlay layer");
});

test("step aside: with the job popover open (measured [995,98,1345,392]) the dock ends before it", () => {
  const pop = { left: 995, top: 98, right: 1345, bottom: 392 };
  const r = D.canvasRegion({ ...CLOSED, overlays: [pop] });
  assert.ok(r.right <= pop.left - D.GAP + 1e-6, `right ${r.right}`);
  const lay = D.dockLayout("top", r, 44);
  assert.ok(lay.bar.right <= pop.left && lay.panel.right <= pop.left);
  assert.deepEqual(D.canvasRegion({ ...CLOSED, overlays: [] }), D.canvasRegion(CLOSED), "closed popover changes nothing");
  assert.deepEqual(D.canvasRegion({ ...CLOSED, overlays: [{ left: 80, top: 100, right: 200, bottom: 300 }] }), D.canvasRegion(CLOSED), "ignores things at the far left");
});

test("every panel file parses as an ES module (the browser drops the whole extension on one syntax error)", () => {
  const files = ["step_dock.js", "step_dock_logic.js", "video_ui.js", "video_ui_logic.js", "image_ui.js", "image_ui_logic.js"];
  for (const f of files) {
    // Run this test with node --experimental-vm-modules: parse without importing browser APIs
    // or spawning child processes (the workspace sandbox can deny nested process creation).
    assert.doesNotThrow(() => new SourceTextModule(readFileSync(path.join(WEB, f), "utf8"), { identifier: f }), f);
  }
});

for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
