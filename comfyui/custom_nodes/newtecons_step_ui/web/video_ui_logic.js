import { workflowDomain, workflowMediaKind, NEWTECONS_DOMAIN } from "./workflow_context.js";

// Pure logic for the NEWTECONS VIDEO step panel (no DOM, no ComfyUI imports) — tested with node.
// Read-only toward the GPU: it never queues a prompt. Settings only go to graph.extra / a job widget.

export const SCHEMA = "jjv/video-ui-state/v1";
export const EXTRA_KEY = "newtecons_video_ui";
export const BASE_URL = "/extensions/newtecons_step_ui/";
export const DATA_DIR = BASE_URL + "data/video/";
export const STATUSES = ["planned", "prompted", "rendered", "upscaled_1080", "accepted"];
export const STATUS_LABEL = {
  planned: "Đã lên shot", prompted: "Đã có prompt", rendered: "Đã quay (native)",
  upscaled_1080: "Đã lên 1080p", accepted: "Đã duyệt",
};
export const MISSING = "chưa có";
export const VIDEO_STEPS = [
  { code: "01", label: "ĐỌC SHOTLIST" },
  { code: "02", label: "VIẾT PROMPT" },
  { code: "03", label: "AI QUAY VIDEO" },
  { code: "04", label: "LÊN 1080P" },
  { code: "05", label: "LƯU & QUAY TIẾP" },
];
export const RUN_MODES = [
  { value: "auto_pending", label: "Tự động: shot chưa có video" },
  { value: "selected_only", label: "Chỉ shot đang chọn" },
];
// User gates of `jjv video run` (engine/video/run.py USER_GATES), shown in Vietnamese.
export const GATE_LABEL = {
  "gpu-approval": "Chờ user duyệt chạy GPU",
  "needs-gpu-pilot-approval": "Chờ user duyệt pilot GPU (chưa nghiệm thu)",
  "take-acceptance": "Chờ duyệt take của shot",
  "review-pending": "Chờ duyệt cuối lượt",
  "final-review": "Chờ duyệt bản ghép cuối",
  blocked_technical: "Kẹt kỹ thuật",
};
export const SEED_MODES = [
  { value: "fixed", label: "Cố định" },
  { value: "randomize", label: "Ngẫu nhiên mỗi shot" },
];
// Style lists per domain. NEWTECONS = live-action only; cartoon is never offered there.
export const DOMAIN_STYLES = {
  newtecons_live_action: [
    { value: "live_action_photoreal", label: "Live-action người thật (photoreal)" },
  ],
  jenniejoy_cartoon_3d: [
    { value: "cartoon_3d", label: "3D cartoon JennieJoy" },
  ],
};
const CARTOON = /cartoon|hoạt\s*hình|anime|toon|chibi/iu;
const LIVE = /live[\s_-]*action|photo[\s_-]*real|người\s*thật|realistic|chân\s*thực/iu;
const EPISODE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/u;
const SAFE_URL = /^(\/(?!\/)|https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/)/iu;

export const INDEX_URL = DATA_DIR + "index.json";
export const INDEX_SCHEMA = "jjv/video-ui-index/v1";
export const DOMAIN_LABEL = {
  newtecons_live_action: "NEWTECONS · live-action",
  jenniejoy_cartoon_3d: "JennieJoyKids · 3D cartoon",
};

// Active when the graph declares the video flow (extra.flow or extra.newtecons_flow) or when it
// carries all five video step groups (01 ĐỌC SHOTLIST … 05 LƯU & QUAY TIẾP).
export function isVideoFlow(extra, groups, context = {}) {
  if (extra?.newtecons?.export_gui_version === 1) return false;
  // Whitelist: only a detected NEWTECONS domain may show the bar. Unknown (null) and other domains hide it.
  const domain = workflowDomain(extra, context);
  if (domain !== NEWTECONS_DOMAIN) return false;
  // Legacy grouped H3 stays on its existing bar; new named video graphs include LongTake exports.
  const kind = workflowMediaKind(extra, groups, context);
  return kind === "video" && !(extra?.newtecons_h3 && !extra?.flow && !extra?.newtecons_flow && !hasVideoGroups(groups)
    && !extra?.title && !context.name && !context.path);
}

export function hasVideoGroups(groups) {
  const titles = new Set((groups || []).map((g) => String(g?.title || "").trim().replace(/\s+/gu, " ")));
  return VIDEO_STEPS.every((s) => titles.has(`${s.code} ${s.label}`));
}

export function domainLabel(domain) {
  return DOMAIN_LABEL[domain] || (domain ? `domain ${domain}` : "domain chưa có");
}

// data/video/index.json — written next to the per-episode files (the browser cannot list a folder).
// {schema, episodes:[{episode, domain, file?, label?}]}. Entries with bad ids are dropped, not fixed.
export function normalizeIndex(raw) {
  const errors = [];
  if (!raw || typeof raw !== "object") return { ok: false, errors: ["index không phải JSON object"], episodes: [] };
  if (raw.schema !== INDEX_SCHEMA) errors.push(`index schema = ${JSON.stringify(raw.schema ?? null)}, cần ${INDEX_SCHEMA}`);
  const episodes = [];
  for (const [i, e] of (Array.isArray(raw.episodes) ? raw.episodes : []).entries()) {
    const ep = typeof e === "string" ? e : e?.episode;
    if (!episodeOk(ep)) { errors.push(`episodes[${i}] id không hợp lệ`); continue; }
    const file = typeof e?.file === "string" && /^[A-Za-z0-9._-]+\.json$/u.test(e.file) ? e.file : `${ep}.json`;
    episodes.push({ episode: ep, domain: typeof e?.domain === "string" ? e.domain : null, label: text(e?.label),
      url: DATA_DIR + encodeURIComponent(file) });
  }
  return { ok: raw.schema === INDEX_SCHEMA && Array.isArray(raw.episodes), errors, episodes };
}

export function statusRank(status) {
  return STATUSES.indexOf(status);
}

export function isAtLeast(status, target) {
  const r = statusRank(status);
  return r >= 0 && r >= statusRank(target);
}

// Only served same-origin paths (or localhost) survive; anything else becomes null ("chưa có").
// Relative names resolve against the extension folder.
export function safeUrl(url) {
  if (typeof url !== "string") return null;
  const u = url.trim();
  if (!u) return null;
  if (SAFE_URL.test(u)) return u;
  if (/^[a-z][a-z0-9+.-]*:/iu.test(u) || u.startsWith("//") || u.includes("..")) return null;
  return BASE_URL + u.replace(/^\.\//u, "");
}

function num(v) {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

function size(v) {
  const w = num(v?.w);
  const h = num(v?.h);
  return w && h && w > 0 && h > 0 ? { w, h } : null;
}

function text(v) {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function normShot(raw, i, errors) {
  const id = text(raw?.id);
  if (!id) errors.push(`shots[${i}] thiếu id`);
  const st = raw?.status;
  let status = null;
  let statusRaw = null;
  if (st == null || st === "") status = null;
  else if (STATUSES.includes(st)) status = st;
  else { statusRaw = String(st); errors.push(`shots[${i}] status lạ: ${statusRaw}`); }
  const all = (Array.isArray(raw?.refs) ? raw.refs : []).map((r, k) => ({
    name: text(r?.name) || `ref ${k + 1}`, url: safeUrl(r?.url),
  }));
  // Old pilot inputs (template "ĐIỀN: …" slots, h3-<sha> uploads) are never shot references; they join legacy_refs
  // and are shown only as a struck-out note, with no renderable url.
  const refs = all.filter((r) => !isLegacyRef(r));
  const legacy = [...all.filter(isLegacyRef), ...(Array.isArray(raw?.legacy_refs) ? raw.legacy_refs : [])]
    .map((r, k) => ({ name: text(typeof r === "string" ? r : r?.name) || `ảnh cũ ${k + 1}`, url: null }));
  return {
    legacy, anchor: normAnchor(raw?.anchor_pack),
    wardrobe: normWardrobe(raw?.wardrobe),
    id: id || `#${i + 1}`, scene: text(raw?.scene), size: text(raw?.size), angle: text(raw?.angle),
    move: text(raw?.move), seconds: num(raw?.seconds), refs, prompt: text(raw?.prompt), status, statusRaw,
    pipeline: raw?.pipeline && Array.isArray(raw.pipeline.stages) ? raw.pipeline : null,
    native_url: safeUrl(raw?.native_url), hd_url: safeUrl(raw?.hd_url), thumb_url: safeUrl(raw?.thumb_url),
  };
}

const LEGACY_NAME = /^\s*ĐIỀN\s*:/iu;
const H3_FILE = /^h3-/iu;

function fileOf(url) {
  if (typeof url !== "string") return "";
  const m = /[?&]filename=([^&]*)/u.exec(url);
  try { return m ? decodeURIComponent(m[1].replace(/\+/gu, " ")) : url.split(/[?#]/u)[0].split("/").pop(); } catch { return m ? m[1] : ""; }
}

export function isLegacyRef(r) {
  const name = String(r?.name ?? "");
  return LEGACY_NAME.test(name) || H3_FILE.test(name) || H3_FILE.test(fileOf(r?.url));
}

export function legacyNote(shot) {
  const n = shot?.legacy?.length || 0;
  return n ? `ảnh cũ chưa duyệt — không dùng (${n})` : null;
}

const SAFE_SEG = /^[A-Za-z0-9._ -]+$/u;
const SHA_HEX = /^[0-9a-f]{64}$/u;

// anchor_pack.staged: [{slot, role, input_subfolder, filename, sha256}] — files under ComfyUI input/. Only these
// entries may ever fill the graph's anchor LoadImage nodes; unsafe paths, bad sha and legacy names are rejected.
function normStaged(rows) {
  const ok = [];
  let rejected = 0;
  for (const r of Array.isArray(rows) ? rows : []) {
    const slot = text(r?.slot);
    const filename = text(r?.filename);
    const sub = typeof r?.input_subfolder === "string" ? r.input_subfolder.trim().replace(/^\/+|\/+$/gu, "") : "";
    const segs = sub ? sub.split("/") : [];
    const safe = filename && SAFE_SEG.test(filename) && segs.every((s) => s && s !== "." && s !== ".." && SAFE_SEG.test(s));
    const sha = String(r?.sha256 || "").toLowerCase();
    if (!slot || !safe || !SHA_HEX.test(sha) || isLegacyRef({ name: filename })) { rejected += 1; continue; }
    ok.push({ slot, role: text(r?.role), filename, subfolder: sub, sha256: sha,
      value: sub ? `${sub}/${filename}` : filename, ref: { filename, subfolder: sub, type: "input" } });
  }
  return { staged: ok, rejected };
}

function normAnchor(a) {
  if (!a || typeof a !== "object") return null;
  const st = normStaged(a.staged);
  return { status: text(a.status), context: text(a.context), ready: a.ready_for_graph === true, staged: st.staged, stagedRejected: st.rejected };
}

export const ANCHOR_STATUS_LABEL = { loaded: "đã nạp", missing_file: "thiếu file", sha_mismatch: "sha lệch", unchecked: "chưa kiểm",
  empty: "trống — giữ tắt", needs_root: "cần file ở gốc input/" };
export const MUTED = 2;

export function anchorStatusLabel(status) {
  return ANCHOR_STATUS_LABEL[status] || status;
}

// Graph nodes with properties.nt_anchor_slot -> what loading the staged pack would do. checks[value] = {exists, sha256}
// from GET /view + SHA-256 in the browser. A slot is filled (value set, unmuted) ONLY when its file exists and the sha
// matches; empty / missing / mismatching slots are muted with no value. Pure: returns rows, never edits nodes.
export function anchorPlan(nodes, staged, checks = {}) {
  const bySlot = new Map((staged || []).map((e) => [e.slot, e]));
  const anchorNodes = (nodes || []).filter((n) => typeof n?.properties?.nt_anchor_slot === "string" && n.properties.nt_anchor_slot);
  const rows = anchorNodes.map((n) => {
    const slot = n.properties.nt_anchor_slot;
    const entry = bySlot.get(slot) || null;
    let status = "empty";
    if (entry && entry.subfolder) {
      // Measured 31/10 (ComfyUI 1.55): "sub/file.png" previews, but the frontend marks the LoadImage node Error
      // ("Media input missing"). Only files at the input/ root are filled — the engine must stage them there.
      status = "needs_root";
    } else if (entry) {
      const c = checks[entry.value];
      status = !c ? "unchecked" : !c.exists ? "missing_file" : String(c.sha256 || "").toLowerCase() !== entry.sha256 ? "sha_mismatch" : "loaded";
    }
    const loaded = status === "loaded";
    return { nodeId: n.id, slot, title: n.title || n.type, entry, status, value: loaded ? entry.value : null,
      mode: loaded ? 0 : MUTED, current: String(n.widgets?.image ?? ""), currentMode: n.mode || 0 };
  });
  const used = new Set(anchorNodes.map((n) => n.properties.nt_anchor_slot));
  const orphans = (staged || []).filter((e) => !used.has(e.slot));
  const withEntry = rows.filter((r) => r.entry);
  const loaded = rows.filter((r) => r.status === "loaded");
  // applied = every verified slot already holds its staged file and is live in the graph.
  return { rows, orphans, ready: withEntry.length > 0 && withEntry.every((r) => r.status === "loaded"),
    applied: loaded.length > 0 && loaded.every((r) => r.current === r.value && r.currentMode === 0) };
}

// "BỘ NEO: candidate (chưa duyệt) · CÔNG TRƯỜNG · chưa sẵn sàng cho graph" — null when the shot has no anchor pack.
export function anchorText(shot) {
  const a = shot?.anchor;
  if (!a) return null;
  const status = a.status ? (a.status === "approved" ? "approved" : `${a.status} (chưa duyệt)`) : MISSING;
  const ctx = a.context ? WARDROBE_LABEL[a.context] || a.context : MISSING;
  return `BỘ NEO: ${status} · ${ctx} · ${a.ready ? "sẵn sàng cho graph" : "chưa sẵn sàng cho graph"}`;
}

// Per-shot wardrobe from the engine data (context chosen from the shotlist, or refused with a reason).
export const WARDROBE_LABEL = { cong_truong: "CÔNG TRƯỜNG", van_phong: "VĂN PHÒNG", van_phong_suit: "VĂN PHÒNG · VEST" };

function normWardrobe(w) {
  if (!w || typeof w !== "object") return null;
  const refused = typeof w.refused === "string" && w.refused.trim() ? w.refused.trim() : w.refused === true ? "refused" : null;
  return {
    context: text(w.context), refused,
    code: refused ? refused.split(":")[0].trim() : null,
    refs: (Array.isArray(w.refs) ? w.refs : []).map((r, k) => ({ name: text(r?.name) || `ref ${k + 1}`, url: safeUrl(typeof r === "string" ? r : r?.url) })),
  };
}

// One line for the shot card / table: "CÔNG TRƯỜNG · 3 ref", "TỪ CHỐI (WARDROBE_CONTEXT_UNKNOWN)", or "chưa có".
export function wardrobeText(shot) {
  const w = shot?.wardrobe;
  if (!w) return MISSING;
  if (w.refused) return `TỪ CHỐI (${w.code})`;
  if (!w.context) return MISSING;
  return `${WARDROBE_LABEL[w.context] || w.context}${w.refs.length ? ` · ${w.refs.length} ref` : ""}`;
}

// Validates a jjv/video-ui-state/v1 payload. Never invents a status: unknown -> statusRaw + error.
export function normalizeState(raw, source = "data") {
  const errors = [];
  if (!raw || typeof raw !== "object") return { ok: false, errors: ["không phải JSON object"], shots: [], source };
  if (raw.schema !== SCHEMA) errors.push(`schema = ${JSON.stringify(raw.schema ?? null)}, cần ${SCHEMA}`);
  const shots = (Array.isArray(raw.shots) ? raw.shots : []).map((s, i) => normShot(s, i, errors));
  if (!Array.isArray(raw.shots)) errors.push("thiếu mảng shots");
  const ids = new Set();
  for (const s of shots) { if (ids.has(s.id)) errors.push(`shot trùng id ${s.id}`); ids.add(s.id); }
  return {
    ok: raw.schema === SCHEMA && Array.isArray(raw.shots), errors, source, sample: Boolean(raw.sample),
    sampleNote: text(raw.sample_note), episode: text(raw.episode), domain: text(raw.domain), fps: num(raw.fps),
    native: size(raw.native), export: size(raw.export), styles: Array.isArray(raw.styles) ? raw.styles : null,
    seed: seedOk(raw.seed) ? raw.seed : null, gate: normGate(raw.gate, errors), shots,
  };
}

// Optional engine gate {name, message?, pending?[]}; unknown gate names are reported, not relabelled.
function normGate(g, errors) {
  if (g == null) return null;
  const name = typeof g === "string" ? g : g?.name;
  if (typeof name !== "string" || !name) { errors.push("gate không có name"); return null; }
  if (!GATE_LABEL[name]) errors.push(`gate lạ: ${name}`);
  return { name, label: GATE_LABEL[name] || `không rõ (${name})`, message: text(g?.message),
    pending: Array.isArray(g?.pending) ? g.pending.filter((x) => typeof x === "string") : [] };
}

export function formatSeconds(s) {
  if (s == null) return MISSING;
  return String(Math.round(s * 10) / 10).replace(".", ",") + " giây";
}

export function shotCaption(shot) {
  return [shot?.size, shot?.angle, shot?.move].map((v) => v || MISSING).concat(formatSeconds(shot?.seconds ?? null)).join(" · ");
}

export function statusText(shot) {
  if (shot?.statusRaw) return `không rõ (${shot.statusRaw})`;
  return shot?.status ? STATUS_LABEL[shot.status] : MISSING;
}

export function pad2(n) {
  return String(n).padStart(2, "0");
}

// Step 05: TWO counters, never one ambiguous number.
//  produced = "Đã lên 1080p" = status >= upscaled_1080 AND an hd_url file;
//  accepted = "Đã duyệt"     = status accepted.
// pending_review = status upscaled_1080 (engine status.progress.pending_review / gate review-pending).
// stateOnly = status >= upscaled_1080 but no hd_url yet (engine `produced` counts these; the UI does not).
export function progress(shots) {
  const list = shots || [];
  const total = list.length;
  const produced = list.filter((s) => isAtLeast(s.status, "upscaled_1080") && s.hd_url).length;
  const accepted = list.filter((s) => s.status === "accepted").length;
  const pendingReview = list.filter((s) => s.status === "upscaled_1080").map((s) => s.id);
  const stateOnly = list.filter((s) => isAtLeast(s.status, "upscaled_1080") && !s.hd_url).map((s) => s.id);
  const frac = (n) => `${pad2(n)} / ${pad2(total)}`;
  return { produced, accepted, total, pendingReview, stateOnly,
    producedLabel: frac(produced), acceptedLabel: frac(accepted),
    producedPct: total ? produced / total : 0, acceptedPct: total ? accepted / total : 0,
    // kept for older callers
    done: produced, label: frac(produced), pct: total ? produced / total : 0 };
}

// Gate line for step 05: the engine's own gate wins; otherwise derive review-pending from statuses.
export function reviewGate(state) {
  if (state?.gate) return state.gate;
  const pending = progress(state?.shots).pendingReview;
  return pending.length ? { name: "review-pending", label: GATE_LABEL["review-pending"], message: null, pending, derived: true } : null;
}

export function isSampleData(state) {
  return Boolean(state?.sample || state?.source === "sample");
}

export function isShotDone(shot) {
  return isAtLeast(shot?.status, "upscaled_1080") && Boolean(shot?.hd_url);
}

export function scenes(shots) {
  return [...new Set((shots || []).map((s) => s.scene).filter(Boolean))];
}

export function shotsInScene(shots, scene) {
  return (shots || []).filter((s) => !scene || s.scene === scene);
}

// Next shot the run would take: auto = first shot (in order) without a native video;
// selected_only = the selected shot if it exists.
export function nextShot(shots, mode, selectedId, scene = "") {
  const pool = shotsInScene(shots, scene);
  if (mode === "selected_only") return pool.find((s) => s.id === selectedId) || null;
  return pool.find((s) => !isAtLeast(s.status, "rendered")) || null;
}

export function defaultSelected(shots) {
  const list = shots || [];
  return (list.find((s) => !isAtLeast(s.status, "rendered")) || list[0] || null)?.id ?? null;
}

export function ratioLabel(sz) {
  if (!sz) return MISSING;
  const g = (a, b) => (b ? g(b, a % b) : a);
  const d = g(sz.w, sz.h);
  return `${sz.w / d}:${sz.h / d}`;
}

export function sizeLabel(sz) {
  return sz ? `${sz.w}×${sz.h}` : MISSING;
}

export function styleOptions(domain, dataStyles) {
  const base = DOMAIN_STYLES[domain] || [];
  const extra = (dataStyles || []).map((s) => (typeof s === "string" ? { value: s, label: s } : s))
    .filter((s) => s && s.value && s.label && !base.some((b) => b.value === s.value));
  const all = base.concat(extra);
  if (domain === "newtecons_live_action") return all.filter((s) => !CARTOON.test(s.value + " " + s.label));
  if (domain === "jenniejoy_cartoon_3d") return all.filter((s) => !LIVE.test(s.value + " " + s.label));
  return all;
}

export function episodeOk(ep) {
  return typeof ep === "string" && EPISODE_ID.test(ep);
}

export function dataUrl(episode) {
  return episodeOk(episode) ? DATA_DIR + encodeURIComponent(episode) + ".json" : null;
}

// The NEWTECONS video panel shows ONLY episodes of its own domain (domains are never mixed). Fail closed: an episode that is
// not in the index for this domain is never picked, and there is no fallback to "the first episode of the index".
export const PANEL_DOMAIN = "newtecons_live_action";
export const CHOOSE_EPISODE = "chọn tập";

export function episodesForDomain(episodes, domain = PANEL_DOMAIN) {
  return (Array.isArray(episodes) ? episodes : []).filter((e) => e && e.domain === domain);
}

// -> { episode, reason }: reason is null when resolved, else "chon-tap" (nothing/ambiguous) or "wrong-domain" (explicit pick of another domain).
export function resolveEpisode({ settingsEpisode, extraEpisode, episodes, domain = PANEL_DOMAIN }) {
  const mine = episodesForDomain(episodes, domain);
  const explicit = [settingsEpisode, extraEpisode].find((e) => episodeOk(e));
  if (explicit) {
    if (mine.some((e) => e.episode === explicit)) return { episode: explicit, reason: null };
    const other = (Array.isArray(episodes) ? episodes : []).find((e) => e?.episode === explicit);
    return { episode: null, reason: other ? "wrong-domain" : "chon-tap" };
  }
  return mine.length === 1 ? { episode: mine[0].episode, reason: null } : { episode: null, reason: "chon-tap" };
}

export function episodeFromExtra(extra) {
  const cand = [extra?.[EXTRA_KEY]?.episode, extra?.episode, extra?.newtecons_video?.episode, extra?.newtecons_episode,
    extra?.newtecons_h3?.episode];
  return cand.find(episodeOk) || null;
}

export function defaultSettings(state, extra) {
  const saved = extra?.[EXTRA_KEY] || {};
  const domain = state?.domain || null;
  const styles = styleOptions(domain, state?.styles);
  const pick = (v, ok, d) => (ok(v) ? v : d);
  return {
    episode: pick(saved.episode, episodeOk, state?.episode && episodeOk(state.episode) ? state.episode : ""),
    shotlist_file: typeof saved.shotlist_file === "string" ? saved.shotlist_file : "",
    asset_folder: typeof saved.asset_folder === "string" ? saved.asset_folder : "",
    run_mode: pick(saved.run_mode, (v) => RUN_MODES.some((m) => m.value === v), "auto_pending"),
    scene: typeof saved.scene === "string" ? saved.scene : "",
    shot: typeof saved.shot === "string" ? saved.shot : "",
    style: pick(saved.style, (v) => styles.some((s) => s.value === v), styles[0]?.value || ""),
    seed: seedOk(saved.seed) ? saved.seed : seedOk(state?.seed) ? state.seed : null,
    seed_mode: pick(saved.seed_mode, (v) => SEED_MODES.some((m) => m.value === v), "fixed"),
    ...audioDefaults(saved.audio, domain),
  };
}

// SFX default follows the domain (user 2026-10-31: NEWTECONS = BẬT, others = TẮT); voice/music are never muted by default.
export function audioDefaults(saved, domain) {
  const bool = (v, d) => (typeof v === "boolean" ? v : d);
  return {
    sfx_enabled: bool(saved?.sfx_enabled, domain === "newtecons_live_action"),
    mute_voice: Array.isArray(saved?.mute_stems) && saved.mute_stems.includes("voice"),
    mute_music: Array.isArray(saved?.mute_stems) && saved.mute_stems.includes("music"),
  };
}

// The block the engine reads: `jjv audio mix --audio-override <JOB json>` (only audio.sfx_enabled is honoured by the mix).
export function audioBlock(s) {
  const mute = [s?.mute_voice ? "voice" : null, s?.mute_music ? "music" : null].filter(Boolean);
  return { sfx_enabled: s?.sfx_enabled === true, mute_stems: mute };
}

export function sfxLabel(on) {
  return on ? "SFX: BẬT" : "SFX: TẮT";
}

export function seedOk(v) {
  return Number.isSafeInteger(v) && v >= 0;
}

// Validates a settings object; returns {ok, errors, value} where value is what goes into extra.
export function validateSettings(s, state) {
  const errors = [];
  const domain = state?.domain || null;
  if (s.episode && !episodeOk(s.episode)) errors.push("Tập: chỉ chữ, số, . _ -");
  if (!RUN_MODES.some((m) => m.value === s.run_mode)) errors.push("Chế độ chạy không hợp lệ");
  if (s.run_mode === "selected_only" && !s.shot) errors.push("Chọn shot khi chạy 'chỉ shot chọn'");
  if (s.shot && state?.shots?.length && !state.shots.some((x) => x.id === s.shot)) errors.push(`Shot ${s.shot} không có trong shotlist`);
  if (!domain) errors.push("Dữ liệu tập chưa ghi domain");
  else if (!styleOptions(domain, state?.styles).some((x) => x.value === s.style)) errors.push("Phong cách không thuộc domain");
  if (s.seed != null && !seedOk(s.seed)) errors.push("Seed phải là số nguyên ≥ 0 (hoặc để trống = chưa có)");
  if (!SEED_MODES.some((m) => m.value === s.seed_mode)) errors.push("Kiểu seed không hợp lệ");
  const value = {
    schema: "jjv/video-ui-settings/v1", episode: s.episode || null, domain,
    shotlist_file: s.shotlist_file || null, asset_folder: s.asset_folder || null,
    run_mode: s.run_mode, scene: s.scene || null, shot: s.shot || null,
    native: state?.native || null, export: state?.export || null, fps: state?.fps ?? null,
    style: s.style, seed: s.seed ?? null, seed_mode: s.seed_mode, submits_gpu: false,
    audio: audioBlock(s),
  };
  return { ok: errors.length === 0, errors, value };
}

// Optional job widget: a text node marked properties.newtecons_video_job, or titled "JOB ..." /
// "CÀI ĐẶT VIDEO ...". The panel writes settings JSON there; it never queues the graph.
export function findJobNode(nodes) {
  const text = new Set(["PrimitiveStringMultiline", "PrimitiveString"]);
  return (nodes || []).find((n) => text.has(n.type) && (n.properties?.newtecons_video_job === true
    || /^(JOB\b|CÀI ĐẶT VIDEO)/iu.test(String(n.title || "")))) || null;
}

// What each step shows on VÀO / RA (pure description; the DOM layer renders it).
export function stepIO(code, state, shot) {
  const s = shot || {};
  const nat = sizeLabel(state?.native);
  const hd = sizeLabel(state?.export);
  switch (code) {
    case "01": return { in: { kind: "table", caption: "Bảng shotlist" }, out: { kind: "shot", caption: "Shot đã chọn" } };
    case "02": return { in: { kind: "shot", caption: "Shot + ảnh tham chiếu" },
      out: { kind: "prompt", caption: "Prompt máy tự viết", text: s.prompt || null, refs: (s.refs || []).length } };
    case "03": return { in: { kind: "prompt", caption: "Prompt + ảnh tham chiếu", text: s.prompt || null, refs: (s.refs || []).length },
      out: { kind: "video", size: "native", caption: `Video gốc ${nat}`, url: s.native_url || null, poster: s.thumb_url || null } };
    case "04": return { in: { kind: "video", size: "native", caption: `Video gốc ${nat}`, url: s.native_url || null, zoom: 3, poster: s.thumb_url || null },
      out: { kind: "video", size: "export", caption: `Bản ${hd}`, url: s.hd_url || null, zoom: 3, poster: s.thumb_url || null } };
    case "05": return { in: { kind: "video", size: "export", caption: `Bản ${hd}`, url: s.hd_url || null, poster: s.thumb_url || null },
      out: { kind: "progress", caption: `Đủ ${state?.shots?.length ?? 0} shot` } };
    default: return null;
  }
}

// Centre crop of a w×h frame at zoom k (for the "PHÓNG TO ×3" inset).
export function zoomCrop(w, h, k = 3) {
  const cw = w / k;
  const ch = h / k;
  return { x: (w - cw) / 2, y: (h - ch) / 2, w: cw, h: ch };
}

// LiteGraph: screen = (graph + offset) * scale. Fit a group's bounding into the free viewport.
export function fitBounds(b, view, pads = {}) {
  const { left = 0, right = 0, top = 0, bottom = 0, margin = 24 } = pads;
  const availW = Math.max(120, view.width - left - right - 2 * margin);
  const availH = Math.max(120, view.height - top - bottom - 2 * margin);
  const scale = Math.min(2, Math.max(0.05, Math.min(availW / b[2], availH / b[3])));
  const sx = left + margin + (availW - b[2] * scale) / 2;
  const sy = top + margin + (availH - b[3] * scale) / 2;
  return { scale, offset: [sx / scale - b[0], sy / scale - b[1]] };
}

export function groupForStep(groups, code) {
  return (groups || []).find((g) => String(g.title || "").trim().startsWith(code + " ")) || null;
}

// ---- Media phủ lên state (data/video/<tập>.media.json, jjv/video-ui-media/v1) ----
// Poster, bản 1440 (SeedVR2) và phim cuối lấy từ receipt trên đĩa (tools/build_step_ui_index.py). Chỉ điền chỗ TRỐNG của state
// engine (url engine thắng) và chỉ khi cùng tập; sai tập ⇒ bỏ qua, không trộn dữ liệu giữa hai phim.
export const MEDIA_SCHEMA = "jjv/video-ui-media/v1";
export function applyMedia(state, media) {
  const ok = media && media.schema === MEDIA_SCHEMA && state && media.episode === state.episode;
  if (!ok) return { ...state, finalFilm: null };
  const shots = state.shots.map((s) => {
    const m = media.shots?.[s.id];
    if (!m) return s;
    const hd = s.hd_url || safeUrl(m.hd_url);
    return { ...s, thumb_url: s.thumb_url || safeUrl(m.thumb_url), hd_url: hd, hdFromMedia: !s.hd_url && Boolean(hd),
      logo_url: safeUrl(m.logo_url), mediaNote: text(m.note) };
  });
  const f = media.final;
  return { ...state, shots, finalFilm: f && f.exists && safeUrl(f.url) ? { label: text(f.label), url: safeUrl(f.url), bytes: f.bytes ?? null } : null };
}
