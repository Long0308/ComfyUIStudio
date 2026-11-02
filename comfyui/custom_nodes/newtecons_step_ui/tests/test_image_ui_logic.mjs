// node tests/test_image_ui_logic.mjs — IMAGE panel logic against the real workflows + data files.
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as L from "../web/image_ui_logic.js";
import * as S from "../web/step_ui_logic.js";
const { planChanges, routePlan } = S;

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../web");
const WF = path.resolve(here, "../../../user/default/workflows");
const WIDGETS = { LoadImage: ["image"], SaveImage: ["filename_prefix"], PrimitiveStringMultiline: ["value"], CLIPTextEncode: ["text"], ComfySwitchNode: ["switch"] };
const load = (p) => JSON.parse(readFileSync(p, "utf8").replace(/^﻿/u, ""));
function snap(file) {
  const g = load(path.join(WF, file));
  return { extra: g.extra, groups: g.groups, nodes: g.nodes.map((n) => ({ id: n.id, type: n.type, title: n.title, mode: n.mode || 0, pos: n.pos,
    properties: n.properties || {}, widgets: Object.fromEntries((WIDGETS[n.type] || []).map((k, i) => [k, n.widgets_values?.[i]])) })) };
}

const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}

// The image lane renames revisions (v004 -> v004r1): pick the newest v004* file instead of a fixed name.
const V4_NAME = readdirSync(path.join(WF, "NEWTECONS_IMAGE_8STEP")).filter((f) => /^NEWTECONS_IMAGE_8STEP_v004.*_grouped\.json$/u.test(f)).sort().at(-1);
const v4 = snap("NEWTECONS_IMAGE_8STEP/" + V4_NAME);
const v3 = snap("NEWTECONS_IMAGE_8STEP/NEWTECONS_IMAGE_8STEP_v003_grouped.json");
const vid = snap("NEWTECONS_H3/NEWTECONS_H3_R2V_LIVE_ACTION_v003_grouped.json");
const steps4 = L.parseSteps(v4.groups);

test("activates on image graphs, never on the video graph", () => {
  assert.equal(L.isImageFlow(v4.extra, v4.groups), true);
  assert.equal(L.isImageFlow(v3.extra, v3.groups), true);
  assert.equal(L.isImageFlow(vid.extra, vid.groups), false);
  // Whitelist since S1: positives must carry the NEWTECONS domain explicitly; an unknown domain hides the bar.
  assert.equal(L.isImageFlow({ domain: "newtecons_live_action", flow: "image" }, []), true);
  assert.equal(L.isImageFlow({ domain: "newtecons_live_action", flow: "video" }, v4.groups), false);
  assert.equal(L.isImageFlow({}, [{ title: "01 PROMPT", bounding: [0, 0, 1, 1] }]), false);
  assert.equal(L.isImageFlow({ domain: "newtecons_live_action" }, v4.groups), true, "group titles alone are enough");
});

test("tabs = group titles in graph order (v004: 00 … 09)", () => {
  assert.deepEqual(steps4.map((s) => s.code), ["00", "01", "02", "02B", "03", "04", "05", "06", "07", "08", "09"]);
  assert.equal(steps4[0].label, "CHỌN LUỒNG");
  assert.equal(steps4.at(-1).label, "DUYỆT & UPSCALE");
});

test("graph order follows layout: 02A/02B placed before 02 come first", () => {
  const g = [{ title: "02 ASSET 4 GÓC", bounding: [3000, 0, 10, 10] }, { title: "02A NEO TRANG PHỤC", bounding: [1000, 0, 10, 10] },
    { title: "02B THAM CHIẾU NHÂN VẬT", bounding: [2000, 0, 10, 10] }, { title: "01 PROMPT", bounding: [0, 0, 10, 10] }];
  assert.deepEqual(L.parseSteps(g).map((s) => s.code), ["01", "02A", "02B", "02"]);
});

test("VÀO = LoadImage files actually set + prompt text", () => {
  const ref = L.stepInputs(v4, steps4.find((s) => s.code === "02B"));
  assert.deepEqual(ref.images.map((i) => i.ref.filename).sort(), ["newtecons_ref_face_f01d89535c5.webp", "newtecons_ref_pose_full_single_P017_front.png"]);
  const prompt = L.stepInputs(v4, steps4.find((s) => s.code === "01"));
  assert.ok(prompt.prompts.some((p) => /NEWTECONS/u.test(p.text)));
  const unset = L.stepInputs(v4, steps4.find((s) => s.code === "02"));
  assert.equal(unset.images[0].ref, null, "empty LoadImage stays 'chưa chọn file'");
});

test("RA: output nodes + history matching (strong beats newer weak; preview needs strong)", () => {
  const s07 = steps4.find((s) => s.code === "07");
  const outs = L.outputNodesForStep(v4, s07);
  const save = outs.find((o) => o.type === "SaveImage");
  const prev = outs.find((o) => o.type === "PreviewImage");
  const sig = L.groupSignature(v4.groups);
  const media = (f) => ({ images: [{ filename: f, subfolder: "NEWTECONS", type: "output" }] });
  const call = (cls, prefix) => ({ class_type: cls, inputs: prefix ? { filename_prefix: prefix } : {} });
  const h = {
    a: { prompt: [1, "a", { [save.nodeId]: call("SaveImage", save.prefix) }, { extra_pnginfo: { workflow: { groups: v4.groups } } }], outputs: { [save.nodeId]: media("a.png") } },
    b: { prompt: [5, "b", { [save.nodeId]: call("SaveImage", save.prefix) }, {}], outputs: { [save.nodeId]: media("b.png") } },
    c: { prompt: [7, "c", { [prev.nodeId]: call("PreviewImage") }, {}], outputs: { [prev.nodeId]: media("c.png") } },
  };
  assert.equal(L.latestOutput(h, outs, sig).promptId, "a");
  delete h.a;
  assert.equal(L.latestOutput(h, outs, sig).match, "weak");
  assert.equal(L.latestOutput(h, [prev], sig), null);
});

test("characters data: 8 characters with face refs under input/", () => {
  const f = path.join(WEB, "data/characters/newtecons_live_action.json");
  if (!existsSync(f)) { results.push(["info", "data/characters chưa có"]); return; }
  const c = L.parseCharacters(load(f));
  assert.equal(c.ok, true, c.errors.join("; "));
  assert.deepEqual(c.list.map((x) => x.id), L.CHAR_IDS);
  assert.ok(c.list.every((x) => x.refs.length > 0 && x.refs.every((r) => r.ref.type === "input" && r.ref.filename)));
  const none = L.parseCharacters(null);
  assert.equal(none.ok, false);
  assert.equal(none.list.length, 8);
});

test("wardrobe data: CÔNG TRƯỜNG / VĂN PHÒNG contexts with files", () => {
  const w = L.parseWardrobe(load(path.join(WEB, "data/wardrobe/newtecons_live_action.json")));
  assert.equal(w.ok, true);
  assert.ok(w.contexts.some((c) => c.label === "CÔNG TRƯỜNG") && w.contexts.some((c) => c.label === "VĂN PHÒNG"));
  assert.equal(w.def, "cong_truong");
  assert.ok(w.contexts.every((c) => c.files.every((f) => f.ref.subfolder === "newtecons-wardrobe")));
});

test("settings: defaults follow extra.newtecons_route, N 1..10 or chưa có, never submits", () => {
  const chars = L.parseCharacters({ schema: "jjv/character-refs/v1", characters: { CHAR_01: { name: "A", face: [] }, CHAR_02: { name: "B", face: [] } } });
  const ward = L.parseWardrobe({ schema: "jjv/wardrobe-presets/v1", default_context: "van_phong", contexts: { cong_truong: [], van_phong: [] } });
  const d = L.defaultImageSettings({ newtecons_route: "codex" }, chars, ward);
  assert.deepEqual([d.char, d.context, d.route, d.count], ["CHAR_01", "van_phong", "codex", null]);
  const v = L.validateImageSettings(d, chars, ward);
  assert.equal(v.ok, true, v.errors.join("; "));
  assert.equal(v.value.submits_gpu, false);
  const bad = L.validateImageSettings({ ...d, count: 11, route: "cloud", char: "CHAR_09" }, chars, ward);
  assert.equal(bad.errors.length, 3);
  assert.equal(L.defaultImageSettings({ newtecons_image_ui: { count: 4 } }, chars, ward).count, 4);
});

test("route chips use the workflow's own plan (same edits as the image lane)", () => {
  const plan = routePlan(v4.extra);
  assert.ok(plan, "v004 carries newtecons_route_plan");
  const opts = Object.keys(plan.route.options);
  assert.ok(opts.includes("local") && opts.includes("codex"), JSON.stringify(opts));
  const ch = planChanges(v4.extra, v4.nodes, "route", "codex");
  assert.deepEqual(ch.extra, { newtecons_route: "codex" });
  assert.ok(ch.modes.length > 0);
});

test("upload helpers: target node by title, safe name, type/size gate", () => {
  const g = { extra: { newtecons_wardrobe: { optional: [7] } }, nodes: [
    { id: 5, type: "LoadImage", title: "UPLOAD trang phục (khác)" }, { id: 7, type: "LoadImage", title: "UPLOAD — trang phục công ty" },
    { id: 9, type: "LoadImage", title: "BỐI CẢNH tham chiếu" }, { id: 10, type: "Note", title: "BỐI CẢNH" }] };
  assert.equal(L.uploadTarget(g, "wardrobe").id, 7);
  assert.equal(L.uploadTarget(g, "scene").id, 9);
  assert.equal(L.uploadTarget({ nodes: [] }, "scene"), null);
  assert.match(L.uploadName({ name: "Áo phản quang.JPG" }, "CHAR_03", "wardrobe"), /^wardrobe_CHAR_03_\d{14}\.jpg$/u);
  assert.equal(L.acceptsUpload({ type: "image/png", size: 10 }), true);
  assert.equal(L.acceptsUpload({ type: "image/svg+xml", size: 10 }), false);
  assert.equal(L.acceptsUpload({ type: "image/png", size: 26 * 1024 * 1024 }), false);
});

test("every image workflow version activates and yields ≥ 8 tabs", () => {
  const dir = path.join(WF, "NEWTECONS_IMAGE_8STEP");
  for (const f of readdirSync(dir).filter((x) => /grouped\.json$/u.test(x))) {
    const g = load(path.join(dir, f));
    assert.equal(L.isImageFlow(g.extra, g.groups), true, f);
    assert.ok(L.parseSteps(g.groups).length >= 8, f);
  }
});

const v5path = "NEWTECONS_IMAGE_8STEP/NEWTECONS_IMAGE_8STEP_v005_grouped.json";
const v5 = existsSync(path.join(WF, v5path)) ? snap(v5path) : null;

test("v4: lane exports the image panel depends on (namespace import) all exist", () => {
  const fns = ["routePlan", "currentChoice", "planChanges", "wardrobeStatus", "characterStatus", "presetFiles", "switchProblems",
    "approveCommand", "hexOf", "parsePromptList", "queuePromptsSequential", "promptListProgress", "maxPromptNumber",
    "codexMultiPromptSupport", "codexMultiPromptEdits"];
  const missing = fns.filter((k) => typeof S[k] !== "function");
  assert.deepEqual(missing, []);
  assert.equal(typeof S.MAX_PROMPTS, "number");
  assert.equal(typeof S.PROMPT_LIST_KEY, "string");
});

test("v4: VĂN PHÒNG — VEST (van_phong_suit) never offered — data and plan", () => {
  const raw = load(path.join(WEB, "data/wardrobe/newtecons_live_action.json"));
  const w = L.parseWardrobe({ ...raw, contexts: { ...raw.contexts, van_phong_suit: [{ name: "x", file: "newtecons-wardrobe/x.png" }] } });
  assert.deepEqual(w.contexts.map((c) => c.key).sort(), ["cong_truong", "van_phong"]);
  const fakePlan = { wardrobe: { options: { cong_truong: { label: "CÔNG TRƯỜNG" }, van_phong: { label: "VĂN PHÒNG" }, van_phong_suit: { label: "VĂN PHÒNG — VEST" } } } };
  assert.deepEqual(L.planOptions(fakePlan, "wardrobe").map((o) => o.value), ["cong_truong", "van_phong"]);
  if (v5) assert.ok(!L.planOptions(routePlan(v5.extra), "wardrobe").some((o) => o.value === "van_phong_suit"));
});

test("v4: step → plan dimensions on v005 (00 route, 02A wardrobe/upload/boicanh, 02B character, 08 fix08, 09 source/target)", () => {
  if (!v5) { results.push(["info", "v005 chưa có"]); return; }
  const p = routePlan(v5.extra);
  const by = Object.fromEntries(L.parseSteps(v5.groups).map((st) => [st.code, L.stepDimensions(st, p)]));
  assert.deepEqual(by["00"], ["route"]);
  assert.deepEqual(by["02A"], ["wardrobe", "upload", "boicanh"]);
  assert.deepEqual(by["02B"], ["character", "mau_moi"]);
  assert.deepEqual(by["08"], ["fix08"]);
  assert.deepEqual(by["09"], ["source09", "target09"]);
  assert.deepEqual(by["03"], []);
  assert.equal(L.planOptions(p, "target09").find((o) => o.value === "1080").prefix, "NEWTECONS/upscale/1080");
});

test("v4: tab order on v005 = 00·01·02A·02·02B·03…09", () => {
  if (!v5) return;
  assert.deepEqual(L.parseSteps(v5.groups).map((st) => st.code), ["00", "01", "02A", "02", "02B", "03", "04", "05", "06", "07", "08", "09"]);
});

test("v4: prompt-list target node = PrimitiveStringMultiline in the PROMPT group", () => {
  const steps = L.parseSteps(v4.groups);
  assert.equal(L.promptNodeId(v4, steps), 9);
  assert.equal(L.promptNodeId({ nodes: [] }, steps), null);
});

test("v4: lane anchor status works on the v005 snapshot (02A wardrobe / 02B character)", () => {
  if (!v5) return;
  const ws = S.wardrobeStatus(v5);
  assert.ok(ws && ws.slots.length >= 1 && ws.slots[0].kind === "required");
  const cs = S.characterStatus(v5);
  assert.ok(cs && cs.slots.length >= 2);
});

// ---- disk results index (history only keeps ~200 jobs; engine/worker renders use other prefixes) ----
const IDX = { schema: "jjv/image-results-index/v1", generated_at: "2026-11-01T00:00:00Z", folders: {
  "NEWTECONS/upscale": { count: 2, files: [{ name: "1080_00002_.png", mtime: 20 }, { name: "1080_00001_.png", mtime: 10 }, { name: "2K_00001_.png", mtime: 30 }] },
  "NEWTECONS/IMAGE_8STEP/07_9_ANH": { count: 1, files: [{ name: "CHAR_03_POSE1_GOC2_00001_.png", mtime: 5 }] },
  "NEWTECONS/s02a-shirt-v001": { count: 1, files: [{ name: "A_00001_.png", mtime: 1 }] } } };

test("indexOutput: prefix match on disk, newest first, only the node's own prefix", () => {
  const hit = L.indexOutput(IDX, [{ nodeId: 115, type: "SaveImage", title: "1080", prefix: "NEWTECONS/upscale/1080" }]);
  assert.equal(hit.match, "disk");
  assert.deepEqual(hit.media.map((m) => m.filename), ["1080_00002_.png", "1080_00001_.png"]);
  assert.equal(hit.media[0].subfolder, "NEWTECONS/upscale");
  assert.equal(L.indexOutput(IDX, [{ nodeId: 1, type: "SaveImage", title: "4K", prefix: "NEWTECONS/upscale/4K" }]), null);
});

test("indexOutput: CHAR_XX placeholder is a wildcard; PreviewImage (no prefix) and a missing index give null", () => {
  const hit = L.indexOutput(IDX, [{ nodeId: 65, type: "SaveImage", title: "9", prefix: "NEWTECONS/IMAGE_8STEP/07_9_ANH/CHAR_XX_POSEp_GOCg" }]);
  assert.equal(hit?.media[0].filename, "CHAR_03_POSE1_GOC2_00001_.png");
  assert.equal(L.indexOutput(IDX, [{ nodeId: 2, type: "PreviewImage", title: "p", prefix: null }]), null);
  assert.equal(L.indexOutput(null, [{ nodeId: 3, type: "SaveImage", title: "x", prefix: "NEWTECONS/upscale/1080" }]), null);
});

test("emptyOutputText names the prefix and says the step never ran when nothing is on disk or in history", () => {
  const t = L.emptyOutputText(IDX, [{ prefix: "NEWTECONS/upscale/4K" }], 200);
  assert.match(t, /NEWTECONS\/upscale\/4K/u);
  assert.match(t, /chưa chạy/u);
  assert.match(L.emptyOutputText(null, [{ prefix: "a/b" }], 200), /chưa có chỉ mục/u);
});

for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.filter((r) => r[0] === "ok").length}/${results.filter((r) => r[0] !== "info").length} passed`);
process.exit(failed ? 1 : 0);
