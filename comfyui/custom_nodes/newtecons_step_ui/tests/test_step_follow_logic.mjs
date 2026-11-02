// node --experimental-vm-modules tests/test_step_follow_logic.mjs — step-follow reducer, node->group->step mapping, status/title text, a11y ids.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SourceTextModule } from "node:vm";
import * as F from "../web/step_follow_logic.js";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../web");
const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}

const groups = [
  { title: "00 CHỌN LUỒNG", bounding: [0, 0, 400, 300] },
  { title: "02A NEO TRANG PHỤC", bounding: [450, 0, 400, 300] },
  { title: "07 DÁNG", bounding: [900, 0, 400, 300] },
  { title: "07X nhỏ trong 07", bounding: [950, 50, 100, 100] },
  { title: "Ghi chú tự do", bounding: [0, 400, 100, 100] },
];
const steps = F.stepsFromGroups(groups);
const nodePos = new Map([["1", [10, 10]], ["5", [460, 20]], ["9", [910, 20]], ["10", [960, 60]], ["11", [5000, 5000]], ["12", [20, 20]]]);
const ctx = (now = 1) => ({ steps, nodePos, now });

test("stepsFromGroups keeps only NN[A] LABEL groups", () => {
  assert.deepEqual(steps.map((s) => s.code), ["00", "02A", "07", "07X"]);
});
test("stepForNode: inside box, smallest box wins on overlap, outside = null, subgraph id uses prefix", () => {
  assert.equal(F.stepForNode(5, steps, nodePos), "02A");
  assert.equal(F.stepForNode("9", steps, nodePos), "07");
  assert.equal(F.stepForNode("10", steps, nodePos), "07X");
  assert.equal(F.stepForNode("11", steps, nodePos), null);
  assert.equal(F.stepForNode("12:3", steps, nodePos), "00");
  assert.equal(F.stepForNode("999", steps, nodePos), null);
  assert.equal(F.stepForNode(null, steps, nodePos), null);
});
test("running: executing sets RUNNING step, progress gives pct, texts match the agent format", () => {
  let s = F.reduce(F.INITIAL, { type: "start", promptId: "abcdef123456" }, ctx());
  s = F.reduce(s, { type: "executing", node: "9" }, ctx());
  s = F.reduce(s, { type: "progress", value: 9, max: 20, node: "9" }, ctx());
  assert.equal(F.statusText(s), "STEP 07 RUNNING 45%");
  assert.equal(F.headerText(s), "Đang chạy bước 07 · node 9 · 45%");
  assert.equal(F.titleText(s), "NTC STEP 07 RUNNING");
  assert.equal(F.tabStatus(s, "07"), "running");
});
test("next step marks the previous DONE; success marks the last DONE with the output filename", () => {
  let s = F.reduce(F.INITIAL, { type: "start" }, ctx());
  s = F.reduce(s, { type: "executing", node: "1" }, ctx());
  s = F.reduce(s, { type: "executing", node: "5" }, ctx());
  assert.equal(F.tabStatus(s, "00"), "done");
  assert.equal(F.tabStatus(s, "02A"), "running");
  s = F.reduce(s, { type: "executed", node: "5", output: { images: [{ filename: "a.png" }, { filename: "b.png" }] } }, ctx());
  s = F.reduce(s, { type: "success" }, ctx());
  assert.equal(F.tabStatus(s, "02A"), "done");
  assert.equal(F.statusText(s), "STEP 02A COMPLETE b.png");
  assert.equal(F.titleText(s), "NTC STEP 02A COMPLETE");
});
test("executing with null node (old end-of-prompt protocol) completes a local run once", () => {
  let s = F.reduce(F.INITIAL, { type: "start" }, ctx());
  s = F.reduce(s, { type: "executing", node: "9" }, ctx());
  s = F.reduce(s, { type: "executing", node: null }, ctx());
  assert.equal(s.phase, "complete");
  const again = F.reduce(s, { type: "success" }, ctx());
  assert.equal(again.phase, "complete");
  assert.equal(F.tabStatus(again, "07"), "done");
});
test("error marks that step ERROR and later progress does not overwrite it", () => {
  let s = F.reduce(F.INITIAL, { type: "start" }, ctx());
  s = F.reduce(s, { type: "executing", node: "9" }, ctx());
  s = F.reduce(s, { type: "error", node: "9", message: "CUDA out of memory" }, ctx());
  assert.equal(F.statusText(s), "STEP 07 ERROR CUDA out of memory");
  assert.equal(F.tabStatus(s, "07"), "error");
  assert.equal(F.titleText(s), "NTC STEP 07 ERROR");
  assert.equal(F.tabStatus(F.reduce(s, { type: "progress", value: 1, max: 2, node: "9" }, ctx()), "07"), "error");
});
test("progress: invalid max keeps previous pct; clamps to 0..100", () => {
  let s = F.reduce(F.INITIAL, { type: "executing", node: "9" }, ctx());
  s = F.reduce(s, { type: "progress", value: 5, max: 10, node: "9" }, ctx());
  assert.equal(s.pct, 50);
  assert.equal(F.reduce(s, { type: "progress", value: "x", max: 0 }, ctx()).pct, 50);
  assert.equal(F.reduce(s, { type: "progress", value: 50, max: 10, node: "9" }, ctx()).pct, 100);
});
test("node outside every group: STEP -- and nothing highlighted", () => {
  const s = F.reduce(F.INITIAL, { type: "executing", node: "11" }, ctx());
  assert.equal(F.statusText(s), "STEP -- RUNNING");
  assert.deepEqual(s.stepStatus, {});
});
test("job from ANOTHER client whose nodes exist here follows the step with most hits", () => {
  const s = F.reduce(F.INITIAL, { type: "foreign", promptId: "11112222-aaaa", nodeIds: ["9", "10", "5", "9999"] }, ctx());
  assert.equal(s.foreign, false);
  assert.equal(F.tabStatus(s, s.step), "running");
  assert.ok(["07", "07X", "02A"].includes(s.step));
  const t = F.reduce(F.INITIAL, { type: "foreign", promptId: "p", nodeIds: ["9", "9", "5"] }, ctx());
  assert.equal(F.promptOverlap(["9", "5", "1"], nodePos, steps).known, 3);
  assert.equal(t.foreign, false);
});
test("job from another client with NO node here shows 'Đang chạy job khác (prompt <id8>)'", () => {
  const s = F.reduce(F.INITIAL, { type: "foreign", promptId: "11112222-aaaa-bbbb", nodeIds: ["7000", "7001"] }, ctx());
  assert.equal(s.foreign, true);
  assert.equal(F.headerText(s), "Đang chạy job khác (prompt 11112222)");
  assert.equal(F.statusText(s), "OTHER JOB RUNNING 11112222");
  assert.equal(F.titleText(s), "NTC OTHER JOB RUNNING");
  assert.equal(F.reduce(s, { type: "foreign_end" }, ctx()).phase, "complete");
});
test("idle: empty header and empty title (original title restored); restore delay 30 s", () => {
  assert.equal(F.headerText(F.INITIAL), "");
  assert.equal(F.titleText(F.INITIAL), "");
  assert.equal(F.statusText(F.INITIAL), "STEP IDLE");
  assert.equal(F.IDLE_RESTORE_MS, 30000);
});
test("reducer never mutates its input and ignores unknown events", () => {
  const frozen = Object.freeze({ ...F.INITIAL, stepStatus: Object.freeze({}) });
  F.reduce(frozen, { type: "executing", node: "9" }, ctx());
  assert.equal(F.reduce(frozen, { type: "nope" }, ctx()), frozen);
  assert.equal(F.reduce(frozen, null, ctx()), frozen);
});
test("followTarget: switch only when ON and the running step changed", () => {
  const a = F.reduce(F.INITIAL, { type: "executing", node: "1" }, ctx());
  const b = F.reduce(a, { type: "executing", node: "9" }, ctx());
  assert.equal(F.followTarget(a, b, true), "07");
  assert.equal(F.followTarget(a, b, false), null);
  assert.equal(F.followTarget(b, F.reduce(b, { type: "progress", value: 1, max: 2, node: "9" }, ctx()), true), null);
  assert.equal(F.followTarget(b, F.reduce(b, { type: "success" }, ctx()), true), null);
});
test("toggle pref: default ON, only '0'/'false' turn it off", () => {
  assert.equal(F.parseFollowPref(null), true);
  assert.equal(F.parseFollowPref("1"), true);
  assert.equal(F.parseFollowPref("0"), false);
  assert.equal(F.parseFollowPref("false"), false);
});
test("a11y ids and button roles", () => {
  assert.equal(F.testIdFor("tab", "07"), "ntc-step-tab-07");
  assert.equal(F.testIdFor("run", "07"), "ntc-step-run-07");
  assert.equal(F.testIdFor("ra", "07", 2), "ntc-step-ra-07-2");
  assert.equal(F.slotKind("VÀO"), "vao");
  assert.equal(F.slotKind("RA — Sau"), "ra");
  assert.equal(F.slotKind("x"), null);
  assert.equal(F.classifyButton({ text: "CHẠY N PROMPT", act: "run-n" }), "run");
  assert.equal(F.classifyButton({ text: "Chạy (preview)", inJob: true }), "run");
  assert.equal(F.classifyButton({ text: "Chạy tự động 9 ô" }), "auto");
  assert.equal(F.classifyButton({ text: "Stop — dừng các ô còn lại" }), "autostop");
  assert.equal(F.classifyButton({ text: "GHI CÀI ĐẶT VÀO GRAPH" }), "other");
});
test("no orange/yellow in the new CSS; changed modules parse as ES modules", () => {
  const src = readFileSync(path.join(WEB, "step_follow.js"), "utf8");
  assert.doesNotMatch(src, /#(F5B700|FFD34D|FF6B00|FFB347|FFA500|FFC107)/iu);
  assert.match(src, /#0B4FD9/u);
  for (const f of ["step_follow.js", "step_follow_logic.js", "step_dock.js", "step_ui.js"]) {
    assert.doesNotThrow(() => new SourceTextModule(readFileSync(path.join(WEB, f), "utf8"), { identifier: f }), f);
  }
});

for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
