// Run from the proposed custom node: node tests/test_workflow_context.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { workflowDomain, workflowMediaKind, activeWorkflowContext, NEWTECONS_DOMAIN as NTC, JENNIEJOY_DOMAIN as JJ } from "../web/workflow_context.js";
import { isImageFlow, IMAGE_LABELS } from "../web/image_ui_logic.js";
import { isVideoFlow } from "../web/video_ui_logic.js";
import { workflowKind } from "../web/step_ui_logic.js";

const results = [];
function test(name, fn) {
  try { fn(); results.push([true, name]); }
  catch (error) { results.push([false, name, error.stack]); }
}
const groups = IMAGE_LABELS.slice(0, 4).map((label, i) => ({ title: `${String(i).padStart(2, "0")} ${label}`, bounding: [i * 10, 0, 10, 10] }));
const load = (name) => JSON.parse(readFileSync(fileURLToPath(new URL(`../../../user/default/workflows/${name}`, import.meta.url)), "utf8").replace(/^\uFEFF/u, ""));

test("direct extra.domain identifies JennieJoy", () => assert.equal(workflowDomain({ domain: JJ }), JJ));
test("nested extra.*.domain identifies NEWTECONS", () => assert.equal(workflowDomain({ film: { metadata: { domain: NTC } } }), NTC));
test("domain_id fields are accepted", () => assert.equal(workflowDomain({ workflow: { domain_id: JJ } }), JJ));
test("direct domain takes precedence over nested domain", () => assert.equal(workflowDomain({ domain: JJ, image_ui: { domain: NTC } }), JJ));
test("extra domain beats conflicting name prefix and folder", () => assert.equal(workflowDomain({ domain: JJ, title: "NEWTECONS Image" }, { path: "NEWTECONS_IMAGE_8STEP/example.json" }), JJ));
test("nested extra domain beats conflicting name prefix", () => assert.equal(workflowDomain({ workflow: { domain: JJ } }, { name: "NEWTECONS Image" }), JJ));
test("NEWTECONS name prefix identifies the domain", () => assert.equal(workflowDomain({}, { name: "NEWTECONS Video H3" }), NTC));
test("path basename prefix is a name signal before folder", () => assert.equal(workflowDomain({}, { path: "JENNIEJOYKIDS_04/NEWTECONS Video.json" }), NTC));
test("JennieJoyKids name prefix identifies the domain", () => assert.equal(workflowDomain({}, { name: "JENNIEJOYKIDS_S01" }), JJ));
test("extra title prefix identifies domain before folder", () => assert.equal(workflowDomain({ title: "NEWTECONS Video" }, { folder: "JENNIEJOYKIDS_04" }), NTC));
test("context name prefix takes precedence over conflicting folder", () => assert.equal(workflowDomain({}, { name: "JENNIEJOYKIDS_S01", folder: "NEWTECONS_H3" }), JJ));
test("JennieJoy workflow folder supplies identity when basename is neutral", () => assert.equal(workflowDomain({}, { name: "S01_A_hybrid", path: "JENNIEJOYKIDS_04_MILK_AND_MOM/03_MOTION_H3/S01_A_hybrid.workflow.json" }), JJ));
test("Windows NEWTECONS workflow folder supplies identity", () => assert.equal(workflowDomain({}, { path: "ProjectStudio5 - Film Newtecons\\02 Workflow Video\\neutral.json" }), NTC));
test("explicit folder is accepted", () => assert.equal(workflowDomain({}, { folder: "JENNIEJOYKIDS_04/03_MOTION_H3" }), JJ));
test("unknown explicit domain does not inherit a NEWTECONS name", () => assert.equal(workflowDomain({ domain: "other_film" }, { name: "NEWTECONS Image" }), "other_film"));
test("no identity evidence yields null", () => assert.equal(workflowDomain({}, { name: "neutral" }), null));
test("metadata object cycles are bounded", () => { const extra = {}; extra.self = extra; assert.equal(workflowDomain(extra), null); });
test("explicit JennieJoy blocks image bar despite image groups and stale flow", () => assert.equal(isImageFlow({ domain: JJ, newtecons_flow: "image" }, groups), false));
test("JennieJoy name prefix blocks image bar", () => assert.equal(isImageFlow({ flow: "image" }, groups, { name: "JENNIEJOYKIDS_S01" }), false));
test("JennieJoy folder blocks video bar despite stale flow", () => assert.equal(isVideoFlow({ flow: "video" }, [], { path: "JENNIEJOYKIDS_04/S06_B3.json" }), false));
test("NEWTECONS image metadata still activates image UI", () => assert.equal(isImageFlow({ domain: NTC, flow: "image" }, groups), true));
test("flow metadata precedes a misleading filename media marker", () => assert.equal(workflowMediaKind({ flow: "image", title: "NEWTECONS Video" }, []), "image"));
test("video folder identifies otherwise neutral graph", () => assert.equal(workflowMediaKind({}, [], { path: "NEWTECONS_H3/02 Workflow Video/neutral.json" }), "video"));
test("Vietnamese Đ group titles remain a video classification signal", () => assert.equal(workflowMediaKind({}, ["01 ĐỌC SHOTLIST", "02 VIẾT PROMPT", "03 AI QUAY VIDEO", "04 LÊN 1080P", "05 LƯU & QUAY TIẾP"].map((title) => ({ title }))), "video"));
test("actual LongTake GUI title activates video and excludes image without flow or groups", () => {
  const graph = load("ProjectStudio5 - Film Newtecons/02 Workflow Video/NEWTECONS Video H3 LongTake v001 - 20s.json");
  assert.equal(graph.nodes.length, 48);
  assert.deepEqual(graph.groups, []);
  assert.equal(graph.extra.flow, undefined);
  assert.equal(graph.extra.newtecons_flow, undefined);
  assert.equal(workflowDomain(graph.extra), NTC);
  assert.equal(workflowMediaKind(graph.extra, graph.groups), "video");
  assert.equal(isVideoFlow(graph.extra, graph.groups), true);
  assert.equal(isImageFlow(graph.extra, graph.groups), false);
});
test("actual JennieJoy S01 folder suppresses all three NEWTECONS bars", () => {
  const path = "JENNIEJOYKIDS_04_MILK_AND_MOM/03_MOTION_H3/S01_A_hybrid-v001.workflow.json";
  const graph = load(path);
  assert.equal(graph.nodes.length, 24);
  assert.equal(workflowDomain(graph.extra, { path }), JJ);
  assert.equal(isImageFlow(graph.extra, graph.groups, { path }), false);
  assert.equal(isVideoFlow(graph.extra, graph.groups, { path }), false);
  assert.equal(workflowKind(graph.extra, graph.groups, { path }), null);
});
test("actual JennieJoy S06 folder suppresses all three NEWTECONS bars", () => {
  const path = "JENNIEJOYKIDS_04_MILK_AND_MOM/03_MOTION_H3/S06_B3_motion-v006.workflow.json";
  const graph = load(path);
  assert.equal(graph.nodes.length, 28);
  assert.equal(workflowDomain(graph.extra, { path }), JJ);
  assert.equal(isImageFlow(graph.extra, graph.groups, { path }), false);
  assert.equal(isVideoFlow(graph.extra, graph.groups, { path }), false);
  assert.equal(workflowKind(graph.extra, graph.groups, { path }), null);
});
test("active context reads ComfyUI extension workflow manager", () => assert.deepEqual(activeWorkflowContext({ extensionManager: { workflow: { activeWorkflow: { filename: "S01.json", path: "JENNIEJOYKIDS_04/S01.json", directory: "JENNIEJOYKIDS_04" } } } }), { name: "S01.json", path: "JENNIEJOYKIDS_04/S01.json", folder: "JENNIEJOYKIDS_04" }));
test("active context uses supported directory field for neutral filenames", () => assert.equal(workflowDomain({}, activeWorkflowContext({ extensionManager: { workflow: { activeWorkflow: { filename: "neutral.json", directory: "NEWTECONS_H3" } } } })), NTC));
test("active context tolerates unnamed imported graph", () => assert.equal(activeWorkflowContext({ graph: { extra: { title: "NEWTECONS Video" } } }).name, "NEWTECONS Video"));

for (const [ok, name, error] of results) console.log(`${ok ? "ok" : "FAIL"} ${name}${error ? `\n${error}` : ""}`);
const passed = results.filter(([ok]) => ok).length;
const failed = results.length - passed;
console.log(`${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
