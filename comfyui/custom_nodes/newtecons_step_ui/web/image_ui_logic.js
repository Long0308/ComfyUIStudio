import { workflowDomain, workflowMediaKind, NEWTECONS_DOMAIN } from "./workflow_context.js";
import { inputsForStep as stepSources } from "./step_ui_logic.js";

// Pure logic for the NEWTECONS IMAGE step panel (blue theme, layout step_dock.js). No DOM — tested with node.
// It never queues a prompt: settings go to graph.extra.newtecons_image_ui; route/wardrobe choices reuse the
// image lane's plan semantics (step_ui_logic.js planChanges) so both UIs change the graph identically.

export const EXTRA_KEY = "newtecons_image_ui";
export const STEP_TITLE = /^(\d{2})([A-Z]?)\s+(.+)$/u;
export const IMAGE_LABELS = ["CHỌN LUỒNG", "PROMPT", "NEO TRANG PHỤC", "THAM CHIẾU NHÂN VẬT", "THAM CHIẾU FACE/POSE", "ASSET 4 GÓC",
  "3D", "SET 3D 3×3", "CONTROLNET", "KHOÁ ASSET", "9 ẢNH", "SỬA GÓC", "DUYỆT & UPSCALE"];
export const IMAGE_SOURCES = new Set(["LoadImage", "LoadImageMask", "LoadImageOutput"]);
export const TEXT_NODES = new Set(["PrimitiveStringMultiline", "PrimitiveString", "CLIPTextEncode"]);
export const OUTPUT_TYPES = new Set(["SaveImage", "PreviewImage", "SaveVideo", "SaveAnimatedWEBP", "SaveAnimatedPNG"]);
export const CONTEXT_LABEL = { cong_truong: "CÔNG TRƯỜNG", van_phong: "VĂN PHÒNG" };
// Root 31/10: van_phong_suit leaks a CHAR_04 face (critic) and is being removed from the presets — never offered,
// even while the key still exists in data or in the workflow's route plan.
export const BLOCKED_CONTEXTS = new Set(["van_phong_suit"]);
// Which route-plan dimensions belong to which step (by step label, so codes can move between versions).
export const STEP_DIMENSIONS = {
  "CHỌN LUỒNG": ["route"],
  "NEO TRANG PHỤC": ["wardrobe", "upload", "boicanh"],
  "THAM CHIẾU NHÂN VẬT": ["character", "mau_moi"],
  "THAM CHIẾU FACE/POSE": ["character", "mau_moi"],
  "SỬA GÓC": ["fix08"],
  "DUYỆT & UPSCALE": ["source09", "target09"],
};
export const DIMENSION_LABEL = { route: "LUỒNG", wardrobe: "BỐI CẢNH", upload: "UPLOAD", boicanh: "BỐI CẢNH THAM CHIẾU",
  character: "NHÂN VẬT", mau_moi: "MẪU TẠO NHÂN VẬT MỚI", fix08: "SỬA GÓC", source09: "NGUỒN", target09: "ĐÍCH" };
export const ROUTES = [
  { value: "local", label: "LOCAL — ComfyUI RTX 5080" },
  { value: "codex", label: "CODEX — ngoài ComfyUI qua jjv" },
];
export const CHAR_IDS = Array.from({ length: 8 }, (_, i) => `CHAR_0${i + 1}`);
export const COUNT_RANGE = [1, 10];
export const MISSING = "chưa có";
const VIDEO_TITLES = ["01 ĐỌC SHOTLIST", "02 VIẾT PROMPT", "03 AI QUAY VIDEO", "04 LÊN 1080P", "05 LƯU & QUAY TIẾP"];

function norm(t) {
  return String(t || "").trim().replace(/\s+/gu, " ");
}

export function parseSteps(groups) {
  const steps = [];
  for (const g of groups || []) {
    const m = STEP_TITLE.exec(norm(g.title));
    if (!m || !Array.isArray(g.bounding) || g.bounding.length < 4) continue;
    steps.push({ code: m[1] + m[2], num: Number(m[1]), suffix: m[2], label: m[3], title: norm(g.title),
      bounding: g.bounding.slice(0, 4).map(Number) });
  }
  // Graph order = how the builder laid the groups out (left -> right, then top -> bottom); ties by code.
  steps.sort((a, b) => a.bounding[0] - b.bounding[0] || a.bounding[1] - b.bounding[1] || a.code.localeCompare(b.code));
  return steps;
}

export function isVideoGraph(extra, groups, context = {}) {
  return workflowMediaKind(extra, groups, context) === "video";
}

// Explicit workflow identity overrides panel settings left over from another film.
export function isImageFlow(extra, groups, context = {}) {
  if (extra?.newtecons?.export_gui_version === 1) return false;
  // Whitelist: only a detected NEWTECONS domain may show the bar. Unknown (null) and other domains hide it.
  const domain = workflowDomain(extra, context);
  if (domain !== NEWTECONS_DOMAIN) return false;
  const kind = workflowMediaKind(extra, groups, context);
  if (kind !== "none") return kind === "image";
  return parseSteps(groups).filter((s) => IMAGE_LABELS.includes(s.label)).length >= 3;
}

export function inBounds(pos, b) {
  return Array.isArray(pos) && pos[0] >= b[0] && pos[0] < b[0] + b[2] && pos[1] >= b[1] && pos[1] < b[1] + b[3];
}

export function nodesInStep(nodes, step) {
  return (nodes || []).filter((n) => inBounds(n.pos, step.bounding));
}

// "a/b/c.png [input]" -> {filename:"c.png", subfolder:"a/b", type:"input"}
export function splitAnnotated(value, defaultType = "input") {
  let name = String(value || "").trim();
  let type = defaultType;
  const m = /\s*\[(input|output|temp)\]$/u.exec(name);
  if (m) { type = m[1]; name = name.slice(0, m.index); }
  const cut = name.lastIndexOf("/");
  return { filename: cut < 0 ? name : name.slice(cut + 1), subfolder: cut < 0 ? "" : name.slice(0, cut), type };
}

export function viewPath(ref) {
  const q = new URLSearchParams({ filename: ref.filename, subfolder: ref.subfolder || "", type: ref.type || "output" });
  return "/view?" + q.toString();
}

// VÀO of a step: the LoadImage files actually set in the group + non-empty prompt texts.
export function stepInputs(graph, step) {
  const members = nodesInStep(graph.nodes, step);
  const images = stepSources(graph, step, parseSteps(graph.groups)).filter((source) => source.kind === "image");
  const prompts = members.filter((n) => TEXT_NODES.has(n.type)).map((n) => ({
    nodeId: n.id, title: n.title || n.type, mode: n.mode || 0, text: String(n.widgets?.value ?? n.widgets?.text ?? "").trim(),
  })).filter((p) => p.text);
  return { images, prompts, nodes: members.length, muted: members.filter((n) => n.mode === 2 || n.mode === 4).length };
}

export function outputNodesForStep(graph, step) {
  return nodesInStep(graph.nodes, step).filter((n) => OUTPUT_TYPES.has(n.type)).map((n) => ({
    nodeId: n.id, type: n.type, title: n.title || n.type, mode: n.mode || 0,
    prefix: n.widgets && "filename_prefix" in n.widgets ? n.widgets.filename_prefix : null,
  }));
}

export function groupSignature(groups) {
  return (groups || []).map((g) => norm(g.title)).filter((t) => STEP_TITLE.test(t)).sort().join("|");
}

function mediaOf(out) {
  const lists = [out.images, out.gifs, out.videos, out.video].filter(Array.isArray);
  return lists.flat().filter((m) => m && m.filename).map((m) => ({ filename: m.filename, subfolder: m.subfolder || "", type: m.type || "output" }));
}

function entryOrder(entry) {
  const p = entry && entry.prompt;
  return Array.isArray(p) && Number.isFinite(p[0]) ? p[0] : -1;
}

// RA from GET /history (same matching rule as the image lane's step UI): strong = same workflow (group titles)
// + node id + class (+ prefix); weak = node id + class + filename_prefix. PreviewImage only matches strongly.
export function latestOutput(history, outputs, signature) {
  const entries = Object.entries(history || {}).map(([id, e]) => ({ id, e })).sort((a, b) => entryOrder(b.e) - entryOrder(a.e));
  let weak = null;
  for (const { id, e } of entries) {
    const apiGraph = Array.isArray(e.prompt) ? e.prompt[2] || {} : {};
    const wf = Array.isArray(e.prompt) ? e.prompt[3]?.extra_pnginfo?.workflow : null;
    const same = Boolean(wf && signature && groupSignature(wf.groups) === signature);
    for (const o of outputs) {
      const out = e.outputs?.[String(o.nodeId)];
      const media = out ? mediaOf(out) : [];
      const call = apiGraph[String(o.nodeId)];
      if (!media.length || !call || call.class_type !== o.type) continue;
      if (o.prefix != null && call.inputs?.filename_prefix !== o.prefix) continue;
      const hit = { promptId: id, nodeId: o.nodeId, nodeTitle: o.title, media, order: entryOrder(e) };
      if (same) return { ...hit, match: "strong" };
      if (!weak && o.prefix != null) weak = { ...hit, match: "weak" };
    }
  }
  return weak;
}

// ---- Chỉ mục ảnh trên đĩa (data/image/results-index.json, jjv/image-results-index/v1) ----
// /history chỉ giữ ~200 job và render của engine/worker dùng prefix riêng (s02a-shirt-v001/…) nên không bao giờ khớp
// prefix của graph. Chỉ mục do tools/build_step_ui_index.py quét output/NEWTECONS; UI chỉ ĐỌC, không ghi.
export const INDEX_SCHEMA = "jjv/image-results-index/v1";

function prefixRegex(base) {
  const esc = base.split("XX").map((p) => p.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")).join("[A-Za-z0-9]+");
  // Quy ước prefix bước 07: POSEp_GOCg (p = số pose, g = số góc) cũng là ô điền.
  const slots = esc.replace("POSEp", "POSE[A-Za-z0-9]+").replace("GOCg", "GOC[A-Za-z0-9]+");
  return new RegExp("^" + slots + "(?:_|\\.|$)", "u");
}

export function indexOutput(index, outputs) {
  if (!index || index.schema !== INDEX_SCHEMA || !index.folders) return null;
  for (const o of outputs || []) {
    if (!o.prefix || typeof o.prefix !== "string") continue;
    const cut = o.prefix.lastIndexOf("/");
    const folder = cut < 0 ? "" : o.prefix.slice(0, cut);
    const re = prefixRegex(cut < 0 ? o.prefix : o.prefix.slice(cut + 1));
    const files = (index.folders[folder]?.files || []).filter((f) => re.test(f.name)).sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
    if (files.length) return { promptId: "đĩa", nodeId: o.nodeId, nodeTitle: o.title, match: "disk", order: files[0].mtime || 0,
      media: files.map((f) => ({ filename: f.name, subfolder: folder, type: "output" })) };
  }
  return null;
}

// Lý do trống, nói đúng: đã tìm ở đâu và bước này chưa chạy.
export function emptyOutputText(index, outputs, historyItems) {
  const prefixes = (outputs || []).map((o) => o.prefix).filter(Boolean);
  const want = prefixes.length ? prefixes.map((p) => `"${p}*"`).join(" · ") : "(node không có filename_prefix)";
  if (!index || index.schema !== INDEX_SCHEMA) return `Chưa có ảnh RA: không có trong ${historyItems} lượt /history và chưa có chỉ mục đĩa (data/image/results-index.json) — chạy tools/build_step_ui_index.py. Prefix cần: ${want}.`;
  return `Bước này chưa chạy: không có ảnh nào khớp ${want} trên đĩa (quét ${Object.keys(index.folders || {}).length} thư mục NEWTECONS lúc ${index.generated_at || "?"}) và không có trong ${historyItems} lượt /history. Chạy bước này trong ComfyUI (Run) rồi bấm lại tab.`;
}

// data/characters/newtecons_live_action.json (jjv/character-refs/v1): characters = {CHAR_0N: {name, face:[{file}], ...}}.
export function parseCharacters(raw) {
  const errors = [];
  if (!raw || typeof raw !== "object") return { ok: false, errors: ["không có dữ liệu nhân vật"], list: CHAR_IDS.map((id) => ({ id, name: null, refs: [] })) };
  if (raw.schema !== "jjv/character-refs/v1") errors.push(`schema nhân vật = ${JSON.stringify(raw.schema ?? null)}`);
  const src = raw.characters || {};
  const entries = Array.isArray(src) ? src.map((c) => [c?.id, c]) : Object.entries(src);
  const list = entries.filter(([id]) => typeof id === "string" && /^CHAR_\d{2}$/u.test(id)).map(([id, c]) => {
    const refs = Object.entries(c || {}).filter(([, v]) => Array.isArray(v)).flatMap(([kind, rows]) => rows
      .filter((r) => typeof r?.file === "string" && r.file && !r.file.includes(".."))
      .map((r) => ({ kind, name: r.name || r.file, ref: splitAnnotated(r.file), sha256: r.sha256 || null, qa: r.qa ?? null })));
    return { id, name: typeof c?.name === "string" ? c.name : null, refs };
  }).sort((a, b) => a.id.localeCompare(b.id));
  return { ok: errors.length === 0 && list.length > 0, errors, list };
}

// data/wardrobe/newtecons_live_action.json (jjv/wardrobe-presets/v1): contexts.<ctx> = [{name, file, sha256, role}].
export function parseWardrobe(raw) {
  if (!raw || typeof raw !== "object" || !raw.contexts) return { ok: false, contexts: [], def: null };
  const contexts = Object.entries(raw.contexts).filter(([key]) => !BLOCKED_CONTEXTS.has(key)).map(([key, rows]) => ({
    key, label: CONTEXT_LABEL[key] || key.toUpperCase(),
    files: (Array.isArray(rows) ? rows : []).filter((r) => typeof r?.file === "string" && !r.file.includes(".."))
      .map((r) => ({ name: r.name || r.file, ref: splitAnnotated(r.file), role: r.role || null, sha256: r.sha256 || null })),
  }));
  return { ok: raw.schema === "jjv/wardrobe-presets/v1", contexts, def: contexts.some((c) => c.key === raw.default_context) ? raw.default_context : contexts[0]?.key || null };
}

// Options of one plan dimension for the UI (blocked wardrobe contexts removed). [] when the plan lacks it.
export function planOptions(plan, dimension) {
  const opts = plan?.[dimension]?.options;
  if (!opts) return [];
  return Object.entries(opts).filter(([k]) => !(dimension === "wardrobe" && BLOCKED_CONTEXTS.has(k)))
    .map(([value, o]) => ({ value, label: o?.label || CONTEXT_LABEL[value] || value, prefix: o?.prefix || null }));
}

export function stepDimensions(step, plan) {
  return (STEP_DIMENSIONS[step?.label] || []).filter((d) => planOptions(plan, d).length);
}

// Prompt-list widget target: the PrimitiveStringMultiline inside the PROMPT step (same rule as the lane UI).
export function promptNodeId(graph, steps) {
  const s = (steps || []).find((x) => x.label === "PROMPT");
  const n = s && (graph?.nodes || []).find((x) => x.type === "PrimitiveStringMultiline" && inBounds(x.pos, s.bounding));
  return n ? n.id : null;
}

export function defaultImageSettings(extra, chars, wardrobe) {
  const s = extra?.[EXTRA_KEY] || {};
  const ids = (chars?.list || []).map((c) => c.id);
  const ctxs = (wardrobe?.contexts || []).map((c) => c.key);
  const routeNow = typeof extra?.newtecons_route === "string" ? extra.newtecons_route : null;
  return {
    char: ids.includes(s.char) ? s.char : ids[0] || "",
    context: ctxs.includes(s.context) ? s.context : wardrobe?.def || "",
    route: ROUTES.some((r) => r.value === routeNow) ? routeNow : ROUTES.some((r) => r.value === s.route) ? s.route : "local",
    count: Number.isInteger(s.count) && s.count >= COUNT_RANGE[0] && s.count <= COUNT_RANGE[1] ? s.count : null,
    wardrobe_upload: typeof s.wardrobe_upload === "string" ? s.wardrobe_upload : "",
    scene_upload: typeof s.scene_upload === "string" ? s.scene_upload : "",
  };
}

export function validateImageSettings(s, chars, wardrobe) {
  const errors = [];
  if (!s.char || !(chars?.list || []).some((c) => c.id === s.char)) errors.push("Chưa chọn nhân vật");
  if (wardrobe?.contexts?.length && !wardrobe.contexts.some((c) => c.key === s.context)) errors.push("Bối cảnh không có trong bộ trang phục");
  if (!ROUTES.some((r) => r.value === s.route)) errors.push("Luồng phải là LOCAL hoặc CODEX");
  if (s.count != null && !(Number.isInteger(s.count) && s.count >= COUNT_RANGE[0] && s.count <= COUNT_RANGE[1])) errors.push("Số ảnh N phải là 1..10");
  return {
    ok: errors.length === 0, errors,
    value: { schema: "jjv/image-ui-settings/v1", domain: "newtecons_live_action", char: s.char || null, context: s.context || null,
      route: s.route, count: s.count ?? null, wardrobe_upload: s.wardrobe_upload || null, scene_upload: s.scene_upload || null,
      submits_gpu: false },
  };
}

// Where an uploaded file goes: a LoadImage listed in extra.newtecons_wardrobe (optional slots) whose title says
// UPLOAD/TẢI LÊN (wardrobe) or BỐI CẢNH (scene); else any LoadImage titled that way. null = extra only.
export function uploadTarget(graph, kind) {
  const re = kind === "scene" ? /BỐI\s*CẢNH|scene|background/iu : /UPLOAD|TẢI\s*LÊN|TRANG\s*PHỤC\s*CÔNG\s*TY/iu;
  const ids = new Set((graph?.extra?.newtecons_wardrobe?.optional || []).map(String));
  const loads = (graph?.nodes || []).filter((n) => IMAGE_SOURCES.has(n.type) && re.test(String(n.title || "")));
  return loads.find((n) => ids.has(String(n.id))) || loads[0] || null;
}

export function uploadName(file, char, kind) {
  const ext = (/\.(png|jpe?g|webp)$/iu.exec(file?.name || "") || [".png"])[0].toLowerCase();
  const stamp = new Date().toISOString().replace(/[-:T]/gu, "").slice(0, 14);
  return `${kind}_${char || "CHAR_XX"}_${stamp}${ext}`;
}

export function acceptsUpload(file) {
  return Boolean(file) && /^image\/(png|jpeg|webp)$/u.test(file.type || "") && file.size > 0 && file.size <= 25 * 1024 * 1024;
}
