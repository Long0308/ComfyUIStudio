import { test } from "node:test";
import assert from "node:assert/strict";
import { workflowKey } from "../web/workflow_context.js";
test("workflowKey separates workflow tabs sharing one graph object", () => {
  assert.notEqual(workflowKey({ path: "a/x.json" }), workflowKey({ path: "a/y.json" }));
  assert.equal(workflowKey({ name: "n.json" }), "n.json");
  assert.equal(workflowKey(null), "(untitled)");
});
