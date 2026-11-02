import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const logicUrl = new URL("../web/live_preview_logic.js", import.meta.url).href;
const {
  canonicalJson,
  graphCoreFingerprint,
  sha256Hex,
} = await import(logicUrl);

class FakeApi extends EventTarget {
  constructor() {
    super();
    this.clientId = "client-test";
    this.writes = [];
    this.queuePrompt = () => {
      throw new Error("test queue prompt not installed");
    };
  }

  async fetchApi() {
    return new Response("{}", { status: 404 });
  }

  async storeUserData(file, value) {
    this.writes.push({ file, value: structuredClone(value) });
    return new Response("{}", { status: 200 });
  }

  async listUserDataFullInfo() {
    return [];
  }
}

globalThis.localStorage = {
  values: new Map(),
  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  },
  setItem(key, value) {
    this.values.set(key, String(value));
  },
};

function graphFor(key, suffix) {
  const nodes = [
    { id: "8", type: "VAEDecode", inputs: [], mode: 0 },
    {
      id: "9",
      type: "SaveImage",
      inputs: [{ name: "images", link: 9 }],
      mode: 0,
    },
    {
      id: "10",
      type: "PreviewImage",
      inputs: [{ name: "images", link: 10 }],
      mode: 0,
    },
  ];
  const links = [
    [9, "8", 0, "9", 0, "IMAGE"],
    [10, "8", 0, "10", 0, "IMAGE"],
  ];
  return {
    id: `graph-${suffix}`,
    nodes,
    links,
    extra: { newtecons_live: { workflow_key: key } },
    serialize() {
      return structuredClone({
        nodes: this.nodes,
        links: this.links,
        extra: this.extra,
      });
    },
    getNodeById(id) {
      return this.nodes.find(node => String(node.id) === String(id)) || null;
    },
    setDirtyCanvas() {},
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

const api = new FakeApi();
const app = {
  graph: null,
  nodeOutputs: {},
  extension: null,
  registerExtension(extension) {
    this.extension = extension;
  },
};
globalThis.__api = api;
globalThis.__app = app;

const graphA = graphFor("WORKFLOW_A", "a");
const graphB = graphFor("WORKFLOW_B", "b");
const responseA = deferred();
const responseB = deferred();
const responses = [responseA, responseB];
let queueCall = 0;
api.queuePrompt = () => responses[queueCall++].promise;

const original = fs.readFileSync(
  path.resolve(here, "../web/live_preview.js"),
  "utf8",
);
const transformed = original
  .replace(
    'import { api } from "../../scripts/api.js";',
    'import { api } from "data:text/javascript,export const api=globalThis.__api";',
  )
  .replace(
    'import { app } from "../../scripts/app.js";',
    'import { app } from "data:text/javascript,export const app=globalThis.__app";',
  )
  .replace('from "./live_preview_logic.js";', `from "${logicUrl}";`);
const moduleUrl = "data:text/javascript;base64,"
  + Buffer.from(transformed).toString("base64");
const extensionModule = await import(moduleUrl);
await app.extension.setup();

api.dispatchEvent(new CustomEvent("execution_start", {
  detail: { prompt_id: "UNBOUND-JOB" },
}));
api.dispatchEvent(new CustomEvent("executed", {
  detail: {
    prompt_id: "UNBOUND-JOB",
    node: "9",
    output: {
      images: [{ filename: "wrong.png", subfolder: "test", type: "output" }],
    },
  },
}));
api.dispatchEvent(new CustomEvent("execution_success", {
  detail: { prompt_id: "UNBOUND-JOB" },
}));
await wait(80);
assert.equal(
  extensionModule.activeRuns.has("UNBOUND-JOB"),
  false,
  "an uncorrelated execution_start must not bind to the selected graph",
);
assert.equal(api.writes.length, 0);

app.graph = graphA;
const postA = api.queuePrompt(-1, {
  workflow: graphA.serialize(),
  output: { "9": { class_type: "SaveImage", inputs: { images: ["8", 0] } } },
});
app.graph = graphB;
const postB = api.queuePrompt(-1, {
  workflow: graphB.serialize(),
  output: { "9": { class_type: "SaveImage", inputs: { images: ["8", 0] } } },
});

// B starts before the HTTP response, then B's response returns before A's.
api.dispatchEvent(new CustomEvent("execution_start", {
  detail: { prompt_id: "JOB_B" },
}));
api.dispatchEvent(new CustomEvent("executed", {
  detail: {
    prompt_id: "JOB_B",
    node: "9",
    output: {
      images: [{ filename: "B.png", subfolder: "test", type: "output" }],
    },
  },
}));
await wait(20);
assert.equal(extensionModule.activeRuns.has("JOB_B"), false);

responseB.resolve({ prompt_id: "JOB_B" });
await Promise.resolve();
assert.equal(extensionModule.activeRuns.has("JOB_B"), false);
api.dispatchEvent(new CustomEvent("executed", {
  detail: {
    prompt_id: "JOB_B",
    node: "10",
    output: {
      images: [{ filename: "B-temp.png", subfolder: "test", type: "temp" }],
    },
  },
}));
await postB;
await wait(80);
assert.equal(
  extensionModule.activeRuns.get("JOB_B").context.workflowKey,
  "WORKFLOW_B",
);
assert.deepEqual(
  extensionModule.activeRuns.get("JOB_B").journal.outputs["10"],
  { images: [{ filename: "B.png", subfolder: "test", type: "output" }] },
);
assert.ok(extensionModule.activeRuns.get("JOB_B").journal.raw_outputs["10"]);

responseA.resolve({ prompt_id: "JOB_A" });
await postA;
await wait(80);
assert.equal(
  extensionModule.activeRuns.get("JOB_A").context.workflowKey,
  "WORKFLOW_A",
);
assert.ok(api.writes.some(row =>
  row.file === "newtecons-live/native-ui/WORKFLOW_B/JOB_B.json"
));
assert.ok(api.writes.some(row =>
  row.file === "newtecons-live/native-ui/WORKFLOW_A/JOB_A.json"
));

// Browser reload during B: active memory is gone, but the durable running
// ledger is reconciled from the exact prompt history when polling resumes.
extensionModule.activeRuns.clear();
app.graph = graphB;
api.fetchApi = async endpoint => {
  if (endpoint === "/history/JOB_B") {
    return new Response(JSON.stringify({
      JOB_B: {
        outputs: {
          "9": {
            images: [{ filename: "B-final.png", subfolder: "test", type: "output" }],
          },
        },
        status: {
          status_str: "success",
          completed: true,
          messages: [
            ["execution_start", { prompt_id: "JOB_B", timestamp: 1000 }],
            ["execution_success", { prompt_id: "JOB_B", timestamp: 2000 }],
          ],
        },
      },
    }), { status: 200 });
  }
  return new Response("{}", { status: 404 });
};
await wait(1100);
await extensionModule.refreshPreview();
const reconcileContext = await extensionModule.captureGraphContext(graphB);
await extensionModule.resolveNativeJournal(reconcileContext);
const reconciled = Array.from(localStorage.values.values())
  .map(value => JSON.parse(value))
  .find(value => value.prompt_id === "JOB_B");
assert.equal(reconciled.status, "completed");
assert.equal(reconciled.duration_ms, 1000);
assert.ok(reconciled.outputs["10"].images.some(image =>
  image.filename === "B-final.png" && image.type === "output"
));

const unavailable = structuredClone(reconciled);
unavailable.prompt_id = "JOB_HISTORY_MISSING";
unavailable.status = "running";
await extensionModule.reconcileNativeJournal(
  reconcileContext,
  unavailable,
);
assert.equal(unavailable.status, "running");
assert.ok(unavailable.outputs["10"].images.length > 0);

// The committed v003 journal predates viewport-normalized fingerprints. A reload
// can recover it only when history binds both the API prompt and UI graph exactly.
const graphC = graphFor("WORKFLOW_C", "c");
const stableGraphCFingerprint = await graphCoreFingerprint(graphC.serialize());
const stalePromptId = "JOB-STALE-C";
const staleApiPrompt = {
  "8": {
    class_type: "VAEDecode",
    inputs: {},
  },
  "9": {
    class_type: "SaveImage",
    inputs: { images: ["8", 0] },
  },
};
const staleJournal = {
  schema: "newtecons-native-ui-journal-v1",
  source: "comfyui-native-ui",
  workflow_key: "WORKFLOW_C",
  graph_fingerprint: "e0bdc73fa0954ed2cf40105f17973b557cfd2a191817cdfc0d31fd631c5ca6e8",
  api_prompt_fingerprint: await sha256Hex(canonicalJson(staleApiPrompt)),
  prompt_id: stalePromptId,
  status: "completed",
  started_at_ms: 3000,
  updated_at_ms: 4000,
  node_types: { "9": "SaveImage", "10": "PreviewImage" },
  preview_to_save: { "10": "9" },
  outputs: {
    "10": {
      images: [{ filename: "C-restored.png", subfolder: "test", type: "output" }],
    },
  },
};
const staleHistory = {
  [stalePromptId]: {
    prompt: [
      1,
      stalePromptId,
      staleApiPrompt,
      {
        extra_pnginfo: { workflow: graphC.serialize() },
        workflow_metadata: { workflow_id: "workflow-c-ui-id" },
      },
      ["9", "10"],
    ],
    outputs: staleJournal.outputs,
    status: {
      status_str: "success",
      completed: true,
      messages: [
        ["execution_start", { prompt_id: stalePromptId, timestamp: 3000 }],
        ["execution_success", { prompt_id: stalePromptId, timestamp: 4000 }],
      ],
    },
  },
};
const staleNativePath =
  `/userdata/newtecons-live/native-ui/WORKFLOW_C/${stalePromptId}.json`;
api.listUserDataFullInfo = async () => [
  { path: `${stalePromptId}.json`, modified: 4000 },
];
api.fetchApi = async endpoint => {
  if (decodeURIComponent(endpoint) === staleNativePath) {
    return new Response(JSON.stringify(staleJournal), { status: 200 });
  }
  if (endpoint === `/history/${stalePromptId}`) {
    return new Response(JSON.stringify(staleHistory), { status: 200 });
  }
  return new Response("{}", { status: 404 });
};
app.graph = graphC;
const staleContext = await extensionModule.captureGraphContext(graphC);
assert.equal(staleContext.graphFingerprint, stableGraphCFingerprint);
const migratedJournal = await extensionModule.resolveNativeJournal(staleContext);
assert.equal(migratedJournal.prompt_id, stalePromptId);
assert.equal(migratedJournal.graph_fingerprint, stableGraphCFingerprint);
assert.equal(
  migratedJournal.legacy_graph_fingerprint,
  staleJournal.graph_fingerprint,
);
extensionModule.applyJournalToGraph(graphC, migratedJournal);
assert.deepEqual(
  app.nodeOutputs["10"].images,
  staleJournal.outputs["10"].images,
  "the history-proven legacy journal must restore onto native PreviewImage",
);
app.nodeOutputs = {};
assert.equal(
  extensionModule.applyJournalToGraph(graphC, migratedJournal),
  true,
  "a frontend output-store reset must force the same journal to rehydrate",
);
assert.deepEqual(
  app.nodeOutputs["10"].images,
  staleJournal.outputs["10"].images,
  "the proxy output must be repopulated even when the node signature is unchanged",
);

// Deterministically suspend inside SHA-256 and switch workflows before it
// resolves. The post-await graph/generation and behavior checks must reject it.
const graphRaceA = graphFor("WORKFLOW_RACE_A", "race-a");
const graphRaceB = graphFor("WORKFLOW_RACE_B", "race-b");
app.graph = graphRaceA;
const raceContext = await extensionModule.captureGraphContext(graphRaceA);
const originalDigest = globalThis.crypto.subtle.digest.bind(globalThis.crypto.subtle);
let releaseDigest;
let signalDigestStarted;
const digestGate = new Promise(resolve => {
  releaseDigest = resolve;
});
const digestStarted = new Promise(resolve => {
  signalDigestStarted = resolve;
});
globalThis.crypto.subtle.digest = async (...args) => {
  signalDigestStarted();
  await digestGate;
  return originalDigest(...args);
};
app.graph = graphRaceA;
const raceCheck = extensionModule.contextIsCurrent(raceContext);
await digestStarted;
app.graph = graphRaceB;
releaseDigest();
assert.equal(
  await raceCheck,
  false,
  "a workflow switch during SHA-256 must invalidate the captured context",
);
globalThis.crypto.subtle.digest = originalDigest;

// A prompt edited while a run is active must update/persist the journal but
// must not paint the old job onto the changed graph.
const graphD = graphFor("WORKFLOW_D", "d");
graphD.nodes[0].widgets_values = ["prompt-before-run"];
const responseD = deferred();
responses.push(responseD);
app.graph = graphD;
const postD = api.queuePrompt(-1, {
  workflow: graphD.serialize(),
  output: { "9": { class_type: "SaveImage", inputs: { images: ["8", 0] } } },
});
responseD.resolve({ prompt_id: "JOB-EVENT-D" });
await postD;
await wait(80);
assert.ok(extensionModule.activeRuns.has("JOB-EVENT-D"));
graphD.nodes[0].widgets_values[0] = "prompt-edited-during-run";
app.nodeOutputs = {};
api.dispatchEvent(new CustomEvent("executed", {
  detail: {
    prompt_id: "JOB-EVENT-D",
    node: "10",
    output: {
      images: [{ filename: "old-event.png", subfolder: "test", type: "temp" }],
    },
  },
}));
await wait(80);
assert.equal(
  extensionModule.activeRuns.get("JOB-EVENT-D").journal.outputs["10"]
    .images[0].filename,
  "old-event.png",
  "the executed descriptor must still be captured before the canvas guard",
);
assert.equal(
  app.nodeOutputs["10"],
  undefined,
  "an executed event from an edited behavior graph must not repaint the canvas",
);

const graphRaceEvent = graphFor("WORKFLOW_EVENT_RACE", "event-race");
const graphRaceTarget = graphFor("WORKFLOW_EVENT_TARGET", "event-target");
const responseEventRace = deferred();
responses.push(responseEventRace);
app.graph = graphRaceEvent;
const postEventRace = api.queuePrompt(-1, {
  workflow: graphRaceEvent.serialize(),
  output: { "9": { class_type: "SaveImage", inputs: { images: ["8", 0] } } },
});
responseEventRace.resolve({ prompt_id: "JOB-EVENT-RACE" });
await postEventRace;
await wait(80);
assert.ok(extensionModule.activeRuns.has("JOB-EVENT-RACE"));
app.nodeOutputs = {};
app.graph = graphRaceEvent;
api.dispatchEvent(new CustomEvent("executed", {
  detail: {
    prompt_id: "JOB-EVENT-RACE",
    node: "10",
    output: {
      images: [{ filename: "A-race.png", subfolder: "test", type: "temp" }],
    },
  },
}));
app.graph = graphRaceTarget;
await wait(80);
assert.equal(
  app.nodeOutputs["10"],
  undefined,
  "an async event check must not paint captured graph A onto fresh graph B",
);
assert.equal(
  graphRaceTarget.getNodeById(10)._newtecons_live_signature,
  undefined,
  "fresh graph B must receive no onExecuted/application marker from A",
);

const graphE = graphFor("WORKFLOW_E", "e");
graphE.nodes[0].widgets_values = ["terminal-before-run"];
const responseE = deferred();
responses.push(responseE);
app.graph = graphE;
const postE = api.queuePrompt(-1, {
  workflow: graphE.serialize(),
  output: { "9": { class_type: "SaveImage", inputs: { images: ["8", 0] } } },
});
responseE.resolve({ prompt_id: "JOB-TERMINAL-E" });
await postE;
await wait(80);
assert.ok(extensionModule.activeRuns.has("JOB-TERMINAL-E"));
graphE.nodes[0].widgets_values[0] = "terminal-edited-during-run";
app.nodeOutputs = {};
api.fetchApi = async endpoint => {
  if (endpoint === "/history/JOB-TERMINAL-E") {
    return new Response(JSON.stringify({
      "JOB-TERMINAL-E": {
        outputs: {
          "9": {
            images: [{ filename: "old-terminal.png", subfolder: "test", type: "output" }],
          },
        },
        status: {
          status_str: "success",
          completed: true,
          messages: [
            ["execution_start", { prompt_id: "JOB-TERMINAL-E", timestamp: 5000 }],
            ["execution_success", { prompt_id: "JOB-TERMINAL-E", timestamp: 6000 }],
          ],
        },
      },
    }), { status: 200 });
  }
  return new Response("{}", { status: 404 });
};
await extensionModule.finishNativeRun("JOB-TERMINAL-E", "completed");
const persistedTerminal = Array.from(localStorage.values.values())
  .map(value => JSON.parse(value))
  .find(value => value.prompt_id === "JOB-TERMINAL-E");
assert.equal(
  persistedTerminal.outputs["10"].images[0].filename,
  "old-terminal.png",
  "the terminal history descriptor must still persist before the canvas guard",
);
assert.equal(
  app.nodeOutputs["10"],
  undefined,
  "terminal restoration from an edited behavior graph must remain off-canvas",
);

// API journals may use recipe metadata for run ordering, but recipe equality
// alone cannot authorize display. History must bind the UI behavior snapshot.
const apiRecipe = "d".repeat(64);
function recipeGraph(suffix, prompt) {
  const graph = graphFor("WORKFLOW_F", suffix);
  graph.extra.newtecons_live.recipe_fingerprint = apiRecipe;
  graph.nodes[0].widgets_values = [prompt];
  return graph;
}
const graphF = recipeGraph("f", "API prompt v1");
const graphFHistory = {
  "API-JOB-F": {
    prompt: [
      1,
      "API-JOB-F",
      { "8": { class_type: "VAEDecode", inputs: {} } },
      {
        extra_pnginfo: { workflow: graphF.serialize() },
        workflow_metadata: { workflow_id: "api-workflow-f" },
      },
      ["9", "10"],
    ],
    outputs: {
      "10": {
        images: [{ filename: "api-bound.png", subfolder: "test", type: "output" }],
      },
    },
    status: {
      status_str: "success",
      completed: true,
      messages: [
        ["execution_start", { prompt_id: "API-JOB-F", timestamp: 7000 }],
        ["execution_success", { prompt_id: "API-JOB-F", timestamp: 8000 }],
      ],
    },
  },
};
const apiJournalF = {
  workflow_key: "WORKFLOW_F",
  prompt_id: "API-JOB-F",
  status: "completed",
  updated_at: "2026-10-25T00:00:08.000Z",
  recipe_fingerprint: apiRecipe,
  node_types: { "9": "SaveImage", "10": "PreviewImage" },
  outputs: graphFHistory["API-JOB-F"].outputs,
};
api.listUserDataFullInfo = async () => [];
api.fetchApi = async endpoint => {
  if (decodeURIComponent(endpoint)
      === "/userdata/newtecons-live/WORKFLOW_F.json") {
    return new Response(JSON.stringify(apiJournalF), { status: 200 });
  }
  if (endpoint === "/history/API-JOB-F") {
    return new Response(JSON.stringify(graphFHistory), { status: 200 });
  }
  return new Response("{}", { status: 404 });
};
app.graph = graphF;
app.nodeOutputs = {};
await extensionModule.refreshPreview();
assert.deepEqual(
  app.nodeOutputs["10"].images,
  apiJournalF.outputs["10"].images,
  "a history-bound API recipe journal may restore its own output",
);

const graphG = recipeGraph("g", "API prompt v2 with same recipe");
app.graph = graphG;
app.nodeOutputs = {};
await extensionModule.refreshPreview();
assert.equal(
  app.nodeOutputs["10"],
  undefined,
  "an unchanged recipe must not authorize a journal after executable behavior changes",
);

console.log("PASS: lifecycle binding, edit isolation, reload, migration and API behavior binding");
process.exit(0);
