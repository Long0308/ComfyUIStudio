// Pure workflow identity. Domain evidence is ordered: extra domain fields, name prefix, folder.
export const NEWTECONS_DOMAIN = "newtecons_live_action";
export const JENNIEJOY_DOMAIN = "jenniejoy_cartoon_3d";
const DOMAIN_FIELD = /^(?:domain|domain_id|workflow_domain|production_domain|film_domain)$/iu;
const tidy = (value) => typeof value === "string" ? value.trim() : "";
const fold = (value) => tidy(value).normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/đ/gu, "d");

function canonicalDomain(value) {
  const v = fold(value).replace(/[\s-]+/gu, "_");
  if (/^(?:newtecons|newtecons_live_action)$/u.test(v)) return NEWTECONS_DOMAIN;
  if (/^(?:jenniejoy|jenniejoykids|jenniejoy_cartoon_3d)$/u.test(v)) return JENNIEJOY_DOMAIN;
  return v || null; // An explicit unfamiliar domain must not fall through to another film.
}

function extraDomain(extra) {
  const queue = [extra];
  const seen = new Set();
  while (queue.length) {
    const row = queue.shift();
    if (!row || typeof row !== "object" || Array.isArray(row) || seen.has(row)) continue;
    seen.add(row);
    for (const [key, value] of Object.entries(row)) {
      if (DOMAIN_FIELD.test(key) && tidy(value)) return canonicalDomain(value);
    }
    for (const value of Object.values(row)) {
      if (value && typeof value === "object" && !Array.isArray(value)) queue.push(value);
    }
  }
  return null;
}

function domainPrefix(name) {
  const value = fold(name);
  if (/^newtecons(?:\b|_)/u.test(value)) return NEWTECONS_DOMAIN;
  if (/^jenniejoy(?:kids)?(?:\b|_)/u.test(value)) return JENNIEJOY_DOMAIN;
  return null;
}

function names(extra, context) {
  const basename = tidy(context?.path).replace(/\\/gu, "/").split("/").at(-1);
  return [extra?.title, extra?.name, extra?.workflow_name, context?.name, basename].map(tidy).filter(Boolean);
}

function folders(context) {
  const path = tidy(context?.path).replace(/\\/gu, "/");
  // A filename is a name signal, not a folder signal.
  return [tidy(context?.folder), path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ""];
}

export function workflowDomain(extra, context = {}) {
  const explicit = extraDomain(extra);
  if (explicit) return explicit;
  for (const name of names(extra, context)) {
    const domain = domainPrefix(name);
    if (domain) return domain;
  }
  const folderNames = folders(context).flatMap((p) => p.replace(/\\/gu, "/").split("/")).reverse();
  for (const name of folderNames) {
    const domain = domainPrefix(name);
    if (domain) return domain;
    if (/^projectstudio\d*\s*-\s*film\s+newtecons\b/iu.test(name)) return NEWTECONS_DOMAIN;
  }
  return null;
}

function namedKind(value) {
  const name = fold(value);
  if (/(?:\b|_)(?:video|motion|h3|longtake)(?:\b|_)/u.test(name)) return "video";
  if (/(?:\b|_)(?:audio|voice|music)(?:\b|_)/u.test(name)) return "audio";
  if (/(?:\b|_)(?:image|anh)(?:\b|_)/u.test(name)) return "image";
  return null;
}

export function workflowMediaKind(extra, groups = [], context = {}) {
  const ex = extra && typeof extra === "object" ? extra : {};
  for (const value of [ex.flow, ex.newtecons_flow, ex.media_kind]) {
    if (["image", "video", "audio"].includes(value)) return value;
  }
  for (const name of names(ex, context)) {
    const kind = namedKind(name);
    if (kind) return kind;
  }
  for (const folder of folders(context).flatMap((p) => p.split(/[\\/]/u)).reverse()) {
    const kind = namedKind(folder);
    if (kind) return kind;
  }
  if ("newtecons_h3" in ex) return "video";
  if ("newtecons_image_8step" in ex) return "image";
  const titles = new Set((groups || []).map((g) => fold(g?.title).replace(/\s+/gu, " ")));
  if (["01 doc shotlist", "02 viet prompt", "03 ai quay video", "04 len 1080p", "05 luu & quay tiep"].every((t) => titles.has(t))) return "video";
  return "none";
}

// Current ComfyUI workflow manager; graph metadata remains usable for imported/unnamed graphs.
export function activeWorkflowContext(app) {
  const workflow = app?.extensionManager?.workflow?.activeWorkflow;
  const path = tidy(workflow?.path);
  const name = tidy(workflow?.fullFilename) || tidy(workflow?.filename) || path.replace(/\\/gu, "/").split("/").at(-1) || tidy(app?.graph?.extra?.title);
  return { name, path, folder: tidy(workflow?.directory) };
}

// Stable per-workflow key (path, else name). ComfyUI may reuse one app.graph object across workflow tabs,
// so per-workflow UI state must not be keyed by graph identity alone.
export function workflowKey(context) {
  return tidy(context?.path) || tidy(context?.name) || "(untitled)";
}
