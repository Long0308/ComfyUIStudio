import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { CELL_IDS, selectPoseCell, poseSnapshot, poseSource, queueHasRoom, assertLocalEndpoint, assertLocalGraph,
  promptResult, runPoseBatch } from "../web/auto_run_logic.js";

let workspace = dirname(fileURLToPath(import.meta.url));
while (!existsSync(join(workspace, "docs/media-stage/STAGE-IMAGE-WF-V006-R3/pose_cells.json"))) {
  const parent = dirname(workspace);
  if (parent === workspace) throw new Error("Pose workflow fixtures not found in this workspace");
  workspace = parent;
}
const load = (name) => JSON.parse(readFileSync(join(workspace, "docs/media-stage/STAGE-IMAGE-WF-V006-R3", name), "utf8").replace(/^\uFEFF/, ""));
const graph = load("NEWTECONS Image v006r3 - hybrid pose.api.json");
const cells = load("pose_cells.json").cells;
const shippedCells = JSON.parse(readFileSync(new URL("../web/pose_cells.json", import.meta.url), "utf8")).cells;
test("source follows current loader default / alternate / hash-bound flat filename", () => {
  for (const cell of shippedCells) for (const variant of [cell, ...(cell.alternates || [])]) {
    for (const image of [variant.file_path, variant.flat_input_filename]) {
      const output = structuredClone(graph); output[cell.load_image_node_id].inputs.image = image;
      assert.equal(poseSource(output, cell), variant.source);
      const job = poseSnapshot({ output }, cell.cell_id, poseSource(output, cell));
      assert.equal(job.output[281].inputs.switch, variant.source === "library");
      assert.equal(job.output[cell.load_image_node_id].inputs.image, image);
    }
  }
});
test("unknown input requires exact filename/source binding; conflicts fail closed", () => {
  const cell = shippedCells[0], output = structuredClone(graph);
  assert.throws(() => poseSource(output, cell, { image: output[185].inputs.image, source: "blender" }));
  output[185].inputs.image = "custom.png";
  assert.throws(() => poseSource(output, cell));
  assert.throws(() => poseSource(output, cell, "blender"));
  assert.throws(() => poseSource(output, cell, { image: "stale.png", source: "blender" }));
  assert.equal(poseSource(output, cell, { image: "custom.png", source: "blender" }), "blender");
});
test("PNG workflow mirrors the queued selection without changing the live snapshot", () => {
  const original = { output: graph, workflow: { nodes: [{ id: 174, widgets_values: [false] },
    { id: 281, widgets_values: [false] }, { id: 193, widgets_values: ["existing.png"] }] } };
  const changed = poseSnapshot(original, CELL_IDS[0], "library");
  assert.equal(changed.workflow.nodes[0].widgets_values[0], true);
  assert.equal(changed.workflow.nodes[1].widgets_values[0], true);
  assert.equal(changed.workflow.nodes[2].widgets_values[0], "existing.png");
  assert.equal(original.workflow.nodes[0].widgets_values[0], false);
});
for (const [i, cell] of cells.entries()) test(`select ${cell.cell_id}: only cell booleans/source change`, () => {
  const before = JSON.stringify(graph), output = selectPoseCell(graph, cell.cell_id, cell.source);
  assert.equal(JSON.stringify(graph), before);
  for (let slot = 0; slot < 8; slot++) assert.equal(output[174 + slot].inputs.value, slot === i);
  assert.equal(output[281].inputs.switch, cell.source === "library");
  for (const key of Object.keys(graph)) if (!["174", "175", "176", "177", "178", "179", "180", "181", "281"].includes(key)) {
    assert.deepEqual(output[key], graph[key]);
  }
});
test("reject unknown cell / absent or linked selector / wrong source / depth-library mismatch", () => {
  assert.throws(() => selectPoseCell(graph, "BAD", "library"));
  const bad = structuredClone(graph); delete bad[174];
  assert.throws(() => selectPoseCell(bad, CELL_IDS[0], "library"));
  bad[174] = { class_type: "PrimitiveBoolean", inputs: { value: ["42", 0] } };
  assert.throws(() => selectPoseCell(bad, CELL_IDS[0], "library"));
  assert.throws(() => selectPoseCell(graph, CELL_IDS[0], "unknown"));
  const depth = structuredClone(graph); depth[172].inputs.value = true;
  assert.throws(() => selectPoseCell(depth, CELL_IDS[0], "library"));
});
test("r2 without hybrid switch and Blender override preserve other settings", () => {
  const r2 = structuredClone(graph); delete r2[281];
  assert.equal(selectPoseCell(r2, CELL_IDS[8])[181].inputs.value, false);
  assert.equal(selectPoseCell(graph, CELL_IDS[0], "blender")[281].inputs.switch, false);
});
test("queue capacity 0..3 permitted, 4+ waits, malformed fails closed", () => {
  for (let n = 0; n < 6; n++) assert.equal(queueHasRoom({ queue_pending: Array(n), queue_running: [[1]] }), n < 4);
  assert.throws(() => queueHasRoom({}));
});
test("only loopback ComfyUI and no partner/cloud node", () => {
  for (const host of ["localhost", "127.0.0.1", "[::1]"]) assert.doesNotThrow(() => assertLocalEndpoint("/prompt", `http://${host}:8188`));
  assert.throws(() => assertLocalEndpoint("https://cloud.example/prompt", "http://localhost:8188"));
  assert.throws(() => assertLocalGraph({ 1: { class_type: "Partner" } }, { Partner: { python_module: "comfy_api_nodes.nodes_partner" } }));
  assert.throws(() => assertLocalGraph({ 1: { class_type: "CodexOAuthImageLane" } }, { CodexOAuthImageLane: {} }));
  assert.throws(() => assertLocalGraph({ 1: { class_type: "Missing" } }, {}));
});
const image = { filename: "result.png", subfolder: "", type: "output" };
const done = (id) => ({ [id]: { status: { completed: true, status_str: "success" }, outputs: { 65: { images: [image] } } } });
test("history only accepts own successful prompt and step07 output", () => {
  assert.equal(promptResult(done("other"), "self", ["65"]), null);
  assert.deepEqual(promptResult(done("self"), "self", ["65"]), [image]);
  assert.throws(() => promptResult(done("self"), "self", ["27"]));
  assert.throws(() => promptResult({ self: { status: { status_str: "error" } } }, "self", ["65"]));
});
function harness(extra = {}) {
  const run = { cancelled: false }, calls = [], jobs = CELL_IDS.map((label) => ({ label, outputIds: ["65"] }));
  let clock = 0, submitted = 0;
  return { run, calls, jobs, args: {
    run, jobs, now: () => clock, sleep: async (ms) => { clock += ms; }, validate: async () => {},
    request: async (path) => path.startsWith("/history/") ? done(path.split("/").at(-1)) : { queue_pending: [], queue_running: [] },
    submit: async (job) => { calls.push(job.label); return { prompt_id: `id${++submitted}` }; }, ...extra,
  } };
}
test("sequential nine, waits for history completion and reports every thumbnail", async () => {
  const h = harness(); await runPoseBatch(h.args);
  assert.deepEqual(h.calls, CELL_IDS); assert.ok(h.jobs.every((j) => j.state === "done" && j.images[0] === image));
});
test("full queue waits; other running job does not prevent pending<4", async () => {
  let queues = 0;
  const h = harness({ request: async (path) => path.startsWith("/history/") ? done(path.split("/").at(-1)) :
    { queue_pending: ++queues < 3 ? Array(4).fill([0, "foreign"]) : [], queue_running: [[0, "foreign"]] } });
  await runPoseBatch(h.args); assert.equal(h.calls.length, 9); assert.ok(queues >= 11);
});
test("Stop during capacity wait sends nothing", async () => {
  const h = harness(); h.args.request = async () => { h.run.cancelled = true; return { queue_pending: Array(4), queue_running: [] }; };
  await runPoseBatch(h.args); assert.equal(h.calls.length, 0);
});
test("Stop during serialization/validation sends nothing", async () => {
  const h = harness(); h.args.validate = async () => { h.run.cancelled = true; };
  await runPoseBatch(h.args); assert.equal(h.calls.length, 0);
});
test("capacity is read after serialization, with no async validation before POST", async () => {
  let validated = 0, readAfter = 0;
  const h = harness({ validate: async () => { validated++; } });
  h.args.request = async (path) => {
    if (path.startsWith("/history/")) return done(path.split("/").at(-1));
    readAfter = validated; return { queue_pending: [], queue_running: [] };
  };
  h.args.submit = async (job) => { assert.equal(validated, readAfter); h.calls.push(job.label); return { prompt_id: job.label }; };
  await runPoseBatch(h.args); assert.equal(h.calls.length, 9);
});
test("synchronous graph change during queue request prevents POST", async () => {
  const h = harness({ isCurrent: () => false });
  await assert.rejects(runPoseBatch(h.args), /Graph/); assert.equal(h.calls.length, 0);
});
test("Stop after first completed job cancels eight remaining", async () => {
  const h = harness(); h.args.onChange = () => { if (h.jobs[0].state === "done") h.run.cancelled = true; };
  await runPoseBatch(h.args); assert.equal(h.calls.length, 1); assert.equal(h.jobs[8].state, "cancelled");
});
test("Stop while POST is in flight deletes only own pending prompt", async () => {
  const h = harness(); let posted = false, deleted = false;
  h.args.submit = async () => { posted = true; h.run.cancelled = true; return { prompt_id: "own" }; };
  h.args.request = async (path, opts) => {
    if (opts) { assert.equal(path, "/queue"); assert.deepEqual(JSON.parse(opts.body), { delete: ["own"] }); deleted = true; return {}; }
    if (path.startsWith("/history/")) return {};
    return { queue_pending: posted && !deleted ? [[0, "own"], [1, "foreign"]] : [], queue_running: [] };
  };
  await runPoseBatch(h.args); assert.ok(deleted); assert.equal(h.jobs[0].state, "cancelled");
});
test("Stop never interrupts running job and still collects output", async () => {
  const h = harness(); let history = 0;
  h.args.submit = async () => { h.run.cancelled = true; return { prompt_id: "own" }; };
  h.args.request = async (path, opts) => {
    assert.equal(opts, undefined);
    if (path.startsWith("/history/")) return ++history === 1 ? {} : done("own");
    return { queue_pending: [], queue_running: [[0, "own"]] };
  };
  await runPoseBatch(h.args); assert.equal(h.jobs[0].state, "done"); assert.equal(h.jobs[1].state, "cancelled");
});
test("changed graph and ambiguous POST errors stop without retries", async () => {
  const h = harness({ validate: async () => { throw new Error("changed graph"); } });
  await assert.rejects(runPoseBatch(h.args), /changed graph/); assert.equal(h.calls.length, 0);
  let n = 0; const second = harness({ submit: async () => { n++; throw new Error("network"); } });
  await assert.rejects(runPoseBatch(second.args), /network/); assert.equal(n, 1);
});
const REAL_FLAT = "newtecons_live_action__P1_FRONT__2cce14f8ec85__full_single_P017_front.png";
test("flat staged name <domain>__<cell>__<sha12>__<base> derives source from pose_cells (real UAT name)", () => {
  const cell = shippedCells.find((c) => c.cell_id === "P1_FRONT"), output = structuredClone(graph);
  output[185].inputs.image = REAL_FLAT;
  assert.equal(poseSource(output, cell), "library");
  // wrong cell, wrong hash, other domain stay fail-closed
  const other = shippedCells.find((c) => c.cell_id === "P2_FRONT");
  output[other.load_image_node_id].inputs.image = REAL_FLAT; // P1 name sitting in P2's loader
  assert.throws(() => poseSource(output, other));
  output[185].inputs.image = REAL_FLAT.replace("2cce14f8ec85", "000000000000");
  assert.throws(() => poseSource(output, cell));
  output[185].inputs.image = REAL_FLAT.replace("newtecons_live_action", "jenniejoy_cartoon_3d");
  assert.throws(() => poseSource(output, cell));
  // conflicting binding still rejected
  output[185].inputs.image = REAL_FLAT;
  assert.throws(() => poseSource(output, cell, { image: REAL_FLAT, source: "blender" }));
});
