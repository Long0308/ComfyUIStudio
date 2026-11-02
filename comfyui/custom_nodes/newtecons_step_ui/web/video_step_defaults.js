// Pure helpers for video tabs 06-08: prefill from the known episode/shot and client-side required-field hints.
// Paths are repo-relative (the host runner resolves them against the repo root). No DOM, no network.
export const REQUIRED = {
  "seedvr2.plan": ["out"], "seedvr2.execute": ["plan"], "post.logo": ["video", "out"],
  "timing.words": ["dialogue", "out"],
  "captions.burn": ["video", "timing", "timing_receipt", "subtitles", "font", "wav", "out"],
  "edit.assemble": ["edl", "out_dir", "tag"],
};
const STORY_ROOT = "production-local/JennieJoyKids-Story";
const dirname = (p) => String(p).replaceAll("\\", "/").replace(/\/[^/]*$/, "");

// Episode slug: metadata first; otherwise the only episode of the defaults table.
export function episodeFor(m, table) {
  const own = m?.episode_id || m?.episode;
  if (own) return String(own);
  return table?.episode ? String(table.episode) : "";
}

export function prefill(verb, shot, episode, table) {
  const row = table?.shots?.[shot] || {};
  const root = episode ? `${STORY_ROOT}/${episode}/preview` : "";
  const out = (name) => (root && shot ? `${root}/${shot}/${shot}_${name}` : "");
  const best = row.logo || row.hd || row.native || "";
  const values = {
    "seedvr2.plan": { out: "AUTO", segments_root: row.native ? dirname(row.native) : "" },
    "seedvr2.execute": {},
    "post.logo": { video: row.hd || row.native || "", out: out("logo_preview.mp4") },
    "timing.words": { out: out("timing.json") },
    "captions.burn": { video: best, out: out("captions_preview.mp4") },
    "edit.assemble": { out_dir: root ? `${root}/assemble` : "", tag: "ui-preview" },
  }[verb] || {};
  return Object.fromEntries(Object.entries(values).filter(([, v]) => v));
}

// Blank optional fields are dropped (server rejects "" paths); blank REQUIRED fields are reported, not sent.
export function buildArgs(verb, raw) {
  const args = {}, missing = [];
  for (const [k, v] of Object.entries(raw)) if (typeof v !== "string" || v.trim() !== "") args[k] = typeof v === "string" ? v.trim() : v;
  for (const k of REQUIRED[verb] || []) if (!(k in args)) missing.push(k);
  return { args, missing };
}

export function missingHint(missing, shotKnown) {
  const base = `Còn thiếu: ${missing.join(", ")}. Điền đường dẫn (tương đối từ gốc repo) rồi bấm lại.`;
  return shotKnown ? base : base + " Shot chưa xác định từ workflow nên chưa tự điền được.";
}
