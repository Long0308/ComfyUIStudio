export const NATIVE_UI_JOURNAL_SCHEMA = "newtecons-native-ui-journal-v1";
export const GRAPH_FINGERPRINT_VERSION = "newtecons-graph-core-v3";
export const WORKFLOW_KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
export const FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/;

export function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

export function canonicalJson(value) {
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(key =>
      JSON.stringify(key) + ":" + canonicalJson(value[key])
    ).join(",") + "}";
  }
  return JSON.stringify(value);
}

export async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), byte =>
    byte.toString(16).padStart(2, "0")
  ).join("");
}

function normalizedLinkRowsForFingerprint(graph) {
  const rows = normalizedLinkRows(graph);
  return rows.map(row => {
    if (Array.isArray(row) && row.length >= 6) {
      return [
        String(row[0]),
        String(row[1]),
        Number(row[2]),
        String(row[3]),
        Number(row[4]),
        String(row[5]),
      ];
    }
    if (row && row.id != null && row.origin_id != null
        && row.target_id != null) {
      return [
        String(row.id),
        String(row.origin_id),
        Number(row.origin_slot),
        String(row.target_id),
        Number(row.target_slot),
        String(row.type),
      ];
    }
    return cloneJson(row);
  }).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
}

export function graphCoreProjection(graphOrData) {
  const core = cloneJson(graphOrData);
  // These fields are canvas/editor state. None participate in ComfyUI execution.
  for (const field of [
    "id",
    "revision",
    "last_node_id",
    "last_link_id",
    "groups",
    "_groups",
    "config",
  ]) delete core?.[field];
  if (core?.extra && typeof core.extra === "object") {
    for (const field of ["ds", "frontendVersion", "newtecons_live"]) {
      delete core.extra[field];
    }
    if (!Object.keys(core.extra).length) delete core.extra;
  }

  const runtimeNodeFields = [
    "imgs",
    "images",
    "imageIndex",
    "_loadedWidgetValue",
    "_newtecons_live_signature",
    "order",
    "size",
    "pos",
    "selected",
    "collapsed",
    "pinned",
    "bounding",
    "color",
    "bgcolor",
    "flags",
    "title",
    "label",
    "widgets_values_named",
  ];
  if (Array.isArray(core?.nodes)) {
    for (const node of core.nodes) {
      for (const field of runtimeNodeFields) delete node?.[field];
      const nodeType = node.type || node.comfyClass;
      delete node.comfyClass;
      if (nodeType != null) node.type = nodeType;
      if (node.id != null) node.id = String(node.id);
      if (Number(node.mode ?? 0) === 0) delete node.mode;
      if (Array.isArray(node.inputs)) {
        // Queue/export omit unconnected widget sockets. Their executable values
        // remain in widgets_values; connected sockets must retain their links.
        node.inputs = node.inputs.filter(input => !(input.widget && input.link == null));
        for (const input of node.inputs) {
          delete input.shape;
          delete input.localized_name;
        }
        node.inputs.sort((left, right) =>
          String(left?.name).localeCompare(String(right?.name))
        );
      }
      for (const output of node.outputs || []) delete output.localized_name;
      if (Array.isArray(node.widgets_values)) {
        // LoadImage's trailing upload control is UI-only. The filename is kept.
        if (nodeType === "LoadImage") {
          node.widgets_values = node.widgets_values.slice(0, 1);
        }
        if (!node.widgets_values.length) delete node.widgets_values;
      }
    }
    core.nodes.sort((left, right) =>
      String(left?.id).localeCompare(String(right?.id))
    );
  }
  core.links = normalizedLinkRowsForFingerprint(core);
  return core;
}

export async function graphCoreFingerprint(graphOrData) {
  const core = graphCoreProjection(graphOrData);
  return await sha256Hex(canonicalJson(core));
}

export async function legacyGraphCoreFingerprint(graphOrData) {
  const core = cloneJson(graphOrData);
  if (core?.extra && Object.prototype.hasOwnProperty.call(core.extra, "newtecons_live")) {
    delete core.extra.newtecons_live;
  }
  if (core?.extra?.ds && typeof core.extra.ds === "object") {
    delete core.extra.ds.scale;
    delete core.extra.ds.offset;
    if (!Object.keys(core.extra.ds).length) delete core.extra.ds;
  }
  const runtimeNodeFields = [
    "imgs",
    "images",
    "imageIndex",
    "_loadedWidgetValue",
    "_newtecons_live_signature",
  ];
  for (const node of core?.nodes || []) {
    for (const field of runtimeNodeFields) delete node?.[field];
  }
  return await sha256Hex(canonicalJson(core));
}

export function validWorkflowIdentity(value, workflowKey) {
  return !!value
    && value.workflow_key === workflowKey
    && WORKFLOW_KEY_PATTERN.test(workflowKey || "")
    && FINGERPRINT_PATTERN.test(value.graph_fingerprint || "");
}

function normalizedLinkRows(graph) {
  if (Array.isArray(graph?.links)) return graph.links;
  if (graph?.links && typeof graph.links === "object") {
    return Object.values(graph.links);
  }
  return [];
}

function linkSource(row) {
  if (Array.isArray(row) && row.length >= 3) {
    return [String(row[1]), Number(row[2])];
  }
  if (row && row.origin_id != null) {
    return [String(row.origin_id), Number(row.origin_slot)];
  }
  return null;
}

function guiImageSource(graph, node) {
  const imageInput = (node?.inputs || []).find(input => input?.name === "images");
  const linkId = imageInput?.link;
  if (linkId == null) return null;
  const row = normalizedLinkRows(graph).find(link => {
    if (Array.isArray(link)) return link[0] === linkId;
    return link?.id === linkId;
  });
  return linkSource(row);
}

function apiImageSource(node) {
  const source = node?.inputs?.images;
  if (Array.isArray(source) && source.length === 2
      && typeof source[0] === "string" && Number.isInteger(source[1])) {
    return [source[0], source[1]];
  }
  return null;
}

function isActive(node) {
  return ![2, 4].includes(Number(node?.mode ?? 0));
}

function sourceKey(source) {
  return source == null ? null : source[0] + ":" + source[1];
}

function pairSources(items, sourceReader) {
  const savesBySource = new Map();
  for (const item of items) {
    if (!isActive(item.node) || item.node.type !== "SaveImage"
        && item.node.class_type !== "SaveImage") continue;
    const key = sourceKey(sourceReader(item.node));
    if (!key) continue;
    const saves = savesBySource.get(key) || [];
    saves.push(String(item.id));
    savesBySource.set(key, saves);
  }
  const mapping = {};
  for (const item of items) {
    if (!isActive(item.node) || item.node.type !== "PreviewImage"
        && item.node.class_type !== "PreviewImage") continue;
    const key = sourceKey(sourceReader(item.node));
    const saves = (savesBySource.get(key) || []).sort((left, right) =>
      Number(left) - Number(right)
    );
    if (saves.length) mapping[String(item.id)] = saves[0];
  }
  return mapping;
}

export function derivePreviewSaveMappingFromGraph(graph) {
  return pairSources(
    (graph?.nodes || []).map(node => ({ id: node.id, node })),
    node => guiImageSource(graph, node),
  );
}

export function derivePreviewSaveMappingFromApi(apiGraph) {
  return pairSources(
    Object.entries(apiGraph || {}).map(([id, node]) => ({ id, node })),
    apiImageSource,
  );
}

export function mergeNodeOutput(rawOutputs, nodeId, output) {
  if (nodeId == null || !output || typeof output !== "object") return;
  const key = String(nodeId);
  const destination = rawOutputs[key] || (rawOutputs[key] = {});
  for (const [name, value] of Object.entries(output)) {
    if (name === "images" && Array.isArray(value)) {
      const images = destination.images || (destination.images = []);
      const seen = new Set(images.map(image =>
        `${image?.filename}:${image?.subfolder || ""}:${image?.type || ""}`
      ));
      for (const image of value) {
        const signature =
          `${image?.filename}:${image?.subfolder || ""}:${image?.type || ""}`;
        if (!seen.has(signature)) {
          images.push(cloneJson(image));
          seen.add(signature);
        }
      }
    } else {
      destination[name] = cloneJson(value);
    }
  }
}

export function mergeOutputs(rawOutputs, outputs) {
  for (const [nodeId, output] of Object.entries(outputs || {})) {
    mergeNodeOutput(rawOutputs, nodeId, output);
  }
}

function hasPersistentImage(output) {
  return Array.isArray(output?.images)
    && output.images.some(image => image?.type === "output");
}

export function refreshDisplayOutputs(rawOutputs, previewToSave) {
  const outputs = {};
  for (const [nodeId, output] of Object.entries(rawOutputs || {})) {
    outputs[nodeId] = cloneJson(output);
  }
  const active = [];
  for (const [previewNode, saveNode] of Object.entries(previewToSave || {})) {
    const saveOutput = rawOutputs?.[saveNode];
    const previewOutput = rawOutputs?.[previewNode];
    if (saveOutput && hasPersistentImage(saveOutput)) {
      outputs[previewNode] = cloneJson(saveOutput);
      active.push({
        preview_node: previewNode,
        save_node: saveNode,
        display_node: previewNode,
        descriptor_node: saveNode,
        descriptor_type: "output",
        preview_event_present: !!previewOutput,
      });
    } else if (previewOutput) {
      outputs[previewNode] = cloneJson(previewOutput);
      active.push({
        preview_node: previewNode,
        save_node: saveNode,
        display_node: previewNode,
        descriptor_node: previewNode,
        descriptor_type: "temporary-preview",
        preview_event_present: true,
      });
    }
  }
  return {
    outputs,
    display_provenance: {
      preview_to_save: { ...(previewToSave || {}) },
      active: active.sort((left, right) =>
        Number(left.preview_node) - Number(right.preview_node)
      ),
      rule: "Prefer persistent SaveImage output paired to the same graph image source.",
    },
  };
}

export function nodeTypesFromGraph(graph) {
  return Object.fromEntries((graph?.nodes || []).map(node => [
    String(node.id),
    node.type || node.comfyClass,
  ]));
}

export function createNativeUiJournal({
  graph,
  workflowKey,
  graphFingerprint,
  recipeFingerprint = null,
  promptId,
  clientId = null,
  startedAtMs = Date.now(),
  apiPromptFingerprint = null,
  nodeTypes = null,
  previewToSave = null,
}) {
  return {
    schema: NATIVE_UI_JOURNAL_SCHEMA,
    source: "comfyui-native-ui",
    workflow_key: workflowKey,
    graph_fingerprint: graphFingerprint,
    graph_fingerprint_version: GRAPH_FINGERPRINT_VERSION,
    recipe_fingerprint: recipeFingerprint,
    api_prompt_fingerprint: apiPromptFingerprint,
    prompt_id: promptId,
    client_id: clientId,
    status: "running",
    started_at_ms: startedAtMs,
    updated_at_ms: startedAtMs,
    node_types: nodeTypes || nodeTypesFromGraph(graph),
    preview_to_save: previewToSave || derivePreviewSaveMappingFromGraph(graph),
    raw_outputs: {},
    outputs: {},
    display_provenance: {},
    cached_nodes: [],
  };
}

export function timestampMs(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function runStartedMs(journal) {
  const direct = timestampMs(
    journal?.started_at_ms
    ?? journal?.run_started_at_ms
    ?? journal?.started_at_utc
    ?? journal?.created_at
  );
  if (direct != null) return direct;
  const messages = journal?.history_status?.messages;
  if (!Array.isArray(messages)) return null;
  const start = messages.find(item => item?.[0] === "execution_start");
  return timestampMs(start?.[1]?.timestamp);
}

export function shouldReplaceLocalLedger(existing, incoming) {
  if (!incoming?.prompt_id || !incoming?.graph_fingerprint) return false;
  if (!existing) return true;
  if (existing.prompt_id !== incoming.prompt_id) {
    return Number(runStartedMs(incoming) || 0)
      >= Number(runStartedMs(existing) || 0);
  }
  return Number(incoming.updated_at_ms || 0)
    >= Number(existing.updated_at_ms || 0);
}

export function usableJournal(journal, workflowKey, graphFingerprint) {
  return journal
    && typeof journal === "object"
    && validWorkflowIdentity(journal, workflowKey)
    && journal.graph_fingerprint === graphFingerprint
    && typeof journal.prompt_id === "string"
    && journal.prompt_id.length > 0
    && runStartedMs(journal) != null
    && journal.outputs
    && typeof journal.outputs === "object";
}

export function usableNativeJournalCandidate(journal, workflowKey, promptId = null) {
  return journal
    && typeof journal === "object"
    && journal.schema === NATIVE_UI_JOURNAL_SCHEMA
    && journal.source === "comfyui-native-ui"
    && journal.workflow_key === workflowKey
    && WORKFLOW_KEY_PATTERN.test(workflowKey || "")
    && FINGERPRINT_PATTERN.test(journal.graph_fingerprint || "")
    && (promptId == null || journal.prompt_id === promptId)
    && typeof journal.prompt_id === "string"
    && journal.prompt_id.length > 0
    && runStartedMs(journal) != null
    && journal.outputs
    && typeof journal.outputs === "object";
}

function successfulHistory(history) {
  return history?.status?.status_str === "success";
}

export async function migrateNativeJournal(
  journal,
  workflowKey,
  graphFingerprint,
  history,
  verifiedAtUtc = null,
) {
  if (usableJournal(journal, workflowKey, graphFingerprint)) return journal;
  if (!usableNativeJournalCandidate(journal, workflowKey)
      || !FINGERPRINT_PATTERN.test(graphFingerprint || "")
      || journal.status !== "completed"
      || !successfulHistory(history)
      || history?.status?.status_str === "error") return null;

  const historyPrompt = history.prompt;
  const apiPrompt = Array.isArray(historyPrompt) ? historyPrompt[2] : null;
  const submittedGraph = historyPrompt?.[3]?.extra_pnginfo?.workflow;
  if (!apiPrompt || !submittedGraph) return null;

  const historyApiPromptFingerprint = await sha256Hex(canonicalJson(apiPrompt));
  if (!FINGERPRINT_PATTERN.test(journal.api_prompt_fingerprint || "")
      || historyApiPromptFingerprint !== journal.api_prompt_fingerprint) {
    return null;
  }
  const historyWorkflowKey =
    submittedGraph?.extra?.newtecons_live?.workflow_key;
  if (historyWorkflowKey !== workflowKey
      || await graphCoreFingerprint(submittedGraph) !== graphFingerprint) {
    return null;
  }

  const migrated = cloneJson(journal);
  migrated.legacy_graph_fingerprint =
    journal.legacy_graph_fingerprint || journal.graph_fingerprint;
  migrated.graph_fingerprint = graphFingerprint;
  migrated.graph_fingerprint_version = GRAPH_FINGERPRINT_VERSION;
  migrated.graph_fingerprint_migration = {
    method: "history-ui-graph-and-api-prompt-v1",
    from_legacy: journal.graph_fingerprint,
    to_stable: graphFingerprint,
    history_api_prompt_fingerprint: historyApiPromptFingerprint,
    history_workflow_key: historyWorkflowKey,
    history_workflow_id:
      historyPrompt?.[3]?.workflow_metadata?.workflow_id || null,
    verified_at_utc: verifiedAtUtc,
  };
  return migrated;
}

export async function bindApiJournalToGraph(
  journal,
  workflowKey,
  recipeFingerprint,
  graphFingerprint,
  history,
  verifiedAtUtc = null,
) {
  if (!usableApiJournal(journal, workflowKey, recipeFingerprint)
      || !FINGERPRINT_PATTERN.test(graphFingerprint || "")) return null;
  if (!["completed", "success"].includes(journal.status)) return null;
  if (journal.graph_fingerprint) {
    return journal.graph_fingerprint === graphFingerprint ? journal : null;
  }
  if (!successfulHistory(history)) return null;

  const historyPrompt = history.prompt;
  const submittedGraph = historyPrompt?.[3]?.extra_pnginfo?.workflow;
  if (!submittedGraph) return null;
  const historyWorkflowKey =
    submittedGraph?.extra?.newtecons_live?.workflow_key;
  if (historyWorkflowKey !== workflowKey
      || await graphCoreFingerprint(submittedGraph) !== graphFingerprint) {
    return null;
  }

  let historyApiPromptFingerprint = null;
  if (journal.api_prompt_fingerprint) {
    const apiPrompt = Array.isArray(historyPrompt) ? historyPrompt[2] : null;
    if (!apiPrompt) return null;
    historyApiPromptFingerprint = await sha256Hex(canonicalJson(apiPrompt));
    if (historyApiPromptFingerprint !== journal.api_prompt_fingerprint) {
      return null;
    }
  }

  const bound = cloneJson(journal);
  bound.graph_fingerprint = graphFingerprint;
  bound.graph_fingerprint_version = GRAPH_FINGERPRINT_VERSION;
  bound.graph_binding = {
    method: journal.api_prompt_fingerprint
      ? "history-ui-graph-and-api-prompt-v1"
      : "history-ui-graph-and-recipe-v1",
    history_workflow_key: historyWorkflowKey,
    history_workflow_id:
      historyPrompt?.[3]?.workflow_metadata?.workflow_id || null,
    history_api_prompt_fingerprint: historyApiPromptFingerprint,
    verified_at_utc: verifiedAtUtc,
  };
  return bound;
}

export function usableApiJournal(
  journal,
  workflowKey,
  recipeFingerprint,
  graphFingerprint = null,
) {
  return journal
    && typeof journal === "object"
    && journal.workflow_key === workflowKey
    && WORKFLOW_KEY_PATTERN.test(workflowKey || "")
    && FINGERPRINT_PATTERN.test(recipeFingerprint || "")
    && journal.recipe_fingerprint === recipeFingerprint
    && typeof journal.prompt_id === "string"
    && journal.prompt_id.length > 0
    && journal.outputs
    && typeof journal.outputs === "object"
    && (!graphFingerprint || journal.graph_fingerprint === graphFingerprint);
}

export function chooseNewestJournal(
  apiJournal,
  nativeJournal,
  workflowKey,
  recipeFingerprint,
  graphFingerprint,
) {
  const api = usableApiJournal(
    apiJournal,
    workflowKey,
    recipeFingerprint,
    graphFingerprint,
  )
    ? apiJournal : null;
  const native = usableJournal(nativeJournal, workflowKey, graphFingerprint)
    ? nativeJournal : null;
  if (!native) return api;
  if (!api) return native;
  const apiStart = runStartedMs(api);
  const nativeStart = runStartedMs(native);
  if (apiStart != null && nativeStart != null && apiStart > nativeStart) {
    return api;
  }
  return native;
}

export function applyExecutionOutput(journal, nodeId, output) {
  if (!journal) return false;
  const before = JSON.stringify(journal.raw_outputs || {});
  journal.raw_outputs ||= {};
  mergeNodeOutput(journal.raw_outputs, nodeId, output);
  const next = refreshDisplayOutputs(
    journal.raw_outputs,
    journal.preview_to_save || {},
  );
  journal.outputs = next.outputs;
  journal.display_provenance = next.display_provenance;
  journal.updated_at_ms = Date.now();
  return before !== JSON.stringify(journal.raw_outputs);
}

export function applyHistoryOutputs(journal, historyOutputs) {
  if (!journal) return false;
  const before = JSON.stringify(journal.raw_outputs || {});
  journal.raw_outputs ||= {};
  mergeOutputs(journal.raw_outputs, historyOutputs);
  const next = refreshDisplayOutputs(
    journal.raw_outputs,
    journal.preview_to_save || {},
  );
  journal.outputs = next.outputs;
  journal.display_provenance = next.display_provenance;
  journal.updated_at_ms = Date.now();
  return before !== JSON.stringify(journal.raw_outputs);
}
