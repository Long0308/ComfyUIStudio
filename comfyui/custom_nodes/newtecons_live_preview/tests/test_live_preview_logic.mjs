import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  GRAPH_FINGERPRINT_VERSION,
  WORKFLOW_KEY_PATTERN,
  applyExecutionOutput,
  applyHistoryOutputs,
  bindApiJournalToGraph,
  canonicalJson,
  chooseNewestJournal,
  createNativeUiJournal,
  derivePreviewSaveMappingFromGraph,
  graphCoreFingerprint,
  migrateNativeJournal,
  refreshDisplayOutputs,
  sha256Hex,
  shouldReplaceLocalLedger,
} from "../web/live_preview_logic.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const workflowDir = path.resolve(
  here,
  "../../../user/default/workflows/NEWTECONS_3_MODELS",
);
const workflowNames = [
  "CHAR_08_FLUX1_4K_MASTER_v002.json",
  "CHAR_08_KREA2_4K_MASTER_v002.json",
  "CHAR_08_ZIMAGE_4K_MASTER_v002.json",
];
const expectedMappings = {
  "CHAR_08_FLUX1_4K_MASTER_v002.json": { "9": "8", "32": "31", "54": "53" },
  "CHAR_08_KREA2_4K_MASTER_v002.json": { "10": "9", "32": "31", "54": "53" },
  "CHAR_08_ZIMAGE_4K_MASTER_v002.json": { "10": "9", "32": "31", "54": "53" },
};

const output = (filename, type = "output") => ({
  images: [{ filename, subfolder: "Newtecons_3Models", type }],
});

function journal(promptId, startedAt, values = {}) {
  return {
    workflow_key: "CHAR_08_KREA2_TURBO",
    graph_fingerprint: "b".repeat(64),
    prompt_id: promptId,
    started_at_ms: startedAt,
    updated_at_ms: startedAt,
    status: "completed",
    outputs: {},
    ...values,
  };
}

for (const name of workflowNames) {
  const workflow = JSON.parse(fs.readFileSync(path.join(workflowDir, name), "utf8"));
  const live = workflow.extra.newtecons_live;
  const graphFingerprint = await graphCoreFingerprint(workflow);
  assert.match(live.workflow_key, WORKFLOW_KEY_PATTERN);
  assert.match(graphFingerprint, /^[0-9a-f]{64}$/);
  if (live.recipe_fingerprint) {
    assert.match(live.recipe_fingerprint, /^[0-9a-f]{64}$/);
  } else {
    assert.equal(live.recipe_fingerprint, undefined);
  }
  const mapping = derivePreviewSaveMappingFromGraph(workflow);
  assert.deepEqual(mapping, expectedMappings[name]);
  assert.equal(mapping["70"], undefined, "muted 4K pair must stay excluded");

  // The live frontend adds localized ports and unconnected widget sockets;
  // native queue/export strips them while keeping widgets_values unchanged.
  const hydrated = structuredClone(workflow);
  for (const node of hydrated.nodes) {
    for (const port of [...(node.inputs || []), ...(node.outputs || [])]) {
      port.localized_name = `Vietnamese ${port.name}`;
    }
  }
  const textNode = hydrated.nodes.find(node => node.type === "CLIPTextEncode");
  textNode.inputs.push({
    name: "text", type: "STRING", localized_name: "Prompt",
    widget: { name: "text" }, link: null,
  });
  assert.equal(await graphCoreFingerprint(hydrated), graphFingerprint,
    "live widget sockets and localization must match the exported graph");
  const changedPrompt = structuredClone(hydrated);
  changedPrompt.nodes.find(node => node.id === textNode.id).widgets_values[0] += " changed";
  assert.notEqual(await graphCoreFingerprint(changedPrompt), graphFingerprint,
    "widget values must remain execution-bearing");
  textNode.inputs.at(-1).link = 999;
  assert.notEqual(await graphCoreFingerprint(hydrated), graphFingerprint,
    "connected widget sockets must not be ignored");
}

const recipe = "a".repeat(64);
const apiA = journal("A", 100, {
  recipe_fingerprint: recipe,
  upstream_journal: "timed-api-runner",
  updated_at_ms: 300,
  outputs: { "31": output("A.png") },
});
const nativeB = journal("B", 200, {
  source: "comfyui-native-ui",
  schema: "newtecons-native-ui-journal-v1",
  outputs: { "31": output("B.png"), "32": output("B.png") },
});
assert.equal(
  chooseNewestJournal(
    apiA, nativeB, nativeB.workflow_key, recipe, nativeB.graph_fingerprint,
  ).prompt_id,
  "B",
  "native B must survive an older API A journal",
);
assert.equal(
  chooseNewestJournal(
    apiA, nativeB, nativeB.workflow_key, recipe, nativeB.graph_fingerprint,
  ).prompt_id,
  "B",
  "A finishing later must not replace B selected by start time",
);

const failedB = journal("B", 200, {
  schema: "newtecons-native-ui-journal-v1",
  status: "error",
  outputs: {},
});
assert.equal(
  chooseNewestJournal(
    apiA, failedB, failedB.workflow_key, recipe, failedB.graph_fingerprint,
  ).prompt_id,
  "B",
);

assert.equal(
  shouldReplaceLocalLedger(nativeB, apiA),
  false,
  "delayed terminal write from older A must not replace B in localStorage",
);
assert.equal(shouldReplaceLocalLedger(apiA, nativeB), true);

const legacyApi = journal("API-ONLY", 1, {
  recipe_fingerprint: recipe,
  started_at_ms: undefined,
  outputs: { "31": output("api-only.png") },
});
assert.equal(
  chooseNewestJournal(
    legacyApi, null, legacyApi.workflow_key, recipe, "b".repeat(64),
  ).prompt_id,
  "API-ONLY",
  "legacy API journal remains the fallback when no native ledger exists",
);

const newerApi = journal("API-C", 400, {
  recipe_fingerprint: recipe,
  run_started_at_ms: 400,
  outputs: { "31": output("api-c.png") },
});
assert.equal(
  chooseNewestJournal(
    newerApi, nativeB, nativeB.workflow_key, recipe, nativeB.graph_fingerprint,
  ).prompt_id,
  "API-C",
  "an explicitly newer API run start may supersede the older native ledger",
);

const durableApi = journal("API-DURABLE", 1, {
  recipe_fingerprint: recipe,
  started_at_ms: undefined,
  history_status: {
    messages: [
      ["execution_start", { prompt_id: "API-DURABLE", timestamp: 600 }],
      ["execution_success", { prompt_id: "API-DURABLE", timestamp: 900 }],
    ],
  },
  outputs: { "31": output("durable-api.png") },
});
assert.equal(
  chooseNewestJournal(
    durableApi, nativeB, nativeB.workflow_key, recipe, nativeB.graph_fingerprint,
  ).prompt_id,
  "API-DURABLE",
  "durable API history timestamps must remain effective after ComfyUI restart",
);

const wrongFingerprint = journal("B", 200, {
  schema: "newtecons-native-ui-journal-v1",
  graph_fingerprint: "c".repeat(64),
  outputs: { "31": output("wrong.png") },
});
assert.equal(
  chooseNewestJournal(
    apiA, wrongFingerprint, apiA.workflow_key, recipe, "b".repeat(64),
  ).prompt_id,
  "A",
  "a switched/edited graph must not accept another recipe's ledger",
);

const graph = {
  nodes: [
    { id: "8", type: "VAEDecode", inputs: [], mode: 0 },
    { id: "9", type: "SaveImage", inputs: [{ name: "images", link: 9 }], mode: 0 },
    { id: "10", type: "PreviewImage", inputs: [{ name: "images", link: 10 }], mode: 0 },
  ],
  links: [
    [9, "8", 0, "9", 0, "IMAGE"],
    [10, "8", 0, "10", 0, "IMAGE"],
  ],
};
const cachedJournal = createNativeUiJournal({
  graph,
  workflowKey: "CHAR_08_ZIMAGE_TURBO",
  graphFingerprint: "b".repeat(64),
  promptId: "CACHED-B",
  startedAtMs: 500,
});
assert.equal(
  cachedJournal.graph_fingerprint_version,
  GRAPH_FINGERPRINT_VERSION,
  "new native journals must identify the stable graph projection",
);
applyHistoryOutputs(cachedJournal, { "9": output("cached.png") });
assert.deepEqual(cachedJournal.outputs["10"], output("cached.png"));

const raw = {
  "9": output("preview-first.png"),
  "10": output("preview-first.png", "temp"),
};
const refreshed = refreshDisplayOutputs(raw, { "10": "9" });
assert.deepEqual(refreshed.outputs["10"], raw["9"]);
assert.equal(refreshed.display_provenance.active[0].descriptor_type, "output");

applyExecutionOutput(cachedJournal, "10", output("late-preview.png", "temp"));
assert.deepEqual(cachedJournal.outputs["10"], cachedJournal.raw_outputs["9"]);

const edited = JSON.parse(
  fs.readFileSync(path.join(workflowDir, workflowNames[1]), "utf8"),
);
const originalFingerprint = await graphCoreFingerprint(edited);
const editedNode = edited.nodes.find(node => Array.isArray(node.widgets_values));
assert.ok(editedNode, "workflow must expose a widget for the edit test");
editedNode.widgets_values[0] = `${editedNode.widgets_values[0]}-edited`;
assert.notEqual(await graphCoreFingerprint(edited), originalFingerprint);

const viewportGraph = {
  nodes: [{ id: 1, type: "PreviewImage", inputs: [{ name: "images", link: 1 }] }],
  links: [[1, 2, 0, 1, 0, "IMAGE"]],
  extra: {
    ds: { scale: 0.6, offset: [50, 200] },
    newtecons_live: { workflow_key: "CHAR_08_FLUX1_HD_DRAFT_V003" },
  },
};
const viewportFingerprint = await graphCoreFingerprint(viewportGraph);
viewportGraph.extra.ds.scale = 0.19;
viewportGraph.extra.ds.offset = [-1800, 420];
assert.equal(
  await graphCoreFingerprint(viewportGraph),
  viewportFingerprint,
  "canvas pan/zoom must not invalidate a saved preview journal",
);
viewportGraph.nodes[0].inputs[0].link = null;
assert.notEqual(
  await graphCoreFingerprint(viewportGraph),
  viewportFingerprint,
  "actual workflow input changes must continue to invalidate a preview journal",
);

const serializedGraph = JSON.parse(
  fs.readFileSync(path.join(workflowDir, workflowNames[0]), "utf8"),
);
const stableWorkflowFingerprint = await graphCoreFingerprint(serializedGraph);
const editorMovedGraph = structuredClone(serializedGraph);
editorMovedGraph.id = "frontend-generated-id";
editorMovedGraph.revision = 99;
editorMovedGraph.last_node_id = 999;
editorMovedGraph.last_link_id = 999;
editorMovedGraph.extra.ds = { scale: 0.2, offset: [-4000, 900] };
editorMovedGraph.extra.frontendVersion = "different-runtime";
editorMovedGraph.groups[0].id = 999;
editorMovedGraph.groups[0].font_size = 48;
editorMovedGraph.nodes.reverse();
for (const node of editorMovedGraph.nodes) {
  node.order = (node.order || 0) + 100;
  node.pos = [999, 999];
  node.size = [777, 777];
  node.color = "#112233";
  node.bgcolor = "#445566";
  node.widgets_values_named = { runtime: "ui-only" };
}
assert.equal(
  await graphCoreFingerprint(editorMovedGraph),
  stableWorkflowFingerprint,
  "canvas and frontend-only serialization must survive reload without hiding an old output",
);

const executableMutations = [
  graph => { graph.nodes.find(node => node.id === 4).widgets_values[0] += " changed"; },
  graph => { graph.nodes.find(node => node.id === 1).widgets_values[0] = "other.safetensors"; },
  graph => { graph.nodes.find(node => node.id === 20).widgets_values[0] = "other-reference.png"; },
  graph => { graph.nodes.find(node => node.id === 6).widgets_values[0] += 1; },
  graph => { graph.nodes.find(node => node.id === 54).inputs[0].link = 999; },
  graph => { graph.nodes.find(node => node.id === 69).mode = 0; },
  graph => { graph.nodes.find(node => node.id === 47).properties.custom_behavior = "changed"; },
  graph => { graph.extra.custom_execution_metadata = { guard: "changed" }; },
];
for (const mutate of executableMutations) {
  const changed = structuredClone(serializedGraph);
  mutate(changed);
  assert.notEqual(
    await graphCoreFingerprint(changed),
    stableWorkflowFingerprint,
    "prompt, model, reference, seed, link, and mode changes must invalidate output restoration",
  );
}

const apiPrompt = {
  "1": {
    class_type: "CheckpointLoaderSimple",
    inputs: { ckpt_name: "flux1-dev-fp8.safetensors" },
  },
  "53": {
    class_type: "SaveImage",
    inputs: {
      filename_prefix: "Newtecons_3Models/CHAR_08_FLUX1_V003_HD_DRAFT_REVIEW",
    },
  },
};
const apiPromptFingerprint = await sha256Hex(canonicalJson(apiPrompt));
const staleJournal = {
  schema: "newtecons-native-ui-journal-v1",
  source: "comfyui-native-ui",
  workflow_key: serializedGraph.extra.newtecons_live.workflow_key,
  graph_fingerprint: "e0bdc73fa0954ed2cf40105f17973b557cfd2a191817cdfc0d31fd631c5ca6e8",
  api_prompt_fingerprint: apiPromptFingerprint,
  prompt_id: "59b288fa-cffb-48a2-901c-1ba78057e8e2",
  status: "completed",
  started_at_ms: 1792929628351,
  updated_at_ms: 1792929959381,
  outputs: { "54": output("CHAR_08_FLUX1_V003_HD_DRAFT_REVIEW_00001_.png") },
};
const provenHistory = {
  prompt: [
    1,
    staleJournal.prompt_id,
    apiPrompt,
    {
      extra_pnginfo: { workflow: structuredClone(serializedGraph) },
      workflow_metadata: { workflow_id: "d7087ad1-4e4e-41e6-bfd7-85de5a642ad7" },
    },
    ["8", "9", "31", "32", "53", "54"],
  ],
  status: { status_str: "success", completed: true, messages: [] },
  outputs: staleJournal.outputs,
};
const migrated = await migrateNativeJournal(
  staleJournal,
  staleJournal.workflow_key,
  stableWorkflowFingerprint,
  provenHistory,
  "2026-10-25T00:00:00.000Z",
);
assert.ok(migrated, "the legacy job must migrate when history binds it to the loaded graph");
assert.equal(migrated.graph_fingerprint, stableWorkflowFingerprint);
assert.equal(migrated.graph_fingerprint_version, GRAPH_FINGERPRINT_VERSION);
assert.equal(migrated.legacy_graph_fingerprint, staleJournal.graph_fingerprint);
assert.equal(
  migrated.graph_fingerprint_migration.history_api_prompt_fingerprint,
  apiPromptFingerprint,
);
assert.deepEqual(
  migrated.outputs,
  staleJournal.outputs,
  "migration must preserve output descriptors without rewriting their provenance",
);

const wrongPromptHistory = structuredClone(provenHistory);
wrongPromptHistory.prompt[2]["1"].inputs.ckpt_name = "different.safetensors";
assert.equal(
  await migrateNativeJournal(
    staleJournal,
    staleJournal.workflow_key,
    stableWorkflowFingerprint,
    wrongPromptHistory,
  ),
  null,
  "an API prompt mismatch must block migration",
);
const merelyCompletedHistory = structuredClone(provenHistory);
delete merelyCompletedHistory.status.status_str;
assert.equal(
  await migrateNativeJournal(
    staleJournal,
    staleJournal.workflow_key,
    stableWorkflowFingerprint,
    merelyCompletedHistory,
  ),
  null,
  "a completed flag without an explicit successful terminal status must not migrate",
);
assert.equal(
  await migrateNativeJournal(
    staleJournal,
    staleJournal.workflow_key,
    `${stableWorkflowFingerprint.slice(0, -1)}0`,
    provenHistory,
  ),
  null,
  "a current graph mismatch must block migration",
);

const apiHistory = structuredClone(provenHistory);
apiHistory.prompt[1] = "API-BIND";
const candidateApiJournal = {
  workflow_key: staleJournal.workflow_key,
  prompt_id: "API-BIND",
  status: "completed",
  recipe_fingerprint: recipe,
  outputs: staleJournal.outputs,
};
const boundApiJournal = await bindApiJournalToGraph(
  candidateApiJournal,
  candidateApiJournal.workflow_key,
  recipe,
  stableWorkflowFingerprint,
  apiHistory,
);
assert.ok(boundApiJournal, "a successful history-bound API journal may restore");
assert.equal(boundApiJournal.graph_fingerprint, stableWorkflowFingerprint);
assert.deepEqual(boundApiJournal.outputs, candidateApiJournal.outputs);
const changedApiGraph = structuredClone(serializedGraph);
changedApiGraph.nodes.find(node => node.id === 4).widgets_values[0] += " changed";
assert.equal(
  await bindApiJournalToGraph(
    candidateApiJournal,
    candidateApiJournal.workflow_key,
    recipe,
    await graphCoreFingerprint(changedApiGraph),
    apiHistory,
  ),
  null,
  "recipe equality alone must not authorize an edited API graph",
);

const extensionSource = fs.readFileSync(
  path.resolve(here, "../web/live_preview.js"),
  "utf8",
);
assert.ok(
  extensionSource.indexOf("pendingSubmissions.add(pending)")
    < extensionSource.indexOf("originalQueuePrompt.call"),
  "queue context must exist before the HTTP queue request can emit execution_start",
);
assert.match(extensionSource, /fetchPromptHistory\(promptId, attempts = 6\)/);
assert.match(extensionSource, /run\.journal\.duration_ms/);
assert.match(extensionSource, /chooseNewestJournal\([\s\S]*context\.graphFingerprint/);
assert.match(extensionSource, /bindPendingSubmission\(promptId, pending\)/);
assert.match(extensionSource, /waitForExactQueueBinding\(promptId\)/);
assert.equal(
  (extensionSource.match(/beginNativeRun\(/g) || []).length,
  2,
  "native starts must be limited to the definition and exact queue binding",
);
assert.match(
  extensionSource,
  /try \{\s*const context = await captureGraphContext\(app\.graph\)/,
  "polling acquisition must be inside the try/finally lifecycle",
);
assert.match(
  extensionSource,
  /migrateNativeJournalForContext\(context, journal\)/,
  "native recovery must pass legacy journals through history-bound migration",
);
assert.match(
  extensionSource,
  /api\.addEventListener\("executed", async event/,
  "executed-event canvas application must await its behavior guard",
);
assert.equal(
  (extensionSource.match(/if \(await contextIsCurrent\(run\.context,\s*\{/g) || []).length,
  2,
  "both executed-event and terminal canvas application must await contextIsCurrent",
);
assert.equal(
  (extensionSource.match(/applyJournalToGraph\(run\.context\.graph, run\.journal\)/g) || []).length,
  2,
  "executed-event and terminal handlers must apply only their captured graph",
);
assert.match(
  extensionSource,
  /const fingerprint = await graphCoreFingerprint\(graphBefore\);[\s\S]*app\.graph !== context\.graph[\s\S]*canonicalJson\(graphCoreProjection\(graphAfter\)\) !== canonicalBefore/,
  "contextIsCurrent must recheck graph, generation, and behavior after SHA-256",
);
assert.match(
  extensionSource,
  /bindApiJournalToGraph\([\s\S]*context\.graphFingerprint/,
  "API fallback must be behavior-bound before selection",
);
assert.match(
  extensionSource,
  /displayedSignature === imageSignature/,
  "journal application must verify the frontend output store before skipping",
);
assert.match(
  extensionSource,
  /async afterConfigureGraph\(\)[\s\S]*_newtecons_live_signature = null/,
  "graph configuration must force one safe reapplication from the store",
);

console.log("PASS: native ledger selection, edit isolation, stable fingerprints, proven migration");
