// node tests/test_domain_whitelist.mjs — NEWTECONS bars show ONLY when the detected domain === newtecons_live_action.
// Unknown (null) and JennieJoy domains must hide the image and video bars, even with NEWTECONS-looking groups.
import assert from "node:assert/strict";
import * as IL from "../web/image_ui_logic.js";
import * as VL from "../web/video_ui_logic.js";

const NTC = "newtecons_live_action";
const JJ = "jenniejoy_cartoon_3d";
const imageGroups = [{ title: "00 ROUTE", bounding: [0, 0, 1, 1] }, { title: "02 ASSET", bounding: [2, 0, 1, 1] }, { title: "03 OUT", bounding: [4, 0, 1, 1] }];
const videoGroups = VL.VIDEO_STEPS.map((s) => ({ title: `${s.code} ${s.label}` }));

const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}

test("domain null: image bar hidden even with image groups and an image flow flag", () => {
  assert.equal(IL.isImageFlow({ flow: "image" }, imageGroups), false);
  assert.equal(IL.isImageFlow({}, imageGroups), false);
});

test("domain null: video bar hidden even with all five video groups and a video flow flag", () => {
  assert.equal(VL.isVideoFlow({ flow: "video" }, videoGroups), false);
  assert.equal(VL.isVideoFlow({}, videoGroups), false);
});

test("domain jenniejoy_cartoon_3d: image and video bars both hidden, even with explicit flow flags", () => {
  assert.equal(IL.isImageFlow({ domain: JJ, flow: "image" }, imageGroups), false);
  assert.equal(VL.isVideoFlow({ domain: JJ, flow: "video" }, videoGroups), false);
  assert.equal(VL.isVideoFlow({ domain: JJ, newtecons_flow: "video" }, []), false);
});

test("domain null via name/folder with no signal: hidden (mirrors a drag-dropped graph)", () => {
  assert.equal(IL.isImageFlow({}, imageGroups, { name: "S01_A_hybrid-v001" }), false);
  assert.equal(VL.isVideoFlow({}, videoGroups, { name: "S06_B3_motion-v006", path: "03_MOTION_H3/S06_B3.json" }), false);
});

test("domain newtecons_live_action: image and video bars show", () => {
  assert.equal(IL.isImageFlow({ domain: NTC, flow: "image" }, imageGroups), true);
  assert.equal(VL.isVideoFlow({ domain: NTC, flow: "video" }, []), true);
  assert.equal(VL.isVideoFlow({}, videoGroups, { path: "ProjectStudio5 - Film Newtecons/02 Workflow Video/x.json" }), true);
});

for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.filter((r) => r[0] === "ok").length}/${results.length} passed`);
process.exit(failed ? 1 : 0);
