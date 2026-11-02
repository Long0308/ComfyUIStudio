import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import {
  NATIVE_UI_JOURNAL_SCHEMA,
  FINGERPRINT_PATTERN,
  GRAPH_FINGERPRINT_VERSION,
  WORKFLOW_KEY_PATTERN,
  canonicalJson,
  cloneJson,
  derivePreviewSaveMappingFromGraph,
  graphCoreFingerprint,
  graphCoreProjection,
  legacyGraphCoreFingerprint,
  nodeTypesFromGraph,
  sha256Hex,
  createNativeUiJournal,
  applyExecutionOutput,
  applyHistoryOutputs,
  bindApiJournalToGraph,
  chooseNewestJournal,
  migrateNativeJournal,
  runStartedMs,
  shouldReplaceLocalLedger,
  usableApiJournal,
  usableJournal,
  usableNativeJournalCandidate,
} from "./live_preview_logic.js";

const EXTENSION_NAME = "Newtecons.LivePreview";
const POLL_INTERVAL_MS = 1000;
const NATIVE_INDEX_TTL_MS = 5000;
const FETCH_TIMEOUT_MS = 8000;
const LOCAL_LEDGER_PREFIX = "newtecons.live-native-run.v1";
const NATIVE_ROOT = "newtecons-live/native-ui";

let graphGeneration = 0;
let isPolling = false;

const activeRuns = new Map();
const pendingSubmissions = new Set();
const queueBindingPromises = new Map();
const finishPromises = new Map();
const pendingExecutionEvents = new Map();
const writeChains = new Map();
const nativeIndexCache = new Map();
const apiHistoryOrderCache = new Map();
const apiJournalHistoryCache = new Map();
const warnedContexts = new Set();
const loggedDiagnostics = new Set();

function nowIso() {
  return new Date().toISOString();
}

function logDiagnosticOnce(key, message, details) {
  if (loggedDiagnostics.has(key)) return;
  loggedDiagnostics.add(key);
  console.info(`[${EXTENSION_NAME}] ${message} ${JSON.stringify(details)}`);
}

function contextDiagnosticKey(context, diagnostic, reason) {
  return [
    diagnostic?.origin || "context",
    diagnostic?.promptId || "none",
    context?.workflowKey || "unknown",
    reason,
  ].join(":");
}

function rejectContext(context, diagnostic, reason, details = {}) {
  logDiagnosticOnce(
    contextDiagnosticKey(context, diagnostic, reason),
    `Context guard rejected ${diagnostic?.origin || "preview"}: ${reason}`,
    {
      origin: diagnostic?.origin || "preview",
      prompt_id: diagnostic?.promptId || null,
      workflow_key: context?.workflowKey || null,
      graph_generation: context?.generation ?? null,
      ...details,
    },
  );
  return false;
}

function boundedDiagnosticValue(value, maxLength = 240) {
  if (value === undefined) return "<missing>";
  const text = JSON.stringify(value);
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function graphProjectionDiff(liveProjection, historyProjection, limit = 24) {
  const changes = [];
  const add = (path, live, history) => {
    if (changes.length >= limit) return;
    const liveValue = boundedDiagnosticValue(live);
    const historyValue = boundedDiagnosticValue(history);
    if (liveValue !== historyValue) changes.push({ path, live: liveValue, history: historyValue });
  };
  const topFields = new Set([
    ...Object.keys(liveProjection || {}),
    ...Object.keys(historyProjection || {}),
  ]);
  topFields.delete("nodes");
  topFields.delete("links");
  for (const field of [...topFields].sort()) {
    add(field, liveProjection?.[field], historyProjection?.[field]);
  }
  add("links", liveProjection?.links, historyProjection?.links);

  const liveNodes = new Map(
    (liveProjection?.nodes || []).map(node => [String(node.id), node]),
  );
  const historyNodes = new Map(
    (historyProjection?.nodes || []).map(node => [String(node.id), node]),
  );
  const nodeIds = new Set([...liveNodes.keys(), ...historyNodes.keys()]);
  for (const nodeId of [...nodeIds].sort((left, right) =>
    Number(left) - Number(right)
  )) {
    const liveNode = liveNodes.get(nodeId);
    const historyNode = historyNodes.get(nodeId);
    if (!liveNode || !historyNode) {
      add(`nodes.${nodeId}`, liveNode, historyNode);
      if (changes.length >= limit) break;
      continue;
    }
    const fields = new Set([
      ...Object.keys(liveNode),
      ...Object.keys(historyNode),
    ]);
    for (const field of [...fields].sort()) {
      add(
        `nodes.${nodeId}.${field}`,
        liveNode[field],
        historyNode[field],
      );
      if (changes.length >= limit) break;
    }
    if (changes.length >= limit) break;
  }
  return changes;
}

function localLedgerKey(workflowKey, graphFingerprint) {
  return `${LOCAL_LEDGER_PREFIX}:${workflowKey}:${graphFingerprint}`;
}

function readLocalLedger(workflowKey, graphFingerprint) {
  try {
    const value = localStorage.getItem(
      localLedgerKey(workflowKey, graphFingerprint),
    );
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

function writeLocalLedger(journal) {
  try {
    const existing = readLocalLedger(
      journal.workflow_key,
      journal.graph_fingerprint,
    );
    if (!shouldReplaceLocalLedger(existing, journal)) return false;
    localStorage.setItem(
      localLedgerKey(journal.workflow_key, journal.graph_fingerprint),
      JSON.stringify(journal),
    );
    return true;
  } catch (error) {
    console.warn(`[${EXTENSION_NAME}] Could not persist local run ledger`, error);
    return false;
  }
}

function nativeJournalPath(journal) {
  return `${NATIVE_ROOT}/${journal.workflow_key}/${journal.prompt_id}.json`;
}

function enqueueJournalWrite(journal) {
  writeLocalLedger(journal);
  const path = nativeJournalPath(journal);
  const snapshot = cloneJson(journal);
  const previous = writeChains.get(path) || Promise.resolve();
  const next = previous
    .catch(() => {})
    .then(() => api.storeUserData(path, snapshot, {
      overwrite: true,
      stringify: true,
      throwOnError: true,
    }))
    .catch(error => {
      console.warn(`[${EXTENSION_NAME}] Could not persist server ledger ${path}`, error);
    });
  writeChains.set(path, next);
  return next;
}

function graphMeta(graph) {
  const live = graph?.extra?.newtecons_live;
  if (!live || typeof live !== "object") return null;
  const workflowKey = live.workflow_key;
  if (!WORKFLOW_KEY_PATTERN.test(workflowKey || "")) return null;
  return {
    workflowKey,
    recipeFingerprint: FINGERPRINT_PATTERN.test(live.recipe_fingerprint || "")
      ? live.recipe_fingerprint : null,
    expectedGraphFingerprint: FINGERPRINT_PATTERN.test(live.graph_fingerprint || "")
      ? live.graph_fingerprint : null,
    graphFingerprintVersion:
      live.graph_fingerprint_version === GRAPH_FINGERPRINT_VERSION
        ? GRAPH_FINGERPRINT_VERSION : null,
  };
}

function serializeGraph(graph) {
  if (graph && typeof graph.serialize === "function") return graph.serialize();
  return {
    nodes: graph?.nodes || [],
    links: graph?.links || [],
    groups: graph?._groups || [],
    config: graph?.config || {},
    extra: graph?.extra || {},
    version: graph?.version,
  };
}

async function graphFingerprintMatchesMetadata(meta, serializedGraph, graphFingerprint) {
  if (!meta?.expectedGraphFingerprint) return true;
  if (meta.expectedGraphFingerprint === graphFingerprint) return true;
  if (meta.graphFingerprintVersion === GRAPH_FINGERPRINT_VERSION) return false;
  return meta.expectedGraphFingerprint
    === await legacyGraphCoreFingerprint(serializedGraph);
}

async function captureGraphContext(graph = app.graph) {
  const meta = graphMeta(graph);
  if (!graph || !meta) {
    logDiagnosticOnce(
      `capture:${meta?.workflowKey || "metadata"}`,
      "Graph context unavailable",
      { has_graph: !!graph, has_live_metadata: !!meta },
    );
    return null;
  }
  const serializedGraph = serializeGraph(graph);
  const graphFingerprint = await graphCoreFingerprint(serializedGraph);
  if (!await graphFingerprintMatchesMetadata(
    meta,
    serializedGraph,
    graphFingerprint,
  )) {
    const warningKey = `${meta.workflowKey}:${graphFingerprint}`;
    if (!warnedContexts.has(warningKey)) {
      warnedContexts.add(warningKey);
      console.warn(
        `[${EXTENSION_NAME}] ${meta.workflowKey} was edited or has stale metadata; `
        + `graph=${graphFingerprint}, metadata=${meta.expectedGraphFingerprint}`,
      );
    }
    logDiagnosticOnce(
      `capture-metadata:${meta.workflowKey}:${graphFingerprint}`,
      "Graph context rejected by workflow fingerprint metadata",
      {
        workflow_key: meta.workflowKey,
        graph_fingerprint: graphFingerprint,
        expected_graph_fingerprint: meta.expectedGraphFingerprint,
      },
    );
    return null;
  }
  logDiagnosticOnce(
    `captured:${meta.workflowKey}:${graphFingerprint}`,
    "Graph context captured",
    {
      workflow_key: meta.workflowKey,
      graph_fingerprint: graphFingerprint,
      graph_generation: graphGeneration,
      nodes: serializedGraph?.nodes?.length ?? null,
      links: serializedGraph?.links?.length ?? null,
    },
  );
  return {
    graph,
    generation: graphGeneration,
    graphProjection: graphCoreProjection(serializedGraph),
    workflowKey: meta.workflowKey,
    recipeFingerprint: meta.recipeFingerprint,
    graphFingerprint,
    nodeTypes: null,
    previewToSave: null,
    submittedApiFingerprint: null,
  };
}

async function contextIsCurrent(context, diagnostic = null) {
  if (!context) {
    return rejectContext(context, diagnostic, "missing_context");
  }
  if (app.graph !== context.graph) {
    return rejectContext(context, diagnostic, "graph_identity_changed", {
      active_generation: graphGeneration,
    });
  }
  if (graphGeneration !== context.generation) {
    return rejectContext(context, diagnostic, "generation_changed", {
      active_generation: graphGeneration,
    });
  }
  const metaBefore = graphMeta(context.graph);
  if (!metaBefore || metaBefore.workflowKey !== context.workflowKey) {
    return rejectContext(context, diagnostic, "workflow_metadata_changed", {
      active_workflow_key: metaBefore?.workflowKey || null,
    });
  }
  const graphBefore = serializeGraph(context.graph);
  const canonicalBefore = canonicalJson(graphCoreProjection(graphBefore));
  const fingerprint = await graphCoreFingerprint(graphBefore);
  if (app.graph !== context.graph) {
    return rejectContext(context, diagnostic, "graph_identity_changed_after_hash", {
      active_generation: graphGeneration,
    });
  }
  if (graphGeneration !== context.generation) {
    return rejectContext(context, diagnostic, "generation_changed_after_hash", {
      active_generation: graphGeneration,
    });
  }
  if (fingerprint !== context.graphFingerprint) {
    return rejectContext(context, diagnostic, "fingerprint_changed_after_hash", {
      current_fingerprint: fingerprint,
    });
  }

  const graphAfter = serializeGraph(context.graph);
  if (canonicalJson(graphCoreProjection(graphAfter)) !== canonicalBefore) {
    return rejectContext(context, diagnostic, "behavior_changed_during_hash");
  }
  const metaAfter = graphMeta(context.graph);
  if (!metaAfter
      || metaAfter.workflowKey !== context.workflowKey
      || !await graphFingerprintMatchesMetadata(
        metaAfter,
        graphAfter,
        fingerprint,
      )) {
    return rejectContext(context, diagnostic, "workflow_metadata_changed_after_hash", {
      active_workflow_key: metaAfter?.workflowKey || null,
    });
  }

  if (app.graph !== context.graph
      || graphGeneration !== context.generation
      || canonicalJson(graphCoreProjection(serializeGraph(context.graph)))
        !== canonicalBefore) {
    return rejectContext(context, diagnostic, "context_changed_during_metadata_check", {
      active_generation: graphGeneration,
    });
  }
  return true;
}

async function captureSubmissionContext(workflow, apiOutput, graph = app.graph) {
  const submittedGraph = workflow || serializeGraph(graph);
  const meta = graphMeta(submittedGraph);
  if (!graph || !meta) return null;
  const graphFingerprint = await graphCoreFingerprint(submittedGraph);
  if (!await graphFingerprintMatchesMetadata(
    meta,
    submittedGraph,
    graphFingerprint,
  )) return null;
  const apiPromptFingerprint = apiOutput
    ? await sha256Hex(canonicalJson(apiOutput)) : null;
  return {
    graph,
    generation: graphGeneration,
    workflowKey: meta.workflowKey,
    recipeFingerprint: meta.recipeFingerprint,
    graphFingerprint,
    submittedApiFingerprint: apiPromptFingerprint,
    nodeTypes: nodeTypesFromGraph(submittedGraph),
    previewToSave: derivePreviewSaveMappingFromGraph(submittedGraph),
  };
}

async function fetchJson(endpoint) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await api.fetchApi(endpoint, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) return null;
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchApiJournal(context) {
  if (!context.recipeFingerprint) return null;
  const endpoint = `/userdata/${encodeURIComponent(
    `newtecons-live/${context.workflowKey}.json`,
  )}`;
  const journal = await fetchJson(endpoint);
  if (!usableApiJournal(
    journal,
    context.workflowKey,
    context.recipeFingerprint,
  )) return null;

  let historyEntry = apiJournalHistoryCache.get(journal.prompt_id);
  if (!historyEntry
      || historyEntry.graphFingerprint !== context.graphFingerprint) {
    const payload = await fetchJson(
      `/history/${encodeURIComponent(journal.prompt_id)}`,
    );
    const history = payload?.[journal.prompt_id] || payload;
    historyEntry = {
      graphFingerprint: context.graphFingerprint,
      history,
    };
  }
  const boundJournal = await bindApiJournalToGraph(
    journal,
    context.workflowKey,
    context.recipeFingerprint,
    context.graphFingerprint,
    historyEntry.history,
    nowIso(),
  );
  if (!boundJournal) return null;
  apiJournalHistoryCache.set(journal.prompt_id, historyEntry);
  journal.graph_fingerprint = boundJournal.graph_fingerprint;
  journal.graph_fingerprint_version = boundJournal.graph_fingerprint_version;
  journal.graph_binding = boundJournal.graph_binding;

  if (journal.run_started_at_ms == null) {
    let order = apiHistoryOrderCache.get(journal.prompt_id);
    if (!order) {
      const messages = historyEntry.history?.status?.messages || [];
      const start = messages.find(item => item?.[0] === "execution_start");
      const terminal = messages.find(item =>
        ["execution_success", "execution_error", "execution_interrupted"]
          .includes(item?.[0])
      );
      order = {
        startedAtMs: Number(start?.[1]?.timestamp),
        endedAtMs: Number(terminal?.[1]?.timestamp),
      };
      if (Number.isFinite(order.startedAtMs)
          || Number.isFinite(order.endedAtMs)) {
        apiHistoryOrderCache.set(journal.prompt_id, order);
      }
    }
    if (Number.isFinite(order.startedAtMs)) {
      journal.run_started_at_ms = order.startedAtMs;
      journal.run_order_source = "history.execution_start.timestamp";
    }
    if (Number.isFinite(order.endedAtMs)) {
      journal.run_ended_at_ms = order.endedAtMs;
    }
  }
  return journal;
}

async function fetchNativeJournal(context, promptId) {
  const endpoint = `/userdata/${encodeURIComponent(
    `${NATIVE_ROOT}/${context.workflowKey}/${promptId}.json`,
  )}`;
  const journal = await fetchJson(endpoint);
  const usable = usableNativeJournalCandidate(
    journal,
    context.workflowKey,
    promptId,
  );
  if (!usable) {
    logDiagnosticOnce(
      `native-candidate:${context.workflowKey}:${promptId}`,
      "Native journal candidate rejected",
      {
        workflow_key: context.workflowKey,
        prompt_id: promptId,
        has_journal: !!journal,
        schema: journal?.schema || null,
        source: journal?.source || null,
        journal_workflow_key: journal?.workflow_key || null,
        graph_fingerprint: journal?.graph_fingerprint || null,
        status: journal?.status || null,
        output_nodes: Object.keys(journal?.outputs || {}),
      },
    );
    return null;
  }
  return journal;
}

async function migrateNativeJournalForContext(context, journal) {
  if (usableJournal(
    journal,
    context.workflowKey,
    context.graphFingerprint,
  )) return journal;
  if (!usableNativeJournalCandidate(journal, context.workflowKey)) {
    logDiagnosticOnce(
      `native-candidate-unusable:${context.workflowKey}:${journal?.prompt_id || "none"}`,
      "Native journal could not enter migration",
      {
        workflow_key: context.workflowKey,
        prompt_id: journal?.prompt_id || null,
        graph_fingerprint: journal?.graph_fingerprint || null,
      },
    );
    return null;
  }
  const payload = await fetchJson(
    `/history/${encodeURIComponent(journal.prompt_id)}`,
  );
  const history = payload?.[journal.prompt_id] || payload;
  const migrated = await migrateNativeJournal(
    journal,
    context.workflowKey,
    context.graphFingerprint,
    history,
    nowIso(),
  );
  if (migrated) {
    // Persist the proven binding so a later server restart need not retain history.
    await enqueueJournalWrite(migrated);
    return migrated;
  }

  const submittedGraph = history?.prompt?.[3]?.extra_pnginfo?.workflow;
  const submittedFingerprint = submittedGraph
    ? await graphCoreFingerprint(submittedGraph) : null;
  logDiagnosticOnce(
    `native-migration-rejected:${context.workflowKey}:${journal.prompt_id}`,
    "Native journal migration rejected",
    {
      workflow_key: context.workflowKey,
      prompt_id: journal.prompt_id,
      context_graph_fingerprint: context.graphFingerprint,
      submitted_graph_fingerprint: submittedFingerprint,
      journal_graph_fingerprint: journal.graph_fingerprint,
      journal_api_prompt_fingerprint: journal.api_prompt_fingerprint,
      submitted_workflow_key:
        submittedGraph?.extra?.newtecons_live?.workflow_key || null,
      history_found: !!payload,
      history_status: history?.status?.status_str || null,
      history_prompt_present: Array.isArray(history?.prompt),
      projection_diff: submittedGraph
        ? graphProjectionDiff(
          context.graphProjection || graphCoreProjection(serializeGraph(context.graph)),
          graphCoreProjection(submittedGraph),
        )
        : [],
    },
  );
  return null;
}

function newerNativeJournal(left, right) {
  if (!left) return right;
  if (!right) return left;
  if (left.prompt_id === right.prompt_id) {
    return Number(right.updated_at_ms || 0) >= Number(left.updated_at_ms || 0)
      ? right : left;
  }
  return Number(runStartedMs(right) || 0) >= Number(runStartedMs(left) || 0)
    ? right : left;
}

function historyTerminalStatus(status) {
  if (status?.status_str === "success" || status?.completed === true) {
    return "completed";
  }
  if (status?.status_str === "interrupted") return "interrupted";
  if (status?.status_str === "error") return "error";
  return null;
}

async function reconcileNativeJournal(context, journal) {
  if (!journal || ["completed", "error", "interrupted"].includes(journal.status)
      || activeRuns.has(journal.prompt_id)
      || finishPromises.has(journal.prompt_id)) {
    return journal;
  }
  const payload = await fetchJson(
    `/history/${encodeURIComponent(journal.prompt_id)}`,
  );
  const history = payload?.[journal.prompt_id] || payload;
  const terminalStatus = historyTerminalStatus(history?.status);
  if (!terminalStatus) return journal;
  if (history.outputs && typeof history.outputs === "object") {
    applyHistoryOutputs(journal, history.outputs);
  }
  const messages = history.status?.messages || [];
  const start = messages.find(item => item?.[0] === "execution_start");
  const terminal = messages.find(item =>
    ["execution_success", "execution_error", "execution_interrupted"]
      .includes(item?.[0])
  );
  const startedAtMs = Number(start?.[1]?.timestamp);
  const terminalAtMs = Number(terminal?.[1]?.timestamp);
  if (Number.isFinite(startedAtMs)) journal.started_at_ms = startedAtMs;
  if (Number.isFinite(terminalAtMs)) journal.terminal_at_ms = terminalAtMs;
  journal.status = terminalStatus;
  journal.history_status = history.status;
  journal.history_restored_at_utc = nowIso();
  journal.descriptor_delivery = (
    Object.keys(journal.outputs || {}).length
      ? "EVENT_AND_HISTORY_DESCRIPTORS_PERSISTED"
      : "NO_OUTPUT_DESCRIPTORS"
  );
  journal.updated_at_ms = Date.now();
  journal.updated_at_utc = nowIso();
  if (Number.isFinite(startedAtMs) && Number.isFinite(terminalAtMs)) {
    journal.duration_ms = Math.max(0, terminalAtMs - startedAtMs);
    journal.duration_seconds = journal.duration_ms / 1000;
  }
  await enqueueJournalWrite(journal);
  const cacheKey = `${context.workflowKey}:${context.graphFingerprint}`;
  nativeIndexCache.delete(cacheKey);
  return journal;
}

async function discoverLatestNativeJournal(context) {
  const cacheKey = `${context.workflowKey}:${context.graphFingerprint}`;
  const cached = nativeIndexCache.get(cacheKey);
  if (cached && Date.now() - cached.fetchedAt < NATIVE_INDEX_TTL_MS) {
    return cached.journal;
  }
  const directory = `${NATIVE_ROOT}/${context.workflowKey}`;
  let listing = null;
  try {
    listing = await api.listUserDataFullInfo(directory);
  } catch {
    const endpoint = `/userdata?dir=${encodeURIComponent(directory)}`
      + "&recurse=true&split=false&full_info=true";
    listing = await fetchJson(endpoint);
  }
  const files = (Array.isArray(listing) ? listing : [])
    .filter(item => /^[0-9A-Za-z-]+\.json$/.test(item?.path || item?.name || ""))
    .sort((left, right) =>
      Number(right.modified || right.modified_ms || 0)
      - Number(left.modified || left.modified_ms || 0)
    )
    .slice(0, 4);
  logDiagnosticOnce(
    `native-listing:${context.workflowKey}:${context.graphFingerprint}`,
    "Native journal directory listed",
    {
      workflow_key: context.workflowKey,
      graph_fingerprint: context.graphFingerprint,
      listing_is_array: Array.isArray(listing),
      listing_count: Array.isArray(listing) ? listing.length : null,
      file_count: files.length,
      file_paths: files.map(file => file.path || file.name),
    },
  );
  const journals = await Promise.all(files.map(async file => {
    const name = file.path || file.name;
    const promptId = name.replace(/\.json$/, "");
    const journal = await fetchNativeJournal(context, promptId);
    return await migrateNativeJournalForContext(context, journal);
  }));
  let latest = null;
  for (const journal of journals) {
    latest = newerNativeJournal(latest, journal);
  }
  nativeIndexCache.set(cacheKey, {
    fetchedAt: Date.now(),
    journal: latest,
  });
  return latest;
}

async function resolveNativeJournal(context) {
  let local = readLocalLedger(
    context.workflowKey,
    context.graphFingerprint,
  );
  if (!usableJournal(
    local,
    context.workflowKey,
    context.graphFingerprint,
  )) local = null;
  const localPromptId = local?.prompt_id;
  const [exactServerCandidate, latestServer] = await Promise.all([
    localPromptId ? fetchNativeJournal(context, localPromptId) : Promise.resolve(null),
    discoverLatestNativeJournal(context),
  ]);
  const exactServer = await migrateNativeJournalForContext(
    context,
    exactServerCandidate,
  );
  const selected = newerNativeJournal(
    local,
    newerNativeJournal(exactServer, latestServer),
  );
  return await reconcileNativeJournal(context, selected);
}

function clearOutputNodes(graph, nodeTypes) {
  for (const node of graph?.nodes || []) {
    const nodeId = String(node.id);
    const type = node.type || node.comfyClass;
    if (!["SaveImage", "PreviewImage"].includes(type)
        || (nodeTypes[nodeId] && nodeTypes[nodeId] !== type)) continue;
    node._newtecons_live_signature = null;
    node.imgs = undefined;
    node.images = undefined;
    node.imageIndex = null;
    if (app.nodeOutputs) delete app.nodeOutputs[node.id];
    try {
      if (typeof node.onExecuted === "function") node.onExecuted({ images: [] });
    } catch {}
  }
}

function imageListSignature(images) {
  if (!Array.isArray(images)) return "";
  return images.map(image =>
    `${image?.filename}:${image?.subfolder || ""}:${image?.type || ""}`
  ).join("|");
}

function applyJournalToGraph(graph, journal) {
  if (!graph || !journal) return false;
  const previousPrompt = graph._newtecons_last_prompt_id;
  if (previousPrompt !== journal.prompt_id) {
    clearOutputNodes(graph, journal.node_types || {});
    graph._newtecons_last_prompt_id = journal.prompt_id;
  }
  const nodeTypes = journal.node_types || {};
  let changed = false;
  for (const [nodeIdString, nodeOutput] of Object.entries(journal.outputs || {})) {
    const nodeId = Number(nodeIdString);
    if (!Number.isFinite(nodeId)) continue;
    const node = graph.getNodeById(nodeId);
    if (!node) continue;
    const actualType = node.type || node.comfyClass;
    if (!["SaveImage", "PreviewImage"].includes(actualType)
        || nodeTypes[nodeIdString] !== actualType) continue;
    const images = nodeOutput?.images;
    if (!Array.isArray(images) || !images.length) continue;
    const imageSignature = imageListSignature(images);
    const signature = `${imageSignature}@${journal.prompt_id}`;
    const displayedSignature = imageListSignature(
      app.nodeOutputs?.[node.id]?.images,
    );
    if (node._newtecons_live_signature === signature
        && displayedSignature === imageSignature) continue;
    app.nodeOutputs ||= {};
    app.nodeOutputs[node.id] = cloneJson(nodeOutput);
    try {
      if (typeof node.onExecuted === "function") node.onExecuted(nodeOutput);
    } catch (error) {
      console.warn(`[${EXTENSION_NAME}] Native preview failed on node ${node.id}`, error);
    }
    node._newtecons_live_signature = signature;
    changed = true;
  }
  if (changed) graph.setDirtyCanvas(true, true);
  if (changed) {
    const workflowKey = graphMeta(graph)?.workflowKey || "unknown";
    logDiagnosticOnce(
      `applied:${workflowKey}:${journal.prompt_id}`,
      "Persisted output descriptors applied to native canvas nodes",
      {
        workflow_key: workflowKey,
        prompt_id: journal.prompt_id,
        output_nodes: Object.keys(journal.outputs || {}),
      },
    );
  }
  return changed;
}

async function beginNativeRun(promptId, explicitContext = null, startedAtMs = null) {
  if (!promptId || activeRuns.has(promptId)) return activeRuns.get(promptId);
  const context = explicitContext || await captureGraphContext(app.graph);
  if (!context) return null;
  if (!explicitContext && !await contextIsCurrent(context)) return null;
  const journal = createNativeUiJournal({
    graph: context.graph,
    workflowKey: context.workflowKey,
    graphFingerprint: context.graphFingerprint,
    recipeFingerprint: context.recipeFingerprint,
    promptId,
    clientId: api.clientId || null,
    startedAtMs: startedAtMs ?? Date.now(),
    apiPromptFingerprint: context.submittedApiFingerprint || null,
    nodeTypes: context.nodeTypes || null,
    previewToSave: context.previewToSave || null,
  });
  journal.started_at_utc = nowIso();
  journal.updated_at_utc = journal.started_at_utc;
  journal.status = "running";
  const run = { journal, context };
  activeRuns.set(promptId, run);
  clearOutputNodes(context.graph, journal.node_types);
  context.graph._newtecons_last_prompt_id = promptId;
  await enqueueJournalWrite(journal);
  const pending = pendingExecutionEvents.get(promptId);
  if (pending) {
    pendingExecutionEvents.delete(promptId);
    for (const pendingEvent of pending) {
      if (pendingEvent.type === "executed") {
        applyExecutionOutput(journal, pendingEvent.data.node, pendingEvent.data.output);
      } else if (pendingEvent.type === "execution_cached") {
        journal.cached_nodes = Array.from(new Set(
          (pendingEvent.data.nodes || []).map(String),
        ));
      }
    }
    await enqueueJournalWrite(journal);
  }
  return run;
}

function activeRunFor(promptId) {
  return promptId ? activeRuns.get(promptId) : null;
}

function bindPendingSubmission(promptId, pending = null) {
  if (!promptId) return Promise.resolve(null);
  if (queueBindingPromises.has(promptId)) {
    return queueBindingPromises.get(promptId);
  }
  pending ||= Array.from(pendingSubmissions).find(item =>
    item.promptId === promptId
  ) || null;
  if (!pending) return Promise.resolve(null);
  pending.promptId = promptId;
  const binding = pending.contextPromise
    .then(context => context
      ? beginNativeRun(promptId, context, pending.startedAtMs)
      : null)
    .finally(() => {
      pendingSubmissions.delete(pending);
      queueBindingPromises.delete(promptId);
    });
  queueBindingPromises.set(promptId, binding);
  return binding;
}

function installQueuePromptHook() {
  if (api._newteconsLiveQueueHookInstalled) return;
  const originalQueuePrompt = api.queuePrompt;
  if (typeof originalQueuePrompt !== "function") return;
  api.queuePrompt = async function newteconsQueuePrompt(front, request, options) {
    const graphAtSubmission = app.graph;
    const startedAtMs = Date.now();
    const workflow = request?.workflow || serializeGraph(graphAtSubmission);
    const contextPromise = captureSubmissionContext(
      workflow,
      request?.output,
      graphAtSubmission,
    ).catch(() => null);
    const pending = {
      promptId: null,
      startedAtMs,
      graphAtSubmission,
      contextPromise,
    };
    pendingSubmissions.add(pending);
    let result;
    try {
      result = await originalQueuePrompt.call(this, front, request, options);
    } catch (error) {
      pendingSubmissions.delete(pending);
      throw error;
    }
    const promptId = result?.prompt_id;
    if (promptId) bindPendingSubmission(promptId, pending).catch(() => {});
    else pendingSubmissions.delete(pending);
    return result;
  };
  api._newteconsLiveQueueHookInstalled = true;
}

function updateTransientState(run, eventType) {
  const journal = run?.journal;
  if (!journal) return;
  journal.status = eventType;
  journal.updated_at_ms = Date.now();
  journal.updated_at_utc = nowIso();
  enqueueJournalWrite(journal);
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForExactQueueBinding(promptId, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const binding = queueBindingPromises.get(promptId);
    if (binding) return binding;
    if (!pendingSubmissions.size) return null;
    await wait(25);
  }
  return queueBindingPromises.get(promptId) || null;
}

async function fetchPromptHistory(promptId, attempts = 6) {
  const delays = [0, 100, 250, 500, 1000, 1500];
  let last = null;
  for (let index = 0; index < attempts; index += 1) {
    if (delays[index]) await wait(delays[index]);
    try {
      const payload = await fetchJson(`/history/${encodeURIComponent(promptId)}`);
      last = payload?.[promptId] || payload || null;
      if (last?.outputs && Object.keys(last.outputs).length) return last;
    } catch {}
  }
  return last;
}

async function finishNativeRun(promptId, status) {
  if (!promptId) return;
  if (finishPromises.has(promptId)) return finishPromises.get(promptId);
  const operation = (async () => {
  let binding = queueBindingPromises.get(promptId);
  if (!binding && pendingSubmissions.size) {
    binding = await waitForExactQueueBinding(promptId);
  }
  if (binding) await binding;
  const run = activeRunFor(promptId);
  if (!run) {
    console.warn(`[${EXTENSION_NAME}] Ignoring uncorrelated terminal event ${promptId}`);
    return;
  }
  run.journal.status = status;
  run.journal.terminal_at_ms = Date.now();
  run.journal.terminal_at_utc = nowIso();
  if (status === "completed") {
    const history = await fetchPromptHistory(promptId);
    if (history?.outputs && Object.keys(history.outputs).length) {
      applyHistoryOutputs(run.journal, history.outputs);
      run.journal.history_status = history.status || null;
      run.journal.history_restored_at_utc = nowIso();
      run.journal.descriptor_delivery = "EVENT_AND_HISTORY_DESCRIPTORS_PERSISTED";
    } else {
      run.journal.history_status = "UNAVAILABLE_AFTER_RETRY";
      run.journal.descriptor_delivery = (
        Object.keys(run.journal.outputs || {}).length
          ? "EVENT_DESCRIPTORS_PERSISTED"
          : "NO_OUTPUT_DESCRIPTORS"
      );
    }
  }
  run.journal.updated_at_ms = Date.now();
  run.journal.updated_at_utc = nowIso();
  run.journal.duration_ms = Math.max(
    0,
    Number(run.journal.terminal_at_ms || Date.now())
      - Number(run.journal.started_at_ms || Date.now()),
  );
  run.journal.duration_seconds = run.journal.duration_ms / 1000;
  await enqueueJournalWrite(run.journal);
  if (await contextIsCurrent(run.context, {
    origin: "terminal",
    promptId,
  })) {
    applyJournalToGraph(run.context.graph, run.journal);
  }
  activeRuns.delete(promptId);
  })();
  finishPromises.set(promptId, operation);
  try {
    await operation;
  } finally {
    finishPromises.delete(promptId);
  }
}

function installApiListeners() {
  api.addEventListener("execution_start", event => {
    const promptId = event.detail?.prompt_id;
    if (!promptId) return;
    const binding = queueBindingPromises.get(promptId);
    if (binding) binding.catch(() => {});
  });

  api.addEventListener("executed", async event => {
    const detail = event.detail || {};
    const promptId = detail.prompt_id;
    if (!promptId) return;
    const run = activeRunFor(promptId);
    if (!run) {
      const pending = pendingExecutionEvents.get(promptId) || [];
      if (pending.length < 64) {
        pending.push({ type: "executed", data: detail });
        pendingExecutionEvents.set(promptId, pending);
      }
      const binding = queueBindingPromises.get(promptId);
      if (binding) binding.catch(() => {});
      else if (!pendingSubmissions.size) {
        console.warn(`[${EXTENSION_NAME}] Ignoring uncorrelated executed event ${promptId}`);
      }
      return;
    }
    const changed = applyExecutionOutput(
      run.journal,
      detail.node ?? detail.display_node,
      detail.output,
    );
    if (!changed) return;
    enqueueJournalWrite(run.journal);
    if (await contextIsCurrent(run.context, {
      origin: "executed",
      promptId,
    })) {
      applyJournalToGraph(run.context.graph, run.journal);
    }
  });

  api.addEventListener("execution_cached", event => {
    const run = activeRunFor(event.detail?.prompt_id);
    if (!run) {
      if (event.detail?.prompt_id
          && (pendingSubmissions.size || queueBindingPromises.has(event.detail.prompt_id))) {
        const pending = pendingExecutionEvents.get(event.detail.prompt_id) || [];
        pending.push({ type: "execution_cached", data: event.detail });
        pendingExecutionEvents.set(event.detail.prompt_id, pending);
      }
      return;
    }
    if (!Array.isArray(event.detail?.nodes)) return;
    run.journal.cached_nodes = [...new Set(event.detail.nodes.map(String))];
    run.journal.updated_at_ms = Date.now();
    enqueueJournalWrite(run.journal);
  });

  api.addEventListener("execution_success", event => {
    const promptId = event.detail?.prompt_id;
    if (promptId) finishNativeRun(promptId, "completed").catch(() => {});
  });

  api.addEventListener("execution_error", event => {
    const detail = event.detail || {};
    const run = activeRunFor(detail.prompt_id);
    if (run) {
      run.journal.error = {
        type: detail.exception_type || "ExecutionError",
        message: detail.exception_message || "Unknown execution error",
        node_id: detail.node_id ?? null,
      };
    }
    if (detail.prompt_id) finishNativeRun(detail.prompt_id, "error").catch(() => {});
  });

  api.addEventListener("execution_interrupted", event => {
    const promptId = event.detail?.prompt_id;
    if (promptId) finishNativeRun(promptId, "interrupted").catch(() => {});
  });
}

async function refreshPreview() {
  if (isPolling) return;
  isPolling = true;
  try {
    const context = await captureGraphContext(app.graph);
    if (!context) return;
    const [apiJournal, nativeJournal] = await Promise.all([
      fetchApiJournal(context),
      resolveNativeJournal(context),
    ]);
    const selected = chooseNewestJournal(
      apiJournal,
      nativeJournal,
      context.workflowKey,
      context.recipeFingerprint,
      context.graphFingerprint,
    );
    if (!selected) {
      logDiagnosticOnce(
        `select:none:${context.workflowKey}`,
        "No usable journal selected for active graph",
        {
          workflow_key: context.workflowKey,
          has_api_journal: !!apiJournal,
          has_native_journal: !!nativeJournal,
        },
      );
      return;
    }
    if (!await contextIsCurrent(context, { origin: "refresh" })) return;
    applyJournalToGraph(context.graph, selected);
  } catch (error) {
    console.warn(`[${EXTENSION_NAME}] Preview refresh failed`, error);
  } finally {
    isPolling = false;
  }
}

app.registerExtension({
  name: EXTENSION_NAME,
  async setup() {
    installQueuePromptHook();
    installApiListeners();
    setInterval(() => refreshPreview().catch(() => {}), POLL_INTERVAL_MS);
    setTimeout(() => refreshPreview().catch(() => {}), 500);
    console.log(
      `[${EXTENSION_NAME}] Native UI run ledger active (${GRAPH_FINGERPRINT_VERSION}); `
      + "event outputs are persisted before history is queried.",
    );
  },
  async afterConfigureGraph() {
    graphGeneration += 1;
    warnedContexts.clear();
    for (const node of app.graph?.nodes || []) {
      if (["SaveImage", "PreviewImage"].includes(node.type || node.comfyClass)) {
        node._newtecons_live_signature = null;
      }
    }
    setTimeout(() => refreshPreview().catch(() => {}), 200);
  },
});

export {
  activeRuns,
  applyJournalToGraph,
  beginNativeRun,
  captureGraphContext,
  chooseNewestJournal,
  contextIsCurrent,
  finishNativeRun,
  graphCoreFingerprint,
  graphMeta,
  reconcileNativeJournal,
  refreshPreview,
  resolveNativeJournal,
};
