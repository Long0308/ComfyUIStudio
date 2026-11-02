import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as S from "../web/step_ui_logic.js";
import * as I from "../web/image_ui_logic.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../../../user/default/workflows");
const file = path.join(root, "ProjectStudio5 - Film Newtecons/01 Workflow Image/NEWTECONS Image v005 - neo trang phuc.json");
const raw = JSON.parse(readFileSync(file, "utf8").replace(/^\uFEFF/u, ""));
const graph = {
  extra: raw.extra, groups: raw.groups,
  nodes: raw.nodes.map((n) => ({ ...n, widgets: n.type === "ComfySwitchNode" ? { switch: n.widgets_values[0] } : { image: n.widgets_values?.[0] }, inputs: n.inputs || [] })),
  links: raw.links.map((l) => ({ id: l[0], origin_id: l[1], target_id: l[3] })),
};
const steps = S.parseSteps(graph.groups);
const step02 = steps.find((s) => s.code === "02");
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log("ok " + name); }
  catch (err) { failed++; console.log("FAIL " + name + ": " + err.message); }
}

test("saved v005 measures 23 LoadImage and 14 populated; node13 is blank", () => {
  const loads = graph.nodes.filter((n) => n.type === "LoadImage");
  assert.equal(loads.length, 23);
  assert.equal(loads.filter((n) => n.widgets.image).length, 14);
  assert.equal(loads.find((n) => n.id === 13).widgets.image, "");
});
test("step02 preserves blank node13 and shows seven wardrobe plus five character references", () => {
  const images = I.stepInputs(graph, step02).images;
  assert.equal(images.find((i) => i.nodeId === 13).ref, null);
  assert.equal(images.find((i) => i.nodeId === 13).upstream, false);
  const refs = images.filter((i) => i.upstream && i.ref);
  assert.deepEqual(refs.map((i) => i.nodeId).sort((a, b) => a - b), [123, 124, 125, 126, 127, 128, 129, 148, 149, 150, 155, 156]);
  assert.ok(refs.every((i) => ["02A", "02B"].includes(i.step) && i.mode === 0));
  assert.ok(!images.some((i) => [84, 85].includes(i.nodeId)));
});

const synthetic = (choice = false) => ({
  nodes: [
    { id: 1, type: "LoadImage", pos: [0, 0], widgets: { image: "chosen.png" } },
    { id: 2, type: "LoadImage", pos: [0, 0], widgets: { image: "other.png" } },
    { id: 3, type: "ComfySwitchNode", pos: [0, 0], widgets: { switch: choice }, inputs: [{ name: "on_false", link: 10 }, { name: "on_true", link: 11 }] },
    { id: 4, type: "PreviewImage", pos: [100, 0], widgets: {} },
    { id: 5, type: "LoadImage", pos: [100, 1], widgets: { image: "" } },
    { id: 6, type: "LoadImage", pos: [0, 0], widgets: { image: "unconnected.png" } },
  ], links: [{ id: 10, origin_id: 1, target_id: 3 }, { id: 11, origin_id: 2, target_id: 3 }, { id: 12, origin_id: 3, target_id: 4 }],
});
const syntheticStep = { code: "02", bounding: [90, -10, 50, 50] };
test("blank own slot never hides selected upstream image; unused branch excluded", () => {
  const ins = S.inputsForStep(synthetic(), syntheticStep, []);
  assert.deepEqual(ins.map((i) => i.nodeId), [5, 1]);
  assert.equal(ins[0].ref, null);
  assert.equal(ins[1].ref.filename, "chosen.png");
});
test("switch selection controls effective upstream reference", () => {
  assert.deepEqual(S.inputsForStep(synthetic(true), syntheticStep, []).map((i) => i.nodeId), [5, 2]);
});
test("muted upstream nodes cannot supply effective image", () => {
  const g = synthetic(); g.nodes.find((n) => n.id === 1).mode = 2;
  assert.deepEqual(S.inputsForStep(g, syntheticStep, []).map((i) => i.nodeId), [5]);
});
test("bypassed upstream image loader is not an effective image source", () => {
  const g = synthetic(); g.nodes.find((n) => n.id === 1).mode = 4;
  assert.deepEqual(S.inputsForStep(g, syntheticStep, []).map((i) => i.nodeId), [5]);
});
test("upstream search terminates on cycles and deduplicates repeated edges", () => {
  const g = synthetic(); g.links.push({ id: 13, origin_id: 4, target_id: 3 }, { id: 14, origin_id: 1, target_id: 4 });
  assert.deepEqual(S.inputsForStep(g, syntheticStep, []).map((i) => i.nodeId), [5, 1]);
});
console.log(`${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
