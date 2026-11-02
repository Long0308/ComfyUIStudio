// node tests/test_video_ui_logic.mjs — pure logic of the NEWTECONS VIDEO step panel.
import assert from "node:assert/strict";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as L from "../web/video_ui_logic.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../web");
const sampleRaw = JSON.parse(readFileSync(path.join(WEB, "video_ui_sample.json"), "utf8"));
const sample = L.normalizeState(sampleRaw, "sample");

const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}

test("activates only on extra.newtecons_flow == 'video'", () => {
  // Whitelist since S1: positives carry the NEWTECONS domain explicitly.
  assert.equal(L.isVideoFlow({ domain: "newtecons_live_action", newtecons_flow: "video" }), true);
  assert.equal(L.isVideoFlow({ domain: "newtecons_live_action", newtecons_flow: "image" }), false);
  assert.equal(L.isVideoFlow({ newtecons_flow: "video" }), false, "no domain signal = hidden");
  assert.equal(L.isVideoFlow({ domain: "newtecons_live_action", newtecons_h3: {} }), false); // legacy v003 keeps the old step bar
  assert.equal(L.isVideoFlow({ newtecons_image_8step: {} }), false);
  assert.equal(L.isVideoFlow(undefined), false);
  assert.equal(L.isVideoFlow("video"), false);
});

test("activates on extra.flow == 'video' and on the 5 video group titles", () => {
  assert.equal(L.isVideoFlow({ domain: "newtecons_live_action", flow: "video" }), true);
  assert.equal(L.isVideoFlow({ domain: "newtecons_live_action", flow: "image" }), false);
  const groups = L.VIDEO_STEPS.map((s) => ({ title: `${s.code} ${s.label}` }));
  assert.equal(L.isVideoFlow({ domain: "newtecons_live_action" }, groups), true);
  assert.equal(L.isVideoFlow({}, groups.slice(0, 4)), false);
  assert.equal(L.isVideoFlow({}, [{ title: "01 PROMPT" }, { title: "02 TẢI MODEL" }]), false);
});

test("real v003 video workflow groups activate; real image workflow does not", () => {
  const WF = path.resolve(here, "../../../user/default/workflows");
  const load = (f) => JSON.parse(readFileSync(path.join(WF, f), "utf8").replace(/^﻿/u, ""));
  const vid = load("NEWTECONS_H3/NEWTECONS_H3_R2V_LIVE_ACTION_v003_grouped.json");
  const img = load("NEWTECONS_IMAGE_8STEP/NEWTECONS_IMAGE_8STEP_v003_grouped.json");
  assert.equal(L.isVideoFlow(vid.extra, vid.groups), true);
  assert.equal(L.isVideoFlow(img.extra, img.groups), false);
  const v4 = path.join(WF, "NEWTECONS_H3");
  for (const f of readdirSync(v4).filter((x) => /v00[4-9].*grouped\.json$/u.test(x))) {
    const g = load("NEWTECONS_H3/" + f);
    assert.equal(L.isVideoFlow(g.extra, g.groups), true, f);
    results.push(["info", `activates on ${f}`]);
  }
});

test("episode index: valid entries kept with domain, bad ids dropped", () => {
  const ix = L.normalizeIndex({ schema: L.INDEX_SCHEMA, episodes: [
    { episode: "04-milk-and-mom", domain: "jenniejoy_cartoon_3d" },
    { episode: "NEWTECONS_EP05", domain: "newtecons_live_action", file: "NEWTECONS_EP05.json" },
    { episode: "../etc", domain: "x" }, "EP06",
  ] });
  assert.equal(ix.ok, true);
  assert.deepEqual(ix.episodes.map((e) => e.episode), ["04-milk-and-mom", "NEWTECONS_EP05", "EP06"]);
  assert.equal(ix.episodes[0].url, "/extensions/newtecons_step_ui/data/video/04-milk-and-mom.json");
  assert.equal(ix.errors.length, 1);
  assert.equal(L.normalizeIndex({ schema: "x" }).ok, false);
  assert.equal(L.domainLabel("jenniejoy_cartoon_3d"), "JennieJoyKids · 3D cartoon");
  assert.equal(L.domainLabel("newtecons_live_action"), "NEWTECONS · live-action");
  assert.equal(L.domainLabel(null), "domain chưa có");
});

test("JennieJoy styles never include live-action, and vice versa", () => {
  const jj = L.styleOptions("jenniejoy_cartoon_3d", ["Live-action người thật", "photoreal", "Pastel 3D"]);
  assert.ok(jj.every((o) => !/live|photo|người thật/iu.test(o.value + o.label)), JSON.stringify(jj));
  assert.ok(jj.some((o) => o.value === "Pastel 3D"));
  const jjState = L.normalizeState({ schema: L.SCHEMA, domain: "jenniejoy_cartoon_3d", shots: [] });
  const d = L.defaultSettings(jjState, { newtecons_video_ui: { style: "live_action_photoreal" } });
  assert.equal(d.style, "cartoon_3d");
  assert.equal(L.validateSettings({ ...d, style: "live_action_photoreal" }, jjState).ok, false);
  const noDomain = L.normalizeState({ schema: L.SCHEMA, shots: [] });
  assert.deepEqual(L.styleOptions(noDomain.domain), []);
  assert.ok(L.validateSettings(L.defaultSettings(noDomain, {}), noDomain).errors.includes("Dữ liệu tập chưa ghi domain"));
});

test("data/video/index.json (if present) lists exactly the episode files on disk", () => {
  const dir = path.join(WEB, "data", "video");
  const ixPath = path.join(dir, "index.json");
  if (!existsSync(ixPath)) { results.push(["info", "data/video/index.json chưa có"]); return; }
  const ix = L.normalizeIndex(JSON.parse(readFileSync(ixPath, "utf8").replace(/^﻿/u, "")));
  assert.equal(ix.ok, true, ix.errors.join("; "));
  const onDisk = readdirSync(dir).filter((f) => f.endsWith(".json") && f !== "index.json").sort();
  const listed = ix.episodes.map((e) => decodeURIComponent(e.url.split("/").pop())).sort();
  assert.deepEqual(listed, onDisk);
  for (const e of ix.episodes) {
    const st = L.normalizeState(JSON.parse(readFileSync(path.join(dir, decodeURIComponent(e.url.split("/").pop())), "utf8").replace(/^﻿/u, "")));
    assert.equal(st.domain, e.domain, `${e.episode}: index domain ${e.domain} != file domain ${st.domain}`);
  }
});

test("5 steps in order with the reference labels", () => {
  assert.deepEqual(L.VIDEO_STEPS.map((s) => `${s.code} ${s.label}`),
    ["01 ĐỌC SHOTLIST", "02 VIẾT PROMPT", "03 AI QUAY VIDEO", "04 LÊN 1080P", "05 LƯU & QUAY TIẾP"]);
});

test("sample validates, is flagged sample, NEWTECONS 864x480 -> 1920x1080 @24", () => {
  assert.equal(sample.ok, true, sample.errors.join("; "));
  assert.deepEqual(sample.errors, []);
  assert.equal(sample.sample, true);
  assert.match(sample.sampleNote, /không phải dữ liệu thật/u);
  assert.deepEqual(sample.native, { w: 864, h: 480 });
  assert.deepEqual(sample.export, { w: 1920, h: 1080 });
  assert.equal(sample.fps, 24);
  assert.equal(sample.shots.length, 8);
});

test("sample has no real media URLs (nothing invented)", () => {
  for (const s of sample.shots) {
    assert.equal(s.native_url, null); assert.equal(s.hd_url, null); assert.equal(s.thumb_url, null);
    assert.ok(s.refs.every((r) => r.url === null));
  }
});

test("unknown status is never coerced; missing status stays null", () => {
  const st = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "A", status: "done" }, { id: "B" }, { id: "C", status: "accepted" }] });
  assert.equal(st.shots[0].status, null);
  assert.equal(st.shots[0].statusRaw, "done");
  assert.equal(L.statusText(st.shots[0]), "không rõ (done)");
  assert.ok(st.errors.some((e) => /status lạ: done/u.test(e)));
  assert.equal(st.shots[1].status, null);
  assert.equal(L.statusText(st.shots[1]), "chưa có");
  assert.equal(L.statusText(st.shots[2]), "Đã duyệt");
});

test("wrong schema / bad payload -> not ok with reason", () => {
  assert.equal(L.normalizeState({ schema: "x", shots: [] }).ok, false);
  assert.equal(L.normalizeState(null).ok, false);
  const dup = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "A" }, { id: "A" }] });
  assert.ok(dup.errors.some((e) => /trùng/u.test(e)));
});

test("shot caption matches reference wording, missing -> chưa có", () => {
  const s = sample.shots.find((x) => x.id === "S02_A");
  assert.equal(L.shotCaption(s), "Trung toàn · Góc cao · Kéo máy ra · 1,6 giây");
  assert.equal(L.shotCaption({}), "chưa có · chưa có · chưa có · chưa có");
  assert.equal(L.formatSeconds(2), "2 giây");
});

test("progress counts upscaled_1080/accepted WITH hd_url only", () => {
  // sample has 1080p statuses but no hd_url -> 0 done (no invented files)
  assert.equal(L.progress(sample.shots).label, "00 / 08");
  const st = L.normalizeState({ schema: L.SCHEMA, shots: [
    { id: "a", status: "accepted", hd_url: "/view?filename=a.mp4" },
    { id: "b", status: "upscaled_1080", hd_url: "/view?filename=b.mp4" },
    { id: "c", status: "rendered", hd_url: "/view?filename=c.mp4" },
    { id: "d", status: "upscaled_1080" },
    ...Array.from({ length: 39 }, (_, i) => ({ id: "p" + i, status: "planned" })),
  ] });
  const p = L.progress(st.shots);
  assert.equal(p.label, "02 / 43");
  assert.equal(p.accepted, 1);
  assert.ok(Math.abs(p.pct - 2 / 43) < 1e-9);
  assert.equal(L.progress([]).label, "00 / 00");
});

test("QA fix 1: tab 05 has TWO explicit counters (1080p vs duyệt) — no 00/08 vs đã duyệt 1 clash", () => {
  const p = L.progress(sample.shots);
  assert.equal(p.producedLabel, "00 / 08"); // 1080p statuses exist but no hd_url file in the sample
  assert.equal(p.acceptedLabel, "01 / 08"); // S01_C accepted
  assert.deepEqual(p.pendingReview, ["S01_A", "S01_B"]);
  assert.deepEqual(p.stateOnly, ["S01_A", "S01_B", "S01_C"]);
  const st = L.normalizeState({ schema: L.SCHEMA, shots: [
    { id: "a", status: "accepted", hd_url: "/view?filename=a.mp4" },
    { id: "b", status: "upscaled_1080", hd_url: "/view?filename=b.mp4" },
    { id: "c", status: "planned" },
  ] });
  const q = L.progress(st.shots);
  assert.equal(q.producedLabel, "02 / 03");
  assert.equal(q.acceptedLabel, "01 / 03");
  assert.deepEqual(q.pendingReview, ["b"]);
  assert.ok(q.accepted <= q.total && q.produced <= q.total);
});

test("QA fix 1b: review-pending gate (chờ duyệt cuối lượt) — engine gate wins, else derived", () => {
  const g = L.reviewGate(sample);
  assert.equal(g.name, "review-pending");
  assert.equal(g.label, "Chờ duyệt cuối lượt");
  assert.deepEqual(g.pending, ["S01_A", "S01_B"]);
  assert.equal(g.derived, true);
  const eng = L.normalizeState({ schema: L.SCHEMA, gate: { name: "review-pending", message: "all shots produced", pending: ["S02"] }, shots: [] });
  assert.equal(L.reviewGate(eng).pending[0], "S02");
  assert.equal(L.reviewGate(eng).derived, undefined);
  const odd = L.normalizeState({ schema: L.SCHEMA, gate: { name: "made-up" }, shots: [] });
  assert.equal(odd.gate.label, "không rõ (made-up)");
  assert.ok(odd.errors.some((e) => /gate lạ/u.test(e)));
  assert.equal(L.reviewGate(L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "x", status: "planned" }] })), null);
  for (const k of ["gpu-approval", "needs-gpu-pilot-approval", "take-acceptance", "review-pending", "final-review"]) assert.ok(L.GATE_LABEL[k], k);
});

test("QA fix 2: seed shows chưa có unless data/extra carries one", () => {
  assert.equal(sample.seed, null);
  assert.equal(L.defaultSettings(sample, {}).seed, null);
  const withSeed = L.normalizeState({ ...sampleRaw, seed: 42 });
  assert.equal(L.defaultSettings(withSeed, {}).seed, 42);
  assert.equal(L.defaultSettings(sample, { newtecons_video_ui: { seed: 9 } }).seed, 9);
  assert.equal(L.normalizeState({ ...sampleRaw, seed: -3 }).seed, null);
  const v = L.validateSettings(L.defaultSettings(sample, {}), sample);
  assert.equal(v.ok, true, v.errors.join("; "));
  assert.equal(v.value.seed, null);
});

test("mock/sample data is always flagged (banner + write lock source)", () => {
  assert.equal(L.isSampleData(sample), true);
  assert.equal(L.isSampleData(L.normalizeState({ schema: L.SCHEMA, sample: true, shots: [] }, "http://x")), true);
  assert.equal(L.isSampleData(L.normalizeState({ schema: L.SCHEMA, shots: [] }, "/extensions/x.json")), false);
});

test("v4: per-shot wardrobe context / refused rendered, never guessed", () => {
  const st = L.normalizeState({ schema: L.SCHEMA, shots: [
    { id: "a", wardrobe: { context: "cong_truong", refs: [{ name: "áo", url: "/view?filename=a.png&type=input" }], refused: null } },
    { id: "b", wardrobe: { context: null, refs: [], refused: "WARDROBE_CONTEXT_UNKNOWN: shot 'b' has no site/office context" } },
    { id: "c" },
    { id: "d", wardrobe: { context: null, refs: [] } },
  ] });
  assert.equal(L.wardrobeText(st.shots[0]), "CÔNG TRƯỜNG · 1 ref");
  assert.equal(L.wardrobeText(st.shots[1]), "TỪ CHỐI (WARDROBE_CONTEXT_UNKNOWN)");
  assert.match(st.shots[1].wardrobe.refused, /no site\/office/u);
  assert.equal(L.wardrobeText(st.shots[2]), "chưa có");
  assert.equal(L.wardrobeText(st.shots[3]), "chưa có");
  const ep5 = path.join(WEB, "data/video/Newtecons-TienDo-KichTinh-30s.json");
  if (existsSync(ep5)) {
    const real = L.normalizeState(JSON.parse(readFileSync(ep5, "utf8").replace(/^﻿/u, "")));
    assert.ok(real.shots.every((x) => x.wardrobe === null || typeof x.wardrobe === "object"));
    results.push(["info", "EP05 wardrobe: " + real.shots.map((x) => `${x.id}=${L.wardrobeText(x)}`).join(", ")]);
  }
});

test("v4.1: old pilot inputs (ĐIỀN: … / h3-…) are never shot references; legacy only as a note", () => {
  const st = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "S02_A", refs: [
    { name: "ĐIỀN: ảnh nhân vật NEWTECONS đã duyệt — ref Picture 1", url: "/view?filename=h3-dcb0789a.png&type=input" },
    { name: "ĐIỀN: ảnh cảnh đã duyệt — neo frame 0", url: "/view?filename=h3-6e5e4d6e.jpg&type=input" },
    { name: "x.png", url: "/view?filename=h3-abc.png&type=input" },
    { name: "04_04_DECISIVE_COMMAND.png", url: "/view?filename=04_04_DECISIVE_COMMAND.jpg&subfolder=engine-library-r005f/CHAR_02/FACE&type=input" },
  ], legacy_refs: [{ name: "old storyboard", url: "/view?filename=h3-zzz.jpg", blocked: true }],
    anchor_pack: { status: "candidate", context: "cong_truong", ready_for_graph: false } }] });
  const s0 = st.shots[0];
  assert.deepEqual(s0.refs.map((r) => r.name), ["04_04_DECISIVE_COMMAND.png"]);
  assert.equal(s0.legacy.length, 4, "3 guarded refs + 1 legacy_refs entry");
  assert.ok(s0.legacy.every((r) => r.url === null), "legacy entries never carry a renderable url");
  assert.equal(L.legacyNote(s0), "ảnh cũ chưa duyệt — không dùng (4)");
  assert.equal(L.anchorText(s0), "BỘ NEO: candidate (chưa duyệt) · CÔNG TRƯỜNG · chưa sẵn sàng cho graph");
  assert.equal(L.isLegacyRef({ name: "ĐIỀN: abc" }), true);
  assert.equal(L.isLegacyRef({ name: "a.png", url: "/view?filename=h3-1.png" }), true);
  assert.equal(L.isLegacyRef({ name: "h3-raw.png" }), true);
  assert.equal(L.isLegacyRef({ name: "CHAR_02_h3-ok.png", url: "/view?filename=CHAR_02_h3.png" }), false);
  const clean = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "a", refs: [{ name: "a.png", url: "/view?filename=a.png" }] }] }).shots[0];
  assert.equal(L.legacyNote(clean), null);
  assert.equal(L.anchorText(clean), null);
  assert.equal(L.anchorText(L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "b", anchor_pack: { status: "approved", context: "van_phong", ready_for_graph: true } }] }).shots[0]),
    "BỘ NEO: approved · VĂN PHÒNG · sẵn sàng cho graph");
});

test("v4.1: real EP05 data — no S02_A reference is an old pilot input", () => {
  const f = path.join(WEB, "data/video/Newtecons-TienDo-KichTinh-30s.json");
  if (!existsSync(f)) return;
  const st = L.normalizeState(JSON.parse(readFileSync(f, "utf8").replace(/^\uFEFF/u, "")));
  for (const sh of st.shots) {
    const bad = sh.refs.filter((r) => /^ĐIỀN:/u.test(r.name) || /[?&]filename=h3-/u.test(r.url || ""));
    assert.deepEqual(bad.map((r) => r.name), [], sh.id);
  }
  const s2 = st.shots.find((x) => x.id === "S02_A");
  if (s2) results.push(["info", `S02_A refs ${s2.refs.length} · legacy ${s2.legacy.length} · ${L.anchorText(s2)}`]);
});

// v4.2 fixture: anchor_pack.staged as Fable will write it ([{slot, role, input_subfolder, filename, sha256}]).
const SHA = (c) => c.repeat(64);
const STAGED = [
  { slot: "ref_images.ref_image_0", role: "face", input_subfolder: "", filename: "newtecons_ch_CHAR_02_2f01be018cab.png", sha256: SHA("a") },
  { slot: "ref_images.ref_image_3", role: "body", input_subfolder: "newtecons-anchor/EP05/S02_A", filename: "body1.png", sha256: SHA("b") },
  { slot: "guide.image", role: "storyboard", input_subfolder: "", filename: "sb.png", sha256: SHA("c") },
  { slot: "ref_images.ref_image_5", role: "wardrobe", input_subfolder: "", filename: "helmet.png", sha256: SHA("d") },
  { slot: "ref_images.ref_image_9", role: "extra", input_subfolder: "", filename: "nowhere.png", sha256: SHA("e") },
  { slot: "ref_images.ref_image_6", role: "legacy", input_subfolder: "", filename: "h3-dcb0789a.png", sha256: SHA("f") },
  { slot: "ref_images.ref_image_7", role: "bad", input_subfolder: "../etc", filename: "x.png", sha256: SHA("1") },
  { slot: "ref_images.ref_image_8", role: "bad", input_subfolder: "", filename: "y.png", sha256: "nothex" },
];
const ANCHOR_NODES = [
  { id: 5, type: "LoadImage", title: "NEO MẶT 1", mode: 0, properties: { nt_anchor_slot: "ref_images.ref_image_0" }, widgets: { image: "" } },
  { id: 37, type: "LoadImage", title: "NEO MẶT 2", mode: 2, properties: { nt_anchor_slot: "ref_images.ref_image_1" }, widgets: { image: "" } },
  { id: 39, type: "LoadImage", title: "NEO DÁNG 1", mode: 2, properties: { nt_anchor_slot: "ref_images.ref_image_3" }, widgets: { image: "" } },
  { id: 8, type: "LoadImage", title: "STORYBOARD", mode: 0, properties: { nt_anchor_slot: "guide.image" }, widgets: { image: "" } },
  { id: 32, type: "LoadImage", title: "MŨ", mode: 0, properties: { nt_anchor_slot: "ref_images.ref_image_5" }, widgets: { image: "" } },
  { id: 33, type: "LoadImage", title: "LOGO", mode: 0, properties: { nt_anchor_slot: "ref_images.ref_image_6" }, widgets: { image: "" } },
  { id: 35, type: "LoadImage", title: "BỐI CẢNH", mode: 2, properties: {}, widgets: { image: "" } },
];

test("v4.2: staged entries are validated; legacy/unsafe/bad-sha never used", () => {
  const st = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "S02_A", anchor_pack: { status: "candidate", staged: STAGED } }] });
  const sg = st.shots[0].anchor.staged;
  assert.deepEqual(sg.map((e) => e.slot), ["ref_images.ref_image_0", "ref_images.ref_image_3", "guide.image", "ref_images.ref_image_5", "ref_images.ref_image_9"]);
  assert.equal(sg[0].value, "newtecons_ch_CHAR_02_2f01be018cab.png", "root file -> bare filename (as the image lane fills NEO slots)");
  assert.equal(sg[1].value, "newtecons-anchor/EP05/S02_A/body1.png");
  assert.deepEqual(sg[1].ref, { filename: "body1.png", subfolder: "newtecons-anchor/EP05/S02_A", type: "input" });
  assert.equal(st.shots[0].anchor.stagedRejected, 3);
});

test("v4.2: anchor plan — match by nt_anchor_slot, fill+unmute verified slots, mute empty/missing/mismatch", () => {
  const sg = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "S02_A", anchor_pack: { staged: STAGED } }] }).shots[0].anchor.staged;
  const checks = {
    [sg[0].value]: { exists: true, sha256: SHA("a") },
    [sg[1].value]: { exists: true, sha256: SHA("b") },
    [sg[2].value]: { exists: false },
    [sg[3].value]: { exists: true, sha256: SHA("0") },
  };
  const plan = L.anchorPlan(ANCHOR_NODES, sg, checks);
  const by = Object.fromEntries(plan.rows.map((r) => [r.nodeId, r]));
  assert.equal(by[5].status, "loaded"); assert.equal(by[5].value, sg[0].value); assert.equal(by[5].mode, 0);
  // Measured 31/10 on ComfyUI 1.55: a "sub/file.png" LoadImage value previews but the frontend marks the node Error
  // ("Media input missing"); root files work. So subfolder entries are never filled.
  assert.equal(by[39].status, "needs_root"); assert.equal(by[39].mode, 2); assert.equal(by[39].value, null);
  assert.equal(L.anchorStatusLabel("needs_root"), "cần file ở gốc input/");
  assert.equal(by[8].status, "missing_file"); assert.equal(by[8].mode, 2); assert.equal(by[8].value, null);
  assert.equal(by[32].status, "sha_mismatch"); assert.equal(by[32].mode, 2); assert.equal(by[32].value, null);
  assert.equal(by[37].status, "empty"); assert.equal(by[37].mode, 2);
  assert.equal(by[33].status, "empty", "legacy h3- entry for slot 6 was rejected, slot stays empty");
  assert.equal(by[35], undefined, "nodes without nt_anchor_slot are never touched");
  assert.deepEqual(plan.orphans.map((e) => e.slot), ["ref_images.ref_image_9"]);
  assert.equal(plan.ready, false);
  assert.equal(L.anchorStatusLabel("loaded"), "đã nạp");
  assert.equal(L.anchorStatusLabel("missing_file"), "thiếu file");
  assert.equal(L.anchorStatusLabel("sha_mismatch"), "sha lệch");
  const unchecked = L.anchorPlan(ANCHOR_NODES, sg, {});
  assert.ok(unchecked.rows.filter((r) => r.entry && !r.entry.subfolder).every((r) => r.status === "unchecked" && r.value === null), "never fill before the file is verified");
  assert.ok(unchecked.rows.filter((r) => r.entry).every((r) => r.value === null));
});

test("v4.2: ready only when every staged slot with a node is verified", () => {
  const rootBody = { ...STAGED[1], input_subfolder: "", filename: "newtecons_anc_S02_A_body1.png" };
  const sg = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "a", anchor_pack: { staged: [STAGED[0], rootBody] } }] }).shots[0].anchor.staged;
  const ok = { [sg[0].value]: { exists: true, sha256: SHA("a") }, [sg[1].value]: { exists: true, sha256: SHA("b") } };
  const withSub = L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "c", anchor_pack: { staged: STAGED.slice(0, 2) } }] }).shots[0].anchor.staged;
  assert.equal(L.anchorPlan(ANCHOR_NODES, withSub, { ...ok, [withSub[1].value]: { exists: true, sha256: SHA("b") } }).ready, false, "a subfolder entry blocks auto-apply");
  const plan = L.anchorPlan(ANCHOR_NODES, sg, ok);
  assert.equal(plan.ready, true);
  assert.equal(plan.applied, false, "not yet written into the nodes");
  const after = ANCHOR_NODES.map((n) => { const r = plan.rows.find((x) => x.nodeId === n.id); return r ? { ...n, mode: r.mode, widgets: { image: r.value ?? "" } } : n; });
  assert.equal(L.anchorPlan(after, sg, ok).applied, true);
  assert.equal(L.anchorPlan(ANCHOR_NODES, [], ok).ready, false, "nothing staged = not ready (no auto-apply)");
  assert.equal(L.normalizeState({ schema: L.SCHEMA, shots: [{ id: "b", anchor_pack: { status: "candidate" } }] }).shots[0].anchor.staged.length, 0);
});

test("nextShot: auto = first without native video; selected_only = the selected", () => {
  assert.equal(L.nextShot(sample.shots, "auto_pending", null).id, "S02_A");
  assert.equal(L.nextShot(sample.shots, "auto_pending", null, "S03").id, "S03_A");
  assert.equal(L.nextShot(sample.shots, "selected_only", "S01_C").id, "S01_C");
  assert.equal(L.nextShot(sample.shots, "selected_only", "NOPE"), null);
  assert.equal(L.defaultSelected(sample.shots), "S02_A");
  assert.deepEqual(L.scenes(sample.shots), ["S01", "S02", "S03", "S04"]);
});

test("ratio and size labels are measured, not assumed 16:9", () => {
  assert.equal(L.ratioLabel({ w: 864, h: 480 }), "9:5");
  assert.equal(L.ratioLabel({ w: 1920, h: 1080 }), "16:9");
  assert.equal(L.sizeLabel(null), "chưa có");
});

test("NEWTECONS styles never include cartoon, even if data offers it", () => {
  const opts = L.styleOptions("newtecons_live_action", ["3D cartoon", { value: "anime", label: "Anime" }, "Phim tài liệu"]);
  assert.ok(opts.length >= 1);
  assert.ok(opts.every((o) => !/cartoon|anime/iu.test(o.value + o.label)));
  assert.ok(opts.some((o) => o.value === "Phim tài liệu"));
  assert.ok(L.styleOptions("jenniejoy_cartoon_3d").some((o) => /cartoon/u.test(o.value)));
});

test("safeUrl keeps served paths, rejects javascript:/external/traversal", () => {
  assert.equal(L.safeUrl("/view?filename=a.mp4&type=output"), "/view?filename=a.mp4&type=output");
  assert.equal(L.safeUrl("/extensions/newtecons_step_ui/data/video/x.png"), "/extensions/newtecons_step_ui/data/video/x.png");
  assert.equal(L.safeUrl("data/video/x.png"), "/extensions/newtecons_step_ui/data/video/x.png");
  assert.equal(L.safeUrl("http://127.0.0.1:8188/view?x"), "http://127.0.0.1:8188/view?x");
  assert.equal(L.safeUrl("javascript:alert(1)"), null);
  assert.equal(L.safeUrl("https://evil.example/x.png"), null);
  assert.equal(L.safeUrl("//evil.example/x.png"), null);
  assert.equal(L.safeUrl("../../secret"), null);
  assert.equal(L.safeUrl(""), null);
});

test("dataUrl / episode id are sanitised", () => {
  assert.equal(L.dataUrl("NEWTECONS_EP05"), "/extensions/newtecons_step_ui/data/video/NEWTECONS_EP05.json");
  assert.equal(L.dataUrl("../x"), null);
  assert.equal(L.dataUrl("a/b"), null);
  assert.equal(L.episodeFromExtra({ newtecons_video_ui: { episode: "EP05" } }), "EP05");
  assert.equal(L.episodeFromExtra({ newtecons_video: { episode: "EP06" } }), "EP06");
  assert.equal(L.episodeFromExtra({ newtecons_video_ui: { episode: "../x" } }), null);
});

test("settings: defaults, validation, never submits GPU", () => {
  const d = L.defaultSettings(sample, {});
  assert.equal(d.run_mode, "auto_pending");
  assert.equal(d.style, "live_action_photoreal");
  assert.equal(d.seed_mode, "fixed");
  const v = L.validateSettings(d, sample);
  assert.equal(v.ok, true, v.errors.join("; "));
  assert.equal(v.value.submits_gpu, false);
  assert.deepEqual(v.value.native, { w: 864, h: 480 });
  const bad = L.validateSettings({ ...d, seed: -1, style: "cartoon_3d", run_mode: "selected_only", shot: "" }, sample);
  assert.equal(bad.ok, false);
  assert.equal(bad.errors.length, 3);
  assert.equal(L.validateSettings({ ...d, shot: "ZZ" }, sample).ok, false);
  const kept = L.defaultSettings(sample, { newtecons_video_ui: { seed: 7, seed_mode: "randomize", style: "cartoon_3d" } });
  assert.equal(kept.seed, 7); assert.equal(kept.seed_mode, "randomize"); assert.equal(kept.style, "live_action_photoreal");
});

test("findJobNode only matches marked/titled text nodes", () => {
  const nodes = [
    { id: 1, type: "PrimitiveStringMultiline", title: "Prompt người thật" },
    { id: 2, type: "Note", title: "JOB ghi chú" },
    { id: 3, type: "PrimitiveStringMultiline", title: "JOB — cài đặt video" },
  ];
  assert.equal(L.findJobNode(nodes).id, 3);
  assert.equal(L.findJobNode([{ id: 9, type: "PrimitiveString", title: "x", properties: { newtecons_video_job: true } }]).id, 9);
  assert.equal(L.findJobNode(nodes.slice(0, 2)), null);
});

test("stepIO: 03 RA = native video or null; 04 has ×3 zoom both sides; 05 RA progress", () => {
  const s = { prompt: "p", refs: [{}, {}], native_url: "/view?n", hd_url: null };
  const io3 = L.stepIO("03", sample, s);
  assert.equal(io3.out.url, "/view?n");
  assert.match(io3.out.caption, /864×480/u);
  const io4 = L.stepIO("04", sample, s);
  assert.equal(io4.in.zoom, 3); assert.equal(io4.out.zoom, 3); assert.equal(io4.out.url, null);
  assert.equal(io4.in.size, "native"); assert.equal(io4.out.size, "export"); assert.equal(io3.out.size, "native");
  assert.match(io4.out.caption, /1920×1080/u);
  assert.equal(L.stepIO("02", sample, s).out.refs, 2);
  assert.equal(L.stepIO("05", sample, s).out.kind, "progress");
  assert.equal(L.stepIO("09", sample, s), null);
});

test("zoomCrop is a centred 1/3 window", () => {
  assert.deepEqual(L.zoomCrop(864, 480, 3), { x: 288, y: 160, w: 288, h: 160 });
});

test("fitBounds puts the group inside the free area", () => {
  const b = [1680, 0, 1750, 1296];
  const { scale, offset } = L.fitBounds(b, { width: 1600, height: 900 }, { top: 100, margin: 20 });
  const sx = (x) => (x + offset[0]) * scale;
  const sy = (y) => (y + offset[1]) * scale;
  assert.ok(sx(b[0]) >= 20 - 1e-6 && sx(b[0] + b[2]) <= 1580 + 1e-6);
  assert.ok(sy(b[1]) >= 120 - 1e-6 && sy(b[1] + b[3]) <= 880 + 1e-6);
  assert.equal(L.groupForStep([{ title: "03 AI QUAY VIDEO" }], "03").title, "03 AI QUAY VIDEO");
});

test("real data files (if Fable wrote any) validate against the schema", () => {
  const dir = path.join(WEB, "data", "video");
  const files = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".json") && f !== "index.json") : [];
  for (const f of files) {
    const st = L.normalizeState(JSON.parse(readFileSync(path.join(dir, f), "utf8").replace(/^﻿/u, "")), f);
    assert.equal(st.ok, true, `${f}: ${st.errors.join("; ")}`);
  }
  results.push(["info", `data/video files checked: ${files.length}`]);
});

test("audio: SFX default follows the domain; the block carries sfx_enabled + mute_stems", () => {
  assert.equal(L.audioDefaults(undefined, "newtecons_live_action").sfx_enabled, true);
  assert.equal(L.audioDefaults(undefined, "jenniejoy_cartoon_3d").sfx_enabled, false);
  assert.equal(L.audioDefaults({ sfx_enabled: false }, "newtecons_live_action").sfx_enabled, false);
  assert.equal(L.sfxLabel(true), "SFX: BẬT");
  assert.equal(L.sfxLabel(false), "SFX: TẮT");
  assert.deepEqual(L.audioBlock({ sfx_enabled: false, mute_voice: false, mute_music: true }), { sfx_enabled: false, mute_stems: ["music"] });
  const st = L.normalizeState(sampleRaw, "sample");
  const v = L.validateSettings({ ...L.defaultSettings(st, {}), sfx_enabled: false }, st);
  assert.deepEqual(v.value.audio, { sfx_enabled: false, mute_stems: [] });
});

// ---- media overlay (poster / 1440 / final film from receipts on disk) ----
const MEDIA = { schema: "jjv/video-ui-media/v1", episode: "ep-x", shots: { S1: { thumb_url: "/view?filename=p.jpg&subfolder=a&type=output",
  hd_url: "/view?filename=h.mp4&subfolder=a&type=output", logo_url: "/view?filename=l.mp4&subfolder=a&type=output", note: "n" } },
  final: { exists: true, label: "Phim cuối", url: "/view?filename=f.mp4&subfolder=a&type=output", bytes: 5 } };
const RAW = { schema: "jjv/video-ui-state/v1", episode: "ep-x", domain: "newtecons_live_action", shots: [{ id: "S1", status: "rendered", native_url: "/view?filename=n.mp4&subfolder=a&type=output" }, { id: "S2", status: "planned" }] };

test("applyMedia: fills thumb/hd/final for the same episode only; engine urls win; shots without media stay empty", () => {
  const st = L.applyMedia(L.normalizeState(RAW, "x"), MEDIA);
  assert.match(st.shots[0].thumb_url, /p\.jpg/u);
  assert.match(st.shots[0].hd_url, /h\.mp4/u);
  assert.equal(st.shots[0].hdFromMedia, true);
  assert.equal(st.shots[1].hd_url, null);
  assert.match(st.finalFilm.url, /f\.mp4/u);
  const own = L.normalizeState({ ...RAW, shots: [{ ...RAW.shots[0], hd_url: "/view?filename=own.mp4&subfolder=a&type=output" }] }, "x");
  assert.match(L.applyMedia(own, MEDIA).shots[0].hd_url, /own\.mp4/u);
  const other = L.applyMedia(L.normalizeState(RAW, "x"), { ...MEDIA, episode: "other" });
  assert.equal(other.shots[0].hd_url, null);
  assert.equal(other.finalFilm, null);
  assert.equal(L.applyMedia(L.normalizeState(RAW, "x"), null).finalFilm, null);
});

for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.filter((r) => r[0] === "ok").length}/${results.filter((r) => r[0] !== "info").length} passed`);
process.exit(failed ? 1 : 0);
