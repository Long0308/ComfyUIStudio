// NEWTECONS VIDEO step panel — gold-on-black 5-step UI for the video flow graph (layout: step_dock.js).
// Domain-aware video detection includes named H3 LongTake exports without step groups. Reads data/video/index.json + data/video/<episode>.json (written by the engine side);
// writes settings ONLY into graph.extra.newtecons_video_ui and an optional JOB text widget.
// It never queues a prompt (no POST /prompt, no GPU work).
// Gold palette = explicit user exception 2026-10-31 ("LÀM GIAO DIỆN VÀNG NHƯ NÀY") for this panel only.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import * as L from "./video_ui_logic.js";
import { activeWorkflowContext } from "./workflow_context.js";
import { PIPELINE_CSS, pipelineViewModel, renderPipelineHtml } from "./pipeline_view_logic.js";
import { arrowSvg as arrowBase, createDock, el } from "./step_dock.js";
import { THEMES } from "./step_dock_logic.js";

const EXT = "Newtecons.VideoUI";
const POLL_MS = 1000;
const DATA_REFRESH_MS = 20000;
const SAMPLE_URL = new URL("./video_ui_sample.json", import.meta.url).href;
const DATA_BASE = new URL("./data/video/", import.meta.url).href;


const state = {
  active: false, step: "01",
  index: null, indexErr: null, data: null, dataRaw: "", dataUrl: null, dataErr: null, usingSample: false,
  selected: null, settings: null, saved: null, savedAt: null, lastFetch: 0, sig: "",
};
let dock = null;


function isMock() {
  return state.usingSample || L.isSampleData(state.data);
}

function mediaSrc(url) {
  if (!url) return null;
  return url.startsWith("/view") || url.startsWith("/api/") ? api.apiURL(url) : url;
}

function graphInfo() {
  const g = app.graph;
  if (!g) return null;
  const groups = (g._groups || g.groups || []).map((gr) => {
    const b = gr._bounding || gr.boundingRect || gr.bounding || [gr.pos?.[0], gr.pos?.[1], gr.size?.[0], gr.size?.[1]];
    return { title: gr.title, bounding: Array.from(b || [], Number) };
  });
  return { g, extra: g.extra || {}, groups, context: activeWorkflowContext(app) };
}

// ---------- data ----------
async function getJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const raw = (await res.text()).replace(/^﻿/u, "");
  return { raw, json: JSON.parse(raw) };
}

async function loadIndex() {
  try {
    const { json } = await getJson(DATA_BASE + "index.json");
    state.index = L.normalizeIndex(json);
    state.indexErr = state.index.ok ? null : state.index.errors.join("; ");
  } catch (err) {
    state.index = { ok: false, episodes: [], errors: [] };
    state.indexErr = `chưa có data/video/index.json (${err.message})`;
  }
}

function pickEpisode(info) {
  return L.resolveEpisode({ settingsEpisode: state.settings?.episode, extraEpisode: L.episodeFromExtra(info?.extra),
    episodes: state.index?.episodes });
}

async function loadData(info, force = false) {
  const picked = pickEpisode(info);
  const ep = picked.episode;
  const entry = (state.index?.episodes || []).find((e) => e.episode === ep);
  const url = entry ? new URL(entry.url.split("/").pop(), DATA_BASE).href
    : ep && L.dataUrl(ep) ? new URL(encodeURIComponent(ep) + ".json", DATA_BASE).href : null;
  let raw = "";
  let json = null;
  let err = null;
  if (url) {
    try { ({ raw, json } = await getJson(url)); } catch (e) { err = `không đọc được ${ep}.json (${e.message})`; }
  } else err = picked.reason === "wrong-domain" ? "tập đã chọn thuộc domain khác — bảng này chỉ hiện tập NEWTECONS" : "chưa chọn tập";
  if (json && json.domain !== L.PANEL_DOMAIN) {
    err = `dữ liệu ${ep}.json thuộc domain ${json.domain ?? "không rõ"}, không phải ${L.PANEL_DOMAIN}; không hiển thị`;
    json = null; raw = "";
  }
  const usingSample = !json;
  if (usingSample) ({ raw, json } = await getJson(SAMPLE_URL));
  state.lastFetch = performance.now();
  if (!force && raw === state.dataRaw && usingSample === state.usingSample) return false;
  let data = L.normalizeState(json, usingSample ? "sample" : url);
  if (!usingSample && data.episode) {  // media từ receipt trên đĩa: chỉ phủ vào chỗ trống, cùng tập
    // await TRƯỚC khi gán state: render() chen vào lúc settings còn null sẽ nổ ("reading 'episode'" của null).
    try { data = L.applyMedia(data, (await getJson(new URL("media/" + encodeURIComponent(data.episode) + ".media.json", DATA_BASE).href)).json); }
    catch { data = L.applyMedia(data, null); }
  }
  state.dataRaw = raw;
  state.dataUrl = usingSample ? SAMPLE_URL : url;
  state.dataErr = err;
  state.usingSample = usingSample;
  state.data = data;
  const prev = state.settings;
  state.settings = { ...L.defaultSettings(state.data, info?.extra), ...(prev ? { episode: prev.episode } : {}) };
  if (usingSample && state.settings.episode === state.data.episode) state.settings.episode = prev?.episode || "";
  if (!state.settings.episode && !usingSample) state.settings.episode = ep || "";
  if (!state.data.shots.some((s) => s.id === state.selected)) {
    state.selected = state.data.shots.some((s) => s.id === state.settings.shot) ? state.settings.shot : L.defaultSelected(state.data.shots);
  }
  return true;
}

// ---------- settings write (graph.extra + optional JOB widget; never queues) ----------
function writeSettings() {
  const info = graphInfo();
  if (!info) return;
  if (isMock()) { state.saved = { ok: false, errors: ["Đang xem MẪU / MOCK — không ghi cài đặt mẫu vào graph"] }; render(); return; }
  const v = L.validateSettings(state.settings, state.data);
  if (!v.ok) { state.saved = { ok: false, errors: v.errors }; render(); return; }
  const value = { ...v.value, written_at: new Date().toISOString(), source: state.usingSample ? "SAMPLE" : state.dataUrl };
  info.g.extra = { ...info.extra, [L.EXTRA_KEY]: value };
  const job = L.findJobNode((info.g._nodes || info.g.nodes || []).map((n) => ({ id: n.id, type: n.type, title: n.title, properties: n.properties })));
  let jobMsg = "không có node JOB trong graph";
  if (job) {
    const node = info.g.getNodeById(job.id);
    const w = node?.widgets?.find((x) => x.name === "value") || node?.widgets?.[0];
    if (w) { w.value = JSON.stringify(value, null, 2); jobMsg = `đã ghi node JOB #${job.id}`; }
  }
  info.g.change?.();
  app.canvas?.setDirty(true, true);
  state.saved = { ok: true, jobMsg };
  state.savedAt = new Date();
  render();
}

// ---------- graph ----------
function zoomToGroup(code) {
  const info = graphInfo();
  const grp = info && L.groupForStep(info.groups, code);
  if (grp) dock.zoomTo(grp.bounding);
}

// ---------- render pieces ----------
function arrowSvg() {
  return arrowBase(THEMES.gold.acc);
}

function slot(kind, caption, ...kids) {
  const badge = kind === "in" ? el("span", { class: "ntd-badge", text: "VÀO" }) : el("span", { class: "ntd-badge ra", text: "RA" });
  return el("div", { class: "ntd-slot" }, el("div", { class: "ntd-lbl" }, badge, el("span", { text: caption })), ...kids);
}

function empty(title, sub) {
  return el("div", { class: "ntd-empty" }, el("b", { text: title }), sub || "");
}

function selShot() {
  return state.data?.shots.find((s) => s.id === state.selected) || null;
}

function select(id) {
  state.selected = id;
  state.settings = { ...state.settings, shot: id, scene: state.settings.scene && selShot()?.scene !== state.settings.scene ? "" : state.settings.scene };
  render();
  ensureAnchors(selShot(), true);
}

// ---------- v4.2: load the shot's staged anchor pack into the graph's anchor LoadImage nodes ----------
// Only anchor_pack.staged entries are used. Each file is verified first (GET /view + SHA-256 in the browser);
// only verified slots are filled + unmuted, the rest muted. No upload, no /prompt.
function liveAnchorNodes() {
  return (app.graph?._nodes || app.graph?.nodes || []).filter((n) => typeof n.properties?.nt_anchor_slot === "string" && n.properties.nt_anchor_slot)
    .map((n) => ({ id: n.id, type: n.type, title: n.title, mode: n.mode || 0, properties: { ...n.properties },
      widgets: { image: n.widgets?.find((w) => w.name === "image")?.value ?? "" } }));
}

function inputViewUrl(e) {
  return api.apiURL("/view?" + new URLSearchParams({ filename: e.filename, subfolder: e.subfolder, type: "input" }).toString());
}

async function checkStaged(e) {
  try {
    const res = await fetch(inputViewUrl(e), { cache: "no-store" });
    if (!res.ok) return { exists: false, http: res.status };
    if (!globalThis.crypto?.subtle) return { exists: true, sha256: null, error: "no crypto.subtle" };
    const buf = await crypto.subtle.digest("SHA-256", await res.arrayBuffer());
    return { exists: true, sha256: [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("") };
  } catch (err) {
    return { exists: false, error: String(err?.message || err) };
  }
}

async function ensureAnchors(shot, auto) {
  const staged = shot?.anchor?.staged || [];
  if (!staged.length || !liveAnchorNodes().length) return;
  state.anchorChecks = state.anchorChecks || {};
  state.anchorPending = state.anchorPending || new Set();
  const todo = staged.filter((e) => !state.anchorChecks[e.value + "#" + e.sha256] && !state.anchorPending.has(e.value + "#" + e.sha256));
  if (todo.length) {
    todo.forEach((e) => state.anchorPending.add(e.value + "#" + e.sha256));
    const res = await Promise.all(todo.map(checkStaged));
    todo.forEach((e, i) => { state.anchorChecks[e.value + "#" + e.sha256] = res[i]; state.anchorPending.delete(e.value + "#" + e.sha256); });
  } else if (staged.some((e) => state.anchorPending.has(e.value + "#" + e.sha256))) return; // another call is verifying

  const plan = L.anchorPlan(liveAnchorNodes(), staged, checksFor(staged));
  if (auto && plan.ready && !plan.applied && selShot()?.id === shot.id) applyAnchors(shot, "tự nạp khi chọn shot");
  else render();
}

function checksFor(staged) {
  return Object.fromEntries(staged.map((e) => [e.value, state.anchorChecks?.[e.value + "#" + e.sha256]]).filter(([, c]) => c));
}

function applyAnchors(shot, how) {
  const staged = shot?.anchor?.staged || [];
  const plan = L.anchorPlan(liveAnchorNodes(), staged, checksFor(staged));
  let filled = 0;
  for (const r of plan.rows) {
    const node = app.graph.getNodeById(r.nodeId);
    if (!node) continue;
    if (r.value) {
      const w = node.widgets?.find((x) => x.name === "image");
      if (w) { w.value = r.value; w.callback?.(r.value); filled += 1; }
    }
    node.mode = r.mode;
  }
  app.graph.change?.(); app.graph.afterChange?.();
  app.canvas?.setDirty(true, true);
  state.anchorMsg = { ok: plan.ready, text: `${how}: ${filled}/${plan.rows.filter((r) => r.entry).length} ô đã nạp · ${plan.rows.filter((r) => r.mode === L.MUTED).length} ô tắt · shot ${shot.id}. Lưu workflow (Ctrl+S) để giữ.` };
  render();
}

function anchorSection(shot) {
  const nodes = liveAnchorNodes();
  if (!nodes.length) return null;
  const staged = shot?.anchor?.staged || [];
  const head = el("div", { class: "ntd-lbl" }, el("span", { class: "ntd-badge", text: "BỘ NEO" }), el("span", { text: `${nodes.length} ô neo trong graph (nt_anchor_slot) · shot ${shot?.id || L.MISSING}` }));
  if (!staged.length) {
    return el("div", { class: "ntd-slot", style: "margin-top:8px", "data-act": "anchors" }, head,
      el("div", { class: "ntd-banner" }, el("b", { text: "CHƯA NẠP ĐƯỢC: " }), "dữ liệu tập chưa có anchor_pack.staged cho shot này (chờ engine ghi). Bảng không dùng refs cũ."
        + (shot?.anchor?.stagedRejected ? ` ${shot.anchor.stagedRejected} mục staged bị loại (đường dẫn/sha/tên cũ không hợp lệ).` : "")));
  }
  const plan = L.anchorPlan(nodes, staged, checksFor(staged));
  const color = { loaded: "var(--ok)", missing_file: "var(--bad)", sha_mismatch: "var(--bad)", needs_root: "var(--bad)", unchecked: "var(--mute)", empty: "var(--mute)" };
  const table = el("table", { class: "ntd-table", "data-act": "anchor-table" },
    el("thead", {}, el("tr", {}, ["Ô (slot)", "Node", "Vai", "File", "Trạng thái"].map((h) => el("th", { text: h })))),
    el("tbody", {}, plan.rows.map((r) => el("tr", { "data-status": r.status },
      el("td", { text: r.slot }), el("td", { text: `#${r.nodeId} ${String(r.title).split(" — ")[0]}` }), el("td", { text: r.entry?.role || "—" }),
      el("td", { text: r.entry ? r.entry.value : "—", title: r.entry ? `sha256 ${r.entry.sha256}` : "" }),
      el("td", {}, el("b", { style: `color:${color[r.status]}`, text: L.anchorStatusLabel(r.status) }))))));
  const btn = el("button", { class: "ntd-btn", "data-act": "load-anchors", text: "NẠP BỘ NEO VÀO GRAPH",
    onclick: () => applyAnchors(shot, "nạp tay") });
  if (!plan.rows.some((r) => r.status === "loaded")) btn.setAttribute("disabled", "");
  return el("div", { class: "ntd-slot", style: "margin-top:8px", "data-act": "anchors" }, head,
    el("div", { class: "ntd-row2" }, btn, el("span", { text: plan.applied ? "graph đang giữ đúng bộ neo này" : plan.ready ? "đủ file, chưa nạp" : "chưa đủ file đã kiểm" })),
    state.anchorMsg ? el("div", { class: "ntd-msg" }, el("span", { class: state.anchorMsg.ok ? "ok" : "bad", text: state.anchorMsg.text })) : null,
    plan.orphans.length ? el("div", { class: "ntd-warn", text: `Mục staged không có ô trong graph: ${plan.orphans.map((e) => e.slot).join(", ")}` }) : null,
    shot.anchor.stagedRejected ? el("div", { class: "ntd-warn", text: `${shot.anchor.stagedRejected} mục staged bị loại (đường dẫn / sha / tên ảnh cũ).` }) : null,
    el("div", { class: "ntd-scroll" }, table));
}

function legacyLine(shot) {
  const note = L.legacyNote(shot);
  return note ? el("div", { class: "meta", "data-act": "legacy", title: shot.legacy.map((r) => r.name).join(" · ") },
    el("s", { text: note, style: "color:var(--mute)" })) : null;
}

function refsGrid(refs, max = 6) {
  if (!refs.length) return empty("CHƯA CÓ", "Shot này chưa có ảnh tham chiếu.");
  return el("div", { class: "ntd-refs" }, refs.slice(0, max).map((r) => el("div", { class: "ntd-ref", title: r.name },
    r.url ? el("img", { src: mediaSrc(r.url), alt: r.name, loading: "lazy" }) : `${r.name} · chưa có ảnh`)));
}

function tableView() {
  const shots = L.shotsInScene(state.data.shots, state.settings.scene);
  if (!shots.length) return empty("CHƯA CÓ", "Shotlist trống.");
  return el("div", { class: "ntd-scroll" }, el("table", { class: "ntd-table" },
    el("thead", {}, el("tr", {}, ["Ảnh", "Shot", "Cỡ cảnh", "Ảnh tham chiếu", "Trang phục", "Trạng thái", "Native / 1440"].map((h) => el("th", { text: h })))),
    el("tbody", {}, shots.map((s) => el("tr", { class: s.id === state.selected ? "sel" : null, onclick: () => select(s.id) },
      el("td", {}, s.thumb_url ? el("img", { src: mediaSrc(s.thumb_url), alt: s.id, loading: "lazy", style: "width:64px;height:36px;object-fit:cover;border-radius:3px" }) : "—"),
      el("td", { text: s.id }), el("td", { text: s.size || L.MISSING }),
      el("td", {}, s.refs.length ? el("div", { class: "ntd-dots", title: s.refs.map((r) => r.name).join("\n") },
        s.refs.map((r) => el("span", { class: r.url ? "has" : null }))) : L.MISSING),
      el("td", { text: L.wardrobeText(s), title: s.wardrobe?.refused || "" }),
      el("td", { text: L.statusText(s) }),
      el("td", { text: `${s.native_url ? "native ✓" : "native —"} · ${s.hd_url ? "1440 ✓" : "1440 —"}`, title: s.mediaNote || "" }))))));
}

function shotView(s) {
  if (!s) return empty("CHƯA CHỌN", "Chọn một shot trong bảng.");
  return el("div", { class: "ntd-shot" },
    el("div", { class: "id", text: s.id }), el("div", { class: "cap", text: L.shotCaption(s) }),
    el("div", { class: "meta", text: `Scene ${s.scene || L.MISSING} · ${L.statusText(s)} · ${s.refs.length} ảnh tham chiếu` }),
    el("div", { class: "meta", title: s.wardrobe?.refused || "" }, "Trang phục: ",
      el("b", { class: s.wardrobe?.refused ? "bad" : null, style: s.wardrobe?.refused ? "color:var(--bad)" : "color:var(--acc)", text: L.wardrobeText(s) })),
    L.anchorText(s) ? el("div", { class: "meta", "data-act": "anchor" }, el("span", { class: "ntd-chip" + (s.anchor?.status === "approved" ? " solid" : ""), text: L.anchorText(s) })) : null,
    refsGrid(s.refs), legacyLine(s));
}

function promptView(text, refs) {
  return el("div", {}, text ? el("div", { class: "ntd-prompt", text }) : empty("CHƯA CÓ PROMPT", "Máy chưa viết prompt cho shot này."),
    el("div", { style: "margin-top:8px" }, el("span", { class: "ntd-chip solid", text: `+${refs.length} ảnh tham chiếu` })),
    el("div", { style: "margin-top:8px" }, refsGrid(refs, 3)), legacyLine(selShot()));
}

function videoView(io, sz) {
  const ratio = sz ? `${sz.w}/${sz.h}` : "16/9";
  const box = el("div", { class: "ntd-media", style: `aspect-ratio:${ratio}` });
  const src = mediaSrc(io.url);
  let main = null;
  if (src) {
    main = el("video", { src, controls: true, muted: true, loop: true, preload: "metadata", poster: mediaSrc(io.poster) });
    box.append(main);
  } else box.append(empty("CHƯA CÓ", `${io.caption} — chưa có file.`));
  if (!io.zoom) return box;
  // Label sits in its own strip above the window, so it can never cover the window's content. Without a
  // video the inset goes BELOW the frame (no overlap with the "chưa có" text); with a video it overlays it.
  const win = el("div", { class: "win", style: `aspect-ratio:${ratio}` });
  const z = el("div", { class: "ntd-zoom " + (src ? "over" : "below") }, el("span", { class: "tag", text: `PHÓNG TO ×${io.zoom}` }), win);
  {
    if (src) box.append(el("div", { class: "ntd-frame", title: `vùng phóng to ×${io.zoom}` }));
    if (src) {
      const inset = el("video", { src, muted: true, loop: true, preload: "metadata" });
      const sync = () => { if (Math.abs(inset.currentTime - main.currentTime) > 0.12) inset.currentTime = main.currentTime; };
      main.addEventListener("timeupdate", sync); main.addEventListener("seeked", sync);
      main.addEventListener("play", () => { sync(); inset.play().catch(() => {}); });
      main.addEventListener("pause", () => inset.pause());
      win.append(inset);
      box.append(z);
      return box;
    }
    win.append(empty("", "chưa có"));
  }
  return el("div", {}, box, z);
}

function progressView() {
  const p = L.progress(state.data.shots);
  const gate = L.reviewGate(state.data);
  const counter = (cls, k, v, pct) => el("div", { class: "ntd-count " + cls }, el("span", { class: "k", text: k }), el("span", { class: "v", text: v }),
    el("div", { class: "ntd-pbar" }, el("i", { style: `width:${(pct * 100).toFixed(1)}%` })));
  return el("div", { class: "ntd-prog" },
    counter("hd", "Đã lên 1080p", p.producedLabel, p.producedPct),
    counter("acc", "Đã duyệt", p.acceptedLabel, p.acceptedPct),
    el("div", { class: "ntd-lbl", text: "Ô vàng đặc = đã lên 1080p (trạng thái ≥ upscaled_1080 VÀ có file hd_url) · viền xanh = đã duyệt (accepted) · ô rỗng = chưa có" }),
    p.stateOnly.length ? el("div", { class: "ntd-lbl", text: `${p.stateOnly.length} shot có trạng thái 1080p nhưng chưa có file hd_url (không tính): ${p.stateOnly.join(", ")}` }) : null,
    gate ? el("div", { class: "ntd-gate" }, el("b", { text: `${gate.label} (${gate.name})` }),
      gate.pending.length ? ` · ${gate.pending.length} shot: ${gate.pending.join(", ")}` : "",
      gate.message ? ` · ${gate.message}` : "",
      gate.derived ? " · suy từ trạng thái shot (engine chưa ghi gate)" : "",
      gate.name === "review-pending" ? el("div", { text: "Chế độ user chọn: duyệt shot đầu rồi tự chạy — các shot sau dừng ở 1080p chờ duyệt cuối lượt, chưa phải đã duyệt." }) : null)
      : el("div", { class: "ntd-lbl", text: "Cổng: chưa có (không shot nào chờ duyệt)" }),
    state.data.finalFilm ? el("div", { class: "ntd-slot", style: "margin-top:8px" },
      el("div", { class: "ntd-lbl" }, el("span", { class: "ntd-badge", text: "PHIM CUỐI" }), el("span", { text: state.data.finalFilm.label || "phim cuối" })),
      el("video", { src: mediaSrc(state.data.finalFilm.url), controls: true, muted: true, preload: "metadata", style: "width:100%;max-height:260px;background:#000" }),
      el("div", { class: "ntd-lbl", text: "Từ receipt assemble trên đĩa — bản review, chưa duyệt (không nằm trong state engine)." }))
      : el("div", { class: "ntd-lbl", style: "margin-top:8px", text: "PHIM CUỐI: chưa có file assemble cho tập này." }),
    el("div", { class: "ntd-grid", style: "margin-top:8px" }, state.data.shots.map((s) => {
      const done = L.isShotDone(s);
      return el("button", { class: "ntd-cell" + (done ? " done" : "") + (s.status === "accepted" ? " acc" : "") + (s.id === state.selected ? " sel" : ""),
        title: `${s.id} · ${L.statusText(s)}`, onclick: () => select(s.id) },
      s.thumb_url ? el("img", { src: mediaSrc(s.thumb_url), alt: s.id, loading: "lazy" }) : null, el("span", { text: s.id }));
    })));
}

function ioView(io, shot) {
  switch (io.kind) {
    case "table": return tableView();
    case "shot": return shotView(shot);
    case "prompt": return promptView(io.text, shot?.refs || []);
    case "video": return videoView(io, io.size === "native" ? state.data.native : state.data.export);
    case "progress": return progressView();
    default: return empty("?", "");
  }
}

function stepNote(code) {
  const d = state.data.domain;
  const w = selShot()?.wardrobe;
  if (code === "02" && w?.refused) {
    return el("div", { class: "ntd-banner bad" }, el("b", { text: "TRANG PHỤC BỊ TỪ CHỐI: " }), w.refused);
  }
  if (code === "04" && d === "newtecons_live_action") {
    return el("div", { class: "ntd-banner" }, el("b", { text: "CHƯA NGHIỆM THU: " }),
      "lên 1080p cho NEWTECONS cần pilot GPU do user duyệt (AGENTS.md, luật engine 2). Bảng này không chạy GPU.");
  }
  return null;
}

function field(label, control) {
  return el("label", { class: "ntd-f" }, el("span", { text: label }), control);
}

function select_(options, value, onchange) {
  return el("select", { onchange: (e) => onchange(e.target.value) }, options.map(([v, t]) => {
    const o = el("option", { value: v, text: t });
    if (v === value) o.selected = true;
    return o;
  }));
}

function setS(patch, reload = false) {
  state.settings = { ...state.settings, ...patch };
  state.saved = null;
  if (reload) { state.dataRaw = ""; loadData(graphInfo(), true).then(render); return; }
  render();
}

function settingsCard() {
  const s = state.settings;
  const d = state.data;
  const eps = L.episodesForDomain(state.index?.episodes);  // chỉ tập NEWTECONS
  const epOpts = eps.map((e) => [e.episode, `${e.label || e.episode} — ${L.domainLabel(e.domain)}`]);
  if (!s.episode) epOpts.unshift(["", "— chọn tập —"]);
  if (s.episode && !eps.some((e) => e.episode === s.episode)) epOpts.unshift([s.episode, `${s.episode} (không có trong index NEWTECONS)`]);
  if (!epOpts.length) epOpts.push(["", "chưa có tập (index trống)"]);
  const sceneOpts = [["", "Tất cả scene"], ...L.scenes(d.shots).map((x) => [x, x])];
  const shotOpts = [["", "—"], ...L.shotsInScene(d.shots, s.scene).map((x) => [x.id, `${x.id} · ${L.statusText(x)}`])];
  const styles = L.styleOptions(d.domain, d.styles);
  const v = L.validateSettings(s, d);
  const next = L.nextShot(d.shots, s.run_mode, s.shot || state.selected, s.scene);
  const msg = state.saved?.ok ? el("span", { class: "ok", text: `Đã ghi graph.extra.${L.EXTRA_KEY} lúc ${state.savedAt.toLocaleTimeString()} · ${state.saved.jobMsg}. Lưu workflow để giữ.` })
    : state.saved && !state.saved.ok ? el("span", { class: "bad", text: state.saved.errors.join(" · ") })
      : isMock() ? el("span", { text: "Đang xem MẪU / MOCK: nút ghi khoá cho tới khi có data/video/<tập>.json thật." })
      : v.ok ? el("span", { text: "Chưa ghi. Ghi chỉ đổi graph, không gửi /prompt." }) : el("span", { class: "bad", text: v.errors.join(" · ") });
  const sec = (n, title, ...kids) => el("div", { class: "ntd-sec" }, el("h4", {}, el("i", { text: String(n) }), title), ...kids);
  return el("div", { class: "ntd-card" },
    el("h3", { text: "INPUT" }),
    sec(1, "KỊCH BẢN & SHOTLIST",
      field("Tập", select_(epOpts, s.episode, (x) => setS({ episode: x }, true))),
      field("Domain", el("output", {}, el("span", { class: "ntd-chip", text: L.domainLabel(d.domain) }))),
      field("File shotlist", el("input", { value: s.shotlist_file, placeholder: "đường dẫn shotlist / kịch bản", onchange: (e) => setS({ shotlist_file: e.target.value.trim() }) }))),
    sec(2, "ASSET · ẢNH THAM CHIẾU",
      field("Thư mục", el("input", { value: s.asset_folder, placeholder: "thư mục ảnh tham chiếu", onchange: (e) => setS({ asset_folder: e.target.value.trim() }) })),
      field("Shot chọn", el("output", { text: `${selShot()?.refs.length ?? 0} ảnh tham chiếu` }))),
    sec(3, "SHOT CẦN RENDER",
      field("Chế độ chạy", select_(L.RUN_MODES.map((m) => [m.value, m.label]), s.run_mode, (x) => setS({ run_mode: x }))),
      field("Scene", select_(sceneOpts, s.scene, (x) => setS({ scene: x }))),
      field("Shot", select_(shotOpts, s.shot, (x) => { setS({ shot: x }); if (x) select(x); })),
      field("Lượt kế", el("output", { text: next ? next.id : "không còn shot chờ" }))),
    sec(4, "KHUNG HÌNH & ĐỘ PHÂN GIẢI",
      field("Tỉ lệ", el("output", { text: `${L.ratioLabel(d.export)} xuất · ${L.ratioLabel(d.native)} gốc` })),
      field("Sinh H3 native", el("output", { text: L.sizeLabel(d.native) })),
      field("Xuất", el("output", { text: `${L.sizeLabel(d.export)} · ${d.fps ?? L.MISSING} fps` }))),
    sec(5, "HÌNH ẢNH",
      field("Phong cách", styles.length ? select_(styles.map((x) => [x.value, x.label]), s.style, (x) => setS({ style: x }))
        : el("output", { text: "chưa có (dữ liệu chưa ghi domain)" }))),
    sec(6, "SEED",
      field("Seed gốc", el("input", { type: "number", min: "0", step: "1", value: s.seed == null ? "" : String(s.seed), placeholder: "chưa có",
        title: s.seed == null ? "Dữ liệu tập chưa ghi seed" : null,
        onchange: (e) => setS({ seed: e.target.value.trim() === "" ? null : Number(e.target.value) }) })),
      field("Kiểu seed", select_(L.SEED_MODES.map((m) => [m.value, m.label]), s.seed_mode, (x) => setS({ seed_mode: x })))),
    sec(7, "ÂM THANH (mix)",
      field("SFX", el("button", { class: "ntd-btn", "data-act": "toggle-sfx", "aria-pressed": String(s.sfx_enabled),
        title: "Ghi vào audio.sfx_enabled của JOB; mix đọc qua --audio-override", text: L.sfxLabel(s.sfx_enabled),
        onclick: () => setS({ sfx_enabled: !s.sfx_enabled }) })),
      field("Tắt tiếng giọng", el("input", { type: "checkbox", checked: s.mute_voice, onchange: (e) => setS({ mute_voice: e.target.checked }) })),
      field("Tắt tiếng nhạc", el("input", { type: "checkbox", checked: s.mute_music, onchange: (e) => setS({ mute_music: e.target.checked }) })),
      (s.mute_voice || s.mute_music) ? el("div", { class: "ntd-warn", text: "Mix chưa hỗ trợ tắt giọng/nhạc (phá cổng loudness): engine sẽ TỪ CHỐI file JOB này cho tới khi bỏ chọn." }) : null),
    el("button", { class: "ntd-btn", disabled: !v.ok || isMock(), onclick: writeSettings, text: "GHI CÀI ĐẶT VÀO GRAPH" }),
    el("div", { class: "ntd-msg" }, msg));
}

// One shot = one full pipeline (10 stages). Display-only: copy buttons write text to the clipboard, nothing is sent.
function pipelineSection(shot) {
  const box = el("div", { class: "ntd-slot", style: "margin-top:8px;background:#fff;color:#0A2540;overflow:auto;max-height:520px" });
  box.innerHTML = `<style>${PIPELINE_CSS.replace(/body\{[^}]*\}/u, "")}</style>${renderPipelineHtml(pipelineViewModel(shot))}`;
  box.addEventListener("click", (e) => {
    const code = e.target?.closest?.("code[data-copy]");
    if (code) navigator.clipboard?.writeText(code.getAttribute("data-copy"));
  });
  return box;
}

function bodyView() {
  const step = L.VIDEO_STEPS.find((x) => x.code === state.step);
  const shot = selShot();
  const io = L.stepIO(step.code, state.data, shot);
  const info = graphInfo();
  const kids = [el("div", { class: "ntd-title" }, el("span", { class: "n", text: step.code }), el("span", { class: "t", text: step.label }),
    info && L.groupForStep(info.groups, step.code) ? el("button", { class: "x", text: "XEM NHÓM TRÊN GRAPH", onclick: () => zoomToGroup(step.code) }) : null)];
  if (isMock()) {
    kids.push(el("div", { class: "ntd-banner" }, el("b", { text: "ĐANG XEM MẪU / MOCK — " }),
      `${state.data.sampleNote || "không phải dữ liệu thật."} ${state.dataErr ? "Lý do: " + state.dataErr + "." : ""}`));
  }
  const errs = [...(state.data.errors || []), ...(state.indexErr && !state.usingSample ? [state.indexErr] : [])];
  if (errs.length) kids.push(el("div", { class: "ntd-banner bad" }, el("b", { text: "DỮ LIỆU LỖI: " }), errs.slice(0, 6).join(" · ")));
  kids.push(stepNote(step.code));
  kids.push(el("div", { class: "ntd-row" }, slot("in", io.in.caption, ioView(io.in, shot)), arrowSvg(), slot("out", io.out.caption, ioView(io.out, shot))));
  if (step.code === "02") {
    kids.push(anchorSection(shot));
    if (shot?.anchor?.staged?.length && !shot.anchor.staged.every((e) => state.anchorChecks?.[e.value + "#" + e.sha256])) ensureAnchors(shot, false);
  }
  if (shot?.pipeline) kids.push(pipelineSection(shot));
  kids.push(el("div", { class: "ntd-foot" },
    el("span", {}, "Nguồn: ", el("b", { text: state.usingSample ? "video_ui_sample.json (MẪU)" : String(state.dataUrl).replace(location.origin, "") })),
    el("span", { text: `Tập ${state.data.episode || L.MISSING} · ${L.domainLabel(state.data.domain)}` }),
    el("span", { text: "Chỉ đọc + ghi cài đặt vào graph. Không gửi /prompt, không chạy GPU." })));
  return el("div", { class: "ntd-body" }, kids);
}

function buildBar() {
  const d = state.data;
  dock.setBar({
    title: "VIDEO ENGINE",
    sub: d ? `${d.episode || L.MISSING} · ${L.domainLabel(d.domain)}${isMock() ? " · MẪU/MOCK" : ""}` : "đang nạp…",
    tabs: L.VIDEO_STEPS.map((s) => ({ code: s.code, label: s.label, on: s.code === state.step,
      onClick: () => { state.step = s.code; if (dock.prefs.mode === "collapsed") dock.setPrefs({ mode: "top" }); else render(); } })),
    tools: [el("button", { class: "ntd-tool", title: "Đọc lại index + dữ liệu tập", text: "TẢI LẠI",
      onclick: async () => { await loadIndex(); await loadData(graphInfo(), true); render(); } })],
  });
}

function render() {
  if (!dock) return;
  dock.show(state.active);
  if (!state.active) return;
  buildBar();
  if (!state.data) { dock.place(); return; }
  dock.setPanel(settingsCard(), bodyView());
}

async function tick() {
  const info = graphInfo();
  const on = Boolean(info && L.isVideoFlow(info.extra, info.groups, info.context));
  const sig = on ? (info.g.id || "") + "|" + info.groups.map((g) => g.title).join("|") : "";
  if (on !== state.active || sig !== state.sig) {
    state.active = on; state.sig = sig;
    if (on) {
      state.settings = null; state.dataRaw = ""; state.saved = null;
      state.data = null; // đổi graph: bỏ dữ liệu của graph trước, nếu không render() giữa chừng gặp settings=null và nổ
      render();
      await loadIndex();
      await loadData(info, true);
    }
    render();
    return;
  }
  if (on && performance.now() - state.lastFetch > DATA_REFRESH_MS) {
    if (await loadData(info)) render();
  }
  if (on) { dock.watch(); dock.place(); }
}

function init() {
  if (dock) return;
  dock = createDock({ key: "video", theme: "gold", barId: "ntv-bar", panelId: "ntv-panel", onChange: () => render() });
  let busy = false;
  setInterval(async () => {
    if (busy) return;
    busy = true;
    try { await tick(); } catch (err) { console.warn(`[${EXT}] tick`, err); } finally { busy = false; }
  }, POLL_MS);
}

app.registerExtension({
  name: EXT,
  async setup() { init(); },
  async afterConfigureGraph() { state.sig = "~"; },
});
