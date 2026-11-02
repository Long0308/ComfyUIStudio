// node tests/test_pipeline_view_logic.mjs — one-shot 10-stage pipeline view (display-only; commands come from the engine data).
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as P from "../web/pipeline_view_logic.js";
import * as L from "../web/video_ui_logic.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}
const cmd = (t, extra = {}) => ({ text: `python -I jjv.py ${t}`, gpu: false, placeholders: [], ...extra });
const stage = (key, status, extra = {}) => ({ code: "03", key, label: key, status, reason: null, in: [], out: [], detail: {}, approval: null, next: null, ...extra });
const shot = (stages) => ({ id: "S02_A", pipeline: { schema: P.PIPELINE_SCHEMA, stages } });

test("generated-unapproved stage renders CHỜ DUYỆT with BOTH engine commands", () => {
  const s = stage("voice", "pending-review", { out: [{ kind: "audio", path: "a.wav", sha256: "a".repeat(64), seconds: 3.96 }],
    approval: cmd("voice approve --job dialogue:S02_A_L1", { placeholders: ["<tên-người-duyệt>"] }), next: cmd("h3 inputs --spec x") });
  const vm = P.pipelineViewModel(shot([s]));
  assert.equal(vm.pending, 1);
  const rv = vm.stages[0].review;
  assert.ok(rv.approvalCommand.text.includes("voice approve") && rv.nextCommand.text.includes("h3 inputs"));
  const html = P.renderPipelineHtml(vm);
  assert.ok(html.includes("CHỜ DUYỆT") && html.includes("LỆNH DUYỆT") && html.includes("LỆNH CHẠY TIẾP"));
  assert.ok(html.includes("voice approve --job dialogue:S02_A_L1") && html.includes("h3 inputs --spec x") && html.includes("tên-người-duyệt"));
});

test("an approved stage has no review box and no CHỜ DUYỆT", () => {
  const vm = P.pipelineViewModel(shot([stage("shotlist", "approved", { approval: null, next: null })]));
  assert.equal(vm.pending, 0);
  assert.equal(vm.stages[0].review, null);
  assert.ok(!P.renderPipelineHtml(vm).includes("CHỜ DUYỆT</b>"));
});

test("missing stage shows CHƯA CÓ with the exact next command; no command ⇒ none invented", () => {
  const withCmd = P.pipelineViewModel(shot([stage("captions", "missing", { reason: "chưa dựng", next: cmd("captions build --timing T") })]));
  assert.ok(P.renderPipelineHtml(withCmd).includes("CHƯA CÓ") && P.renderPipelineHtml(withCmd).includes("captions build --timing T"));
  const none = P.pipelineViewModel(shot([stage("logo", "missing")]));
  assert.equal(none.stages[0].missingBox.command, null);
  assert.ok(!P.renderPipelineHtml(none).includes("LỆNH KẾ TIẾP"));
});

test("refused stage (06) shows the named reason and what unblocks it; GPU commands are flagged, never a button", () => {
  const html = P.renderPipelineHtml(P.pipelineViewModel(shot([
    stage("upscale", "refused", { reason: "NOT QUALIFIED: cần receipt pilot", detail: { unblocks: "user cho phép pilot" } }),
    stage("h3", "pending-review", { next: cmd("video upscale --gpu-approved <token>", { gpu: true }) })])));
  assert.ok(html.includes("BỊ CHẶN") && html.includes("NOT QUALIFIED") && html.includes("Mở khóa: user cho phép pilot"));
  assert.ok(html.includes("LỆNH GPU") && !/<button/iu.test(html));
});

test("unknown status falls back to missing and is reported; hostile text is escaped; non-local urls dropped", () => {
  const s = P.normStage({ key: "x", status: "weird", reason: "<script>alert(1)</script>", out: [{ kind: "image", url: "http://evil/x.png", name: "<b>" }] });
  assert.equal(s.status, "missing"); assert.equal(s.statusRaw, "weird");
  const html = P.renderStageHtml({ ...s, review: null, missingBox: P.missingBox(s), refused: null });
  assert.ok(!html.includes("<script>") && html.includes("&lt;script&gt;") && !html.includes("evil"));
});

test("shot without pipeline shows CHƯA CÓ; normalizeState keeps shots[].pipeline", () => {
  assert.equal(P.pipelineViewModel({ id: "S" }).present, false);
  const st = L.normalizeState({ schema: L.SCHEMA, episode: "e", domain: "d", counts: {}, shots: [{ id: "S02_A", pipeline: { stages: [stage("a", "approved")] } }] }, "t");
  assert.equal(st.shots[0].pipeline.stages.length, 1);
});

const REAL = path.resolve(here, "../web/data/video/Newtecons-TienDo-KichTinh-30s.json");
test("real S02_A data: 10 stages in order, shirt ref 55f0a34b4777 checked, 06 refused, pending boxes carry commands", () => {
  if (!existsSync(REAL)) return;
  const data = JSON.parse(readFileSync(REAL, "utf8"));
  const vm = P.pipelineViewModel(data.shots.find((s) => s.id === "S02_A"));
  assert.deepEqual(vm.stages.map((s) => s.code), ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"]);
  const anchor = vm.stages.find((s) => s.key === "anchor");
  assert.ok(anchor.detail.wardrobe_checks.some((c) => c.prefix === "55f0a34b4777" && c.present === true));
  assert.equal(vm.stages.find((s) => s.key === "upscale").status, "refused");
  // Bước 10 (duyệt cuối) là bước chót: có lệnh duyệt nhưng không có bước kế — không bắt buộc `next`.
  for (const s of vm.stages.filter((x) => x.review && x.approval && x.key !== "review")) assert.ok(s.next, `${s.key} pending needs a next command`);
});

const MIXED = [
  { episode: "04-milk-and-mom", domain: "jenniejoy_cartoon_3d" },
  { episode: "Newtecons-TienDo-KichTinh-30s", domain: "newtecons_live_action" },
  { episode: "Newtecons-Other", domain: "newtecons_live_action" },
];
test("no episode extra + mixed index never selects a cartoon episode (no eps[0] fallback)", () => {
  const r = L.resolveEpisode({ settingsEpisode: "", extraEpisode: null, episodes: MIXED });
  assert.equal(r.episode, null); assert.equal(r.reason, "chon-tap");  // two live episodes: ambiguous => choose, never cartoon
  const cartoonFirst = L.resolveEpisode({ settingsEpisode: undefined, extraEpisode: undefined, episodes: [MIXED[0]] });
  assert.equal(cartoonFirst.episode, null);
});
test("explicit pick of a cartoon episode is refused as wrong-domain; a live pick resolves; a sole live episode resolves", () => {
  assert.deepEqual(L.resolveEpisode({ settingsEpisode: "04-milk-and-mom", episodes: MIXED }), { episode: null, reason: "wrong-domain" });
  assert.equal(L.resolveEpisode({ extraEpisode: "Newtecons-Other", episodes: MIXED }).episode, "Newtecons-Other");
  assert.equal(L.resolveEpisode({ episodes: MIXED.slice(0, 2) }).episode, "Newtecons-TienDo-KichTinh-30s");
  assert.equal(L.resolveEpisode({ settingsEpisode: "unknown-ep", episodes: MIXED }).reason, "chon-tap");
});
test("episodesForDomain keeps only the panel domain; entries without a domain are excluded", () => {
  assert.deepEqual(L.episodesForDomain([...MIXED, { episode: "x", domain: null }]).map((e) => e.episode), ["Newtecons-TienDo-KichTinh-30s", "Newtecons-Other"]);
});
test("the NEWTECONS panel source has no cartoon banner and no eps[0] fallback", () => {
  const src = readFileSync(path.resolve(here, "../web/video_ui.js"), "utf8");
  assert.ok(!/JENNIEJOY:/u.test(src) && !/eps\[0\]/u.test(src));
});

for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.filter((r) => r[0] === "ok").length}/${results.length} passed`);
process.exit(failed ? 1 : 0);
