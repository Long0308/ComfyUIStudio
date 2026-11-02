import test from "node:test";
import assert from "node:assert/strict";
import { assertLocalGraph, bindSnapshot, historyState, pendingCount, runSequential } from "../web/auto_run.js";

const selected = { shot: "S02_A", scene: "S02", render_key: "a".repeat(64) };
const graph = { output: {
  "100": { class_type: "NewteconsProjectPanel", inputs: { run_mode: "Auto: missing shots", scene: "ALL" } },
  "6": { class_type: "NewteconsPanelH3", inputs: {} },
  "18": { class_type: "NewteconsPanelSaveVideo", inputs: { receipt_json: ["100", 7] } },
}, workflow: { extra: { fixture: true } } };
function done(id, shot = selected) {
  return { [id]: { status: { completed: true, status_str: "success", messages: [] },
    outputs: { "18": { newtecons_panel: [{ ...shot, panel_id: "100" }] } } } };
}
function harness() {
  const owner = { panelId: "100", cancelled: false };
  const shots = [selected, { shot: "S03_A", scene: "S03", render_key: "b".repeat(64) }];
  const rendered = new Set(), submitted = [], notes = [];
  let active, waits = 0;
  const io = {
    current: async () => true,
    report: async () => {
      const pending = shots.filter((s) => !rendered.has(s.shot));
      return { ...pending[0], pending: !!pending.length, total: shots.length,
        missing: pending.length, completed: rendered.size,
        shots: shots.map((s) => ({ ...s, rendered: rendered.has(s.shot) })) };
    },
    progress: (info, note) => notes.push([info.completed, note]),
    queue: async () => ({ queue_running: active ? [[0, active.id]] : [], queue_pending: [] }),
    snapshot: async (s) => { active = { selected: s }; return bindSnapshot(graph, "100", s); },
    submit: async (snapshot) => {
      const id = `prompt-${submitted.length}`;
      submitted.push(snapshot);
      active.id = id;
      return { prompt_id: id };
    },
    history: async (id) => { rendered.add(active.selected.shot); return done(id, active.selected); },
    cancelPending: async () => false,
    wait: async () => { waits++; },
  };
  return { io, owner, rendered, submitted, notes, get waits() { return waits; } };
}

test("snapshot explicitly binds selected shot and key without changing live graph", () => {
  const { frozen, saverId } = bindSnapshot(graph, 100, selected);
  assert.equal(saverId, "18");
  assert.equal(frozen.output[100].inputs.auto_shot, "S02_A");
  assert.equal(frozen.output[100].inputs.auto_render_key, selected.render_key);
  assert.equal(graph.output[100].inputs.auto_shot, undefined);
  frozen.workflow.extra.fixture = false;
  assert.equal(graph.workflow.extra.fixture, true);
});
test("wrong saver receipt binding fails before queue", () => {
  const wrong = structuredClone(graph);
  wrong.output[18].inputs.receipt_json = ["100", 0];
  assert.throws(() => bindSnapshot(wrong, 100, selected), /receipt/);
});
test("history succeeds after missed browser events and ignores unrelated prompt", () => {
  assert.equal(historyState(done("p"), "p", "18", "100", selected), "complete");
  assert.equal(historyState(done("other"), "p", "18", "100", selected), "waiting");
});
test("history rejects successful execution without correct saved shot/key", () => {
  assert.throws(() => historyState(done("p", { ...selected, render_key: "wrong" }), "p", "18", "100", selected), /Save/);
});
test("history detects own execution failure", () => {
  assert.throws(() => historyState({ p: { status: { status_str: "error" } } }, "p", "18", "100", selected), /failed/);
});
test("known already-rendered race permits CPU receipt recheck", () => {
  const history = { p: { status: { status_str: "error", messages: [["execution_error",
    { exception_message: "AUTO_ALREADY_RENDERED: bound shot has a hash-verified render" }]] } } };
  assert.equal(historyState(history, "p", "18", "100", selected), "already-rendered");
});
test("queue limit counts pending prompts, independent of running jobs", () => {
  assert.equal(pendingCount({ queue_running: [[1, "other"]], queue_pending: Array(3).fill([]) }), 3);
  assert.throws(() => pendingCount({}), /incomplete/);
});
test("one click processes missing shots sequentially through history and verified receipts", async () => {
  const h = harness();
  const result = await runSequential(h.io, h.owner);
  assert.equal(result.complete, true);
  assert.deepEqual(h.submitted.map((s) => s.output[100].inputs.auto_shot), ["S02_A", "S03_A"]);
  assert.equal(result.progress.completed, 2);
});
test("valid prior render is skipped", async () => {
  const h = harness(); h.rendered.add("S02_A");
  await runSequential(h.io, h.owner);
  assert.equal(h.submitted.length, 1);
  assert.equal(h.submitted[0].output[100].inputs.auto_shot, "S03_A");
});
test("waits at four pending but submits with other jobs at three pending", async () => {
  const h = harness(); let reads = 0;
  h.io.queue = async () => ({ queue_running: [[0, "other"]], queue_pending: Array(reads++ === 0 ? 4 : 3).fill([1, "other-pending"]) });
  await runSequential(h.io, h.owner);
  assert.equal(h.waits, 1);
  assert.equal(h.submitted.length, 2);
});
test("Stop during wait submits nothing", async () => {
  const h = harness();
  h.io.queue = async () => ({ queue_running: [], queue_pending: Array(4).fill([]) });
  h.io.wait = async () => { h.owner.cancelled = true; };
  const result = await runSequential(h.io, h.owner);
  assert.equal(result.complete, false); assert.equal(h.submitted.length, 0);
});
test("final queue read has no async serialization before submit", async () => {
  const h = harness(); let serializations = 0, lastQueueRead = 0;
  h.io.current = async () => { serializations++; return true; };
  const queue = h.io.queue, submit = h.io.submit;
  h.io.queue = async () => { lastQueueRead = serializations; return queue(); };
  h.io.submit = async (snapshot) => { assert.equal(serializations, lastQueueRead); return submit(snapshot); };
  await runSequential(h.io, h.owner); assert.equal(h.submitted.length, 2);
});
test("synchronous graph switch during queue request blocks submit", async () => {
  const h = harness(); h.io.currentSync = () => false;
  const result = await runSequential(h.io, h.owner);
  assert.equal(result.complete, false); assert.equal(h.submitted.length, 0);
});
test("Stop while submission is in flight cancels only its returned prompt ID", async () => {
  const h = harness(); const submit = h.io.submit; const cancelled = [];
  h.io.submit = async (snapshot) => { const answer = await submit(snapshot); h.owner.cancelled = true; return answer; };
  h.io.cancelPending = async (id) => { cancelled.push(id); return true; };
  await runSequential(h.io, h.owner);
  assert.deepEqual(cancelled, ["prompt-0"]); assert.equal(h.submitted.length, 1);
});
test("Stop leaves running shot to save and cancels remaining shots", async () => {
  const h = harness(); const submit = h.io.submit;
  h.io.submit = async (s) => { const result = await submit(s); h.owner.cancelled = true; return result; };
  const result = await runSequential(h.io, h.owner);
  assert.equal(result.complete, false); assert.equal(h.submitted.length, 1);
  assert.deepEqual([...h.rendered], ["S02_A"]);
});
test("pending-to-running deletion race retains ownership until running shot finishes", async () => {
  const h = harness(); const submit = h.io.submit; const history = h.io.history;
  let polls = 0, deletions = 0;
  h.io.submit = async (s) => { const result = await submit(s); h.owner.cancelled = true; return result; };
  h.io.cancelPending = async () => { deletions++; return true; }; // DELETE was attempted, but job started.
  h.io.history = async (id) => ++polls < 3 ? {} : history(id);
  const result = await runSequential(h.io, h.owner);
  assert.equal(result.complete, false); assert.equal(h.submitted.length, 1);
  assert.equal(polls, 3); assert.equal(deletions, 3); assert.equal(h.waits, 2);
  assert.deepEqual([...h.rendered], ["S02_A"]);
});
test("confirmed queued deletion keeps a history grace before releasing ownership", async () => {
  const h = harness(); const submit = h.io.submit;
  h.io.submit = async (s) => { const result = await submit(s); h.owner.cancelled = true; return result; };
  h.io.cancelPending = async () => true;
  h.io.history = async () => ({});
  h.io.queue = async () => ({ queue_running: [], queue_pending: [] });
  const result = await runSequential(h.io, h.owner);
  assert.equal(result.complete, false); assert.equal(h.waits, 3);
  assert.equal(h.submitted.length, 1); assert.equal(h.owner.promptId, null);
});
test("graph edit stops further submissions but reconciles running shot", async () => {
  const h = harness(); h.io.current = async () => h.submitted.length === 0;
  await runSequential(h.io, h.owner);
  assert.equal(h.submitted.length, 1); assert.equal(h.owner.cancelled, true);
});
test("history success with corrupt output stops instead of advancing", async () => {
  const h = harness(); h.io.history = async (id) => done(id);
  await assert.rejects(runSequential(h.io, h.owner), /hash/);
  assert.equal(h.submitted.length, 1);
});
test("lost queue/history prompt fails closed", async () => {
  const h = harness(); h.io.history = async () => ({});
  h.io.queue = async () => ({ queue_running: [], queue_pending: [] });
  await assert.rejects(runSequential(h.io, h.owner), /queue\/history/);
  assert.equal(h.submitted.length, 1);
});
test("local guard rejects partner nodes, unknown nodes and remote host", () => {
  const definitions = Object.fromEntries(Object.values(graph.output).map((n) => [n.class_type, { python_module: "custom_nodes.local" }]));
  assertLocalGraph(graph.output, definitions, "127.0.0.1");
  assert.throws(() => assertLocalGraph(graph.output, definitions, "example.com"), /localhost/);
  definitions.NewteconsPanelH3.api_node = true;
  assert.throws(() => assertLocalGraph(graph.output, definitions, "localhost"), /local/);
  definitions.NewteconsPanelH3 = { python_module: "comfy_api_nodes.remote" };
  assert.throws(() => assertLocalGraph(graph.output, definitions, "localhost"), /local/);
  delete definitions.NewteconsPanelH3;
  assert.throws(() => assertLocalGraph(graph.output, definitions, "localhost"), /local/);
});
