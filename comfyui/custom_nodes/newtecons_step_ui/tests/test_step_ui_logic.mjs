// node tests/test_step_ui_logic.mjs — pure logic against the real NEWTECONS v003 workflows.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as L from "../web/step_ui_logic.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const WF = path.resolve(here, "../../../user/default/workflows");
const WIDGET_NAMES = {
  LoadImage: ["image"], LoadImageMask: ["image", "channel"], LoadAudio: ["audio"],
  SaveImage: ["filename_prefix"], SaveVideo: ["filename_prefix"], PrimitiveStringMultiline: ["value"],
  ComfySwitchNode: ["switch"],
};

// widget names in saved order: the node's widget inputs (covers schema changes, e.g. the Codex node), else the table
function widgetNames(n) {
  const fromInputs = (n.inputs || []).filter((q) => q.widget).map((q) => q.name);
  return fromInputs.length ? fromInputs : (WIDGET_NAMES[n.type] || []);
}

function snap(file) {
  const g = JSON.parse(readFileSync(path.join(WF, file), "utf8"));
  return {
    extra: g.extra, groups: g.groups,
    nodes: g.nodes.map((n) => ({ id: n.id, type: n.type, title: n.title, mode: n.mode || 0, pos: n.pos,
      widgets: Object.fromEntries(widgetNames(n).map((k, i) => [k, n.widgets_values?.[i]])),
      properties: { ...(n.properties || {}) }, inputs: (n.inputs || []).map((q) => ({ name: q.name, link: q.link })) })),
    links: g.links.map((l) => ({ id: l[0], origin_id: l[1], target_id: l[3] })),
  };
}

const results = [];
function test(name, fn) {
  try { fn(); results.push(["ok", name]); } catch (err) { results.push(["FAIL", name, err.message]); }
}

const img = snap("NEWTECONS_IMAGE_8STEP/NEWTECONS_IMAGE_8STEP_v003_grouped.json");
const vid = snap("NEWTECONS_H3/NEWTECONS_H3_R2V_LIVE_ACTION_v003_grouped.json");
const imgSteps = L.parseSteps(img.groups);
const vidSteps = L.parseSteps(vid.groups);

test("workflow kind gates NEWTECONS only", () => {
  assert.equal(L.workflowKind(img.extra), "image");
  assert.equal(L.workflowKind(vid.extra), "video");
  assert.equal(L.workflowKind({ jenniejoy: {} }), null);
  assert.equal(L.workflowKind(undefined), null);
});

test("image steps in order incl 02B", () => {
  assert.deepEqual(imgSteps.map((s) => s.code), ["01", "02", "02B", "03", "04", "05", "06", "07", "08"]);
  assert.equal(imgSteps[2].label, "THAM CHIẾU FACE/POSE");
  assert.equal(imgSteps[7].label, "9 ẢNH");
});

test("video steps 01..05", () => {
  assert.deepEqual(vidSteps.map((s) => s.label), ["ĐỌC SHOTLIST", "VIẾT PROMPT", "AI QUAY VIDEO", "LÊN 1080P", "LƯU & QUAY TIẾP"]);
});

test("02B VÀO = face + pose LoadImage (top-level newtecons_ref_* copies)", () => {
  const all = L.inputsForStep(img, imgSteps[2], imgSteps);
  const ins = all.filter((i) => !i.upstream);
  assert.ok(all.some((i) => i.upstream && i.nodeId === 13 && i.ref === null), "connected blank node13 remains visible with upstream attribution");
  assert.equal(ins.length, 2);
  assert.deepEqual(ins.map((i) => i.ref.filename.split("_").slice(0, 3).join("_")).sort(),
    ["newtecons_ref_face", "newtecons_ref_pose"]);
  assert.ok(ins.every((i) => !i.upstream && i.kind === "image" && i.ref.subfolder === "" && i.ref.type === "input"));
});

test("07 has no own source: VÀO traced upstream to step 06 LoadImage", () => {
  const ins = L.inputsForStep(img, imgSteps[7], imgSteps);
  assert.ok(ins.length >= 1);
  assert.ok(ins.every((i) => i.upstream));
  assert.ok(ins.some((i) => i.type === "LoadImage" && i.step === "06"), JSON.stringify(ins.map((i) => [i.type, i.step])));
});

test("01 VÀO is the prompt text", () => {
  const ins = L.inputsForStep(img, imgSteps[0], imgSteps);
  assert.equal(ins[0].kind, "text");
  assert.match(ins[0].value, /NEWTECONS/);
});

test("video 01 VÀO = WAV + scene image", () => {
  const kinds = L.inputsForStep(vid, vidSteps[0], vidSteps).map((i) => i.kind).sort();
  assert.deepEqual(kinds, ["audio", "image"]);
});

test("output nodes per step carry filename_prefix", () => {
  const outs07 = L.outputNodesForStep(img, imgSteps[7]);
  assert.deepEqual(outs07.map((o) => o.type).sort(), ["PreviewImage", "SaveImage"]);
  assert.equal(outs07.find((o) => o.type === "SaveImage").prefix, "NEWTECONS/IMAGE_8STEP/07_9_ANH/CHAR_XX_POSEp_GOCg");
  assert.equal(L.outputNodesForStep(vid, vidSteps[4]).find((o) => o.type === "SaveVideo").prefix, "NEWTECONS/H3/Shot");
});

test("latestOutput: strong beats newer weak; wrong class/prefix ignored; Preview needs strong", () => {
  const outs = L.outputNodesForStep(img, imgSteps[7]);
  const save = outs.find((o) => o.type === "SaveImage");
  const prev = outs.find((o) => o.type === "PreviewImage");
  const sig = L.groupSignature(img.groups);
  const media = (f) => ({ images: [{ filename: f, subfolder: "NEWTECONS", type: "output" }] });
  const api = (cls, prefix) => ({ class_type: cls, inputs: prefix ? { filename_prefix: prefix } : {} });
  const history = {
    old_strong: { prompt: [1, "old_strong", { [save.nodeId]: api("SaveImage", save.prefix) }, { extra_pnginfo: { workflow: { groups: img.groups } } }],
      outputs: { [save.nodeId]: media("a.png") } },
    newer_weak: { prompt: [5, "newer_weak", { [save.nodeId]: api("SaveImage", save.prefix) }, {}], outputs: { [save.nodeId]: media("b.png") } },
    newest_wrong_class: { prompt: [9, "x", { [save.nodeId]: api("VAEDecode") }, { extra_pnginfo: { workflow: { groups: img.groups } } }],
      outputs: { [save.nodeId]: media("c.png") } },
    newest_wrong_prefix: { prompt: [8, "y", { [save.nodeId]: api("SaveImage", "OTHER/") }, { extra_pnginfo: { workflow: { groups: img.groups } } }],
      outputs: { [save.nodeId]: media("d.png") } },
    preview_other_wf: { prompt: [7, "p", { [prev.nodeId]: api("PreviewImage") }, {}], outputs: { [prev.nodeId]: media("e.png") } },
  };
  const hit = L.latestOutput(history, outs, sig);
  assert.equal(hit.promptId, "old_strong");
  assert.equal(hit.match, "strong");
  delete history.old_strong;
  const weak = L.latestOutput(history, outs, sig);
  assert.equal(weak.promptId, "newer_weak");
  assert.equal(weak.match, "weak");
  assert.equal(L.latestOutput(history, [prev], sig), null);
  assert.equal(L.latestOutput({}, outs, sig), null);
});

test("video output detected by extension", () => {
  assert.equal(L.mediaKind("Shot_00001_.mp4"), "video");
  assert.equal(L.mediaKind("x.wav"), "audio");
  assert.equal(L.mediaKind("x.png"), "image");
});

test("splitAnnotated + viewPath", () => {
  assert.deepEqual(L.splitAnnotated("reference-library/pose/a.png"), { filename: "a.png", subfolder: "reference-library/pose", type: "input" });
  assert.deepEqual(L.splitAnnotated("b.png [output]"), { filename: "b.png", subfolder: "", type: "output" });
  assert.equal(L.viewPath({ filename: "a b.png", subfolder: "x/y", type: "input" }), "/view?filename=a+b.png&subfolder=x%2Fy&type=input");
});

test("fitBounds maps the group into the free area left of the panel", () => {
  const b = [8160, 0, 1200, 2194];
  const view = { width: 1600, height: 900 };
  const pads = { top: 60, right: 640, margin: 20 };
  const { scale, offset } = L.fitBounds(b, view, pads);
  const sx = (x) => (x + offset[0]) * scale;
  const sy = (y) => (y + offset[1]) * scale;
  assert.ok(sx(b[0]) >= 20 - 1e-6 && sx(b[0] + b[2]) <= 1600 - 640 - 20 + 1e-6);
  assert.ok(sy(b[1]) >= 60 + 20 - 1e-6 && sy(b[1] + b[3]) <= 900 - 20 + 1e-6);
  assert.ok(Math.abs((sy(b[1]) + sy(b[1] + b[3])) / 2 - (60 + 900) / 2) < 1e-6);
});

test("engineFilter", () => {
  const m = { items: [{ char: "CHAR_01", kind: "FACE" }, { char: "CHAR_01", kind: "ACTION" }, { char: "CHAR_02", kind: "FACE" }] };
  assert.equal(L.engineFilter(m, "CHAR_01", "").length, 2);
  assert.equal(L.engineFilter(m, "CHAR_01", "FACE").length, 1);
});

// ---------------- v004 (00 CHỌN LUỒNG, 09 DUYỆT & UPSCALE, 10 PROMPT) ----------------
const v4 = snap("NEWTECONS_IMAGE_8STEP/NEWTECONS_IMAGE_8STEP_v004r1_grouped.json");
const v4Steps = L.parseSteps(v4.groups);
const v4With = (nodes, extra = v4.extra) => ({ ...v4, nodes, extra });
function choose(graph, dim, opt) {
  const ch = L.planChanges(graph.extra, graph.nodes, dim, opt);
  return v4With(L.applyChanges(graph.nodes, ch), { ...graph.extra, ...ch.extra });
}

test("v004 steps 00..09, plan present, defaults local/file/1080", () => {
  assert.deepEqual(v4Steps.map((s) => s.code), ["00", "01", "02", "02B", "03", "04", "05", "06", "07", "08", "09"]);
  assert.equal(v4Steps[0].label, "CHỌN LUỒNG");
  assert.equal(v4Steps[10].label, "DUYỆT & UPSCALE");
  assert.ok(L.routePlan(v4.extra));
  assert.equal(L.routePlan(img.extra), null, "v003 has no plan");
  assert.equal(L.currentChoice(v4.extra, v4.nodes, "route"), "local");
  assert.equal(L.currentChoice(v4.extra, v4.nodes, "source09"), "file");
  assert.equal(L.currentChoice(v4.extra, v4.nodes, "target09"), "1080");
});

test("route codex -> local restores every mode exactly; user-enabled node survives the round trip", () => {
  const codex = choose(v4, "route", "codex");
  assert.equal(L.currentChoice(codex.extra, codex.nodes, "route"), "codex");
  assert.equal(codex.nodes.find((n) => n.type === "CodexOAuthImageLane").mode, 0);
  assert.ok(codex.nodes.filter((n) => n.mode === 2).length > v4.nodes.filter((n) => n.mode === 2).length);
  const back = choose(codex, "route", "local");
  assert.deepEqual(back.nodes.map((n) => n.mode), v4.nodes.map((n) => n.mode));
  // restored (live) nodes drop the saved mode; the re-muted Codex node keeps its pre-mute mode for the next CODEX
  assert.ok(back.nodes.filter((n) => n.mode !== 2).every((n) => !("nt_mode_saved" in n.properties)));
  assert.equal(back.nodes.find((n) => n.type === "CodexOAuthImageLane").properties.nt_mode_saved, 0);
  const face = v4.nodes.find((n) => n.title === "Mã hoá mặt — TẮT (mute)");
  const tweaked = v4With(v4.nodes.map((n) => (n.id === face.id ? { ...n, mode: 0 } : n)));
  const rt = choose(choose(tweaked, "route", "codex"), "route", "local");
  assert.equal(rt.nodes.find((n) => n.id === face.id).mode, 0);
});

test("switchProblems empty for all 36 route x fix08 x source x target combos (2 orders); flipped junction caught", () => {
  for (const r of ["local", "codex"]) for (const f of ["off", "on"]) for (const s of ["file", "08", "07"]) for (const t of ["1080", "2K", "4K"]) {
    const a = choose(choose(choose(choose(v4, "route", r), "fix08", f), "source09", s), "target09", t);
    assert.deepEqual(L.switchProblems(a), [], `${r}/${f}/${s}/${t}`);
    assert.equal(L.currentChoice(a.extra, a.nodes, "source09"), s);
    assert.equal(L.currentChoice(a.extra, a.nodes, "target09"), t);
    const b = choose(choose(choose(choose(v4, "route", r), "source09", s), "fix08", f), "target09", t);
    assert.deepEqual(L.switchProblems(b), [], `order2 ${r}/${s}/${f}/${t}`);
  }
  const codex = choose(v4, "route", "codex");
  const jn = codex.nodes.find((n) => n.title.startsWith("ẢNH TẠO RA"));
  const wrong = v4With(codex.nodes.map((n) => (n.id === jn.id ? { ...n, widgets: { switch: true } } : n)), codex.extra);
  assert.equal(L.switchProblems(wrong).length, 1);
});

test("07 VÀO in v004 skips the muted Codex node and reaches step 06 LoadImage", () => {
  const s07 = v4Steps.find((s) => s.code === "07");
  const ins = L.inputsForStep(v4, s07, v4Steps);
  assert.ok(ins.length && !ins[0].mode && ins[0].type === "LoadImage" && ins[0].step === "06",
    JSON.stringify(ins.map((i) => [i.type, i.step, i.mode])));
});

test("09 outputs: three SaveImage NEWTECONS/upscale/{1080,2K,4K} + VÀO preview", () => {
  const s09 = v4Steps.find((s) => s.code === "09");
  const outs = L.outputNodesForStep(v4, s09);
  assert.deepEqual(outs.filter((o) => o.type === "SaveImage").map((o) => [o.prefix, o.mode]),
    [["NEWTECONS/upscale/1080", 0], ["NEWTECONS/upscale/2K", 2], ["NEWTECONS/upscale/4K", 2]]);
  assert.equal(outs.filter((o) => o.type === "PreviewImage").length, 1);
});

test("approveCommand: exact engine command, sha validated", () => {
  const sha = "e4a81961f88e61ea320c494e8657857cc99525d465d78e8c6b30304097d88be9";
  assert.equal(L.approveCommand({ sha }), "jjv images approve --episode <EPISODE> --out <IMAGES_OUT> --library-out <LIBRARY_DIR> "
    + `--prompt-id <PROMPT_ID> --sha ${sha} --reviewer <user> --scope <SCOPE>`);
  assert.match(L.approveCommand({ sha, reviewer: "Long Pham", scope: "wardrobe" }), /--reviewer "Long Pham" --scope wardrobe$/u);
  assert.throws(() => L.approveCommand({ sha: "E4A8" }));
  assert.equal(L.hexOf(new Uint8Array([0, 15, 255]).buffer), "000fff");
});

test("parsePromptList: lines trimmed, blanks dropped, >10 refused", () => {
  assert.deepEqual(L.parsePromptList(" a \n\n b\r\nc "), ["a", "b", "c"]);
  assert.deepEqual(L.parsePromptList(""), []);
  assert.throws(() => L.parsePromptList(Array.from({ length: 11 }, (_, i) => "p" + i).join("\n")), /tối đa 10/u);
});

const asyncTests = [];
function atest(name, fn) {
  asyncTests.push(fn().then(() => results.push(["ok", name]), (err) => results.push(["FAIL", name, err.message])));
}

atest("queuePromptsSequential: one app.queuePrompt per prompt, in order, never overlapping; widget restored", async () => {
  const widget = { value: "ORIGINAL" };
  const seen = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const app = { queuePrompt: async (number, batch) => {
    inFlight += 1; maxInFlight = Math.max(maxInFlight, inFlight);
    seen.push([widget.value, number, batch]);
    await new Promise((r) => setTimeout(r, 5));
    inFlight -= 1;
    return true;
  } };
  const progress = [];
  const prompts = L.parsePromptList("p1\np2\np3");
  const res = await L.queuePromptsSequential({ prompts, setPrompt: (t) => { widget.value = t; },
    queue: () => app.queuePrompt(0, 1), restore: () => { widget.value = "ORIGINAL"; },
    onQueued: (k, n) => progress.push(`${k} / ${n}`) });
  assert.deepEqual(seen, [["p1", 0, 1], ["p2", 0, 1], ["p3", 0, 1]]);
  assert.equal(maxInFlight, 1);
  assert.deepEqual(progress, ["1 / 3", "2 / 3", "3 / 3"]);
  assert.ok(res.every((r) => r.ok));
  assert.equal(widget.value, "ORIGINAL");
});

atest("queuePromptsSequential: stops at the first refusal or throw, still restores", async () => {
  const widget = { value: "X" };
  let calls = 0;
  const res = await L.queuePromptsSequential({ prompts: ["a", "b", "c"], setPrompt: (t) => { widget.value = t; },
    queue: async () => { calls += 1; return calls !== 2; }, restore: () => { widget.value = "X"; } });
  assert.equal(calls, 2);
  assert.deepEqual(res.map((r) => r.ok), [true, false]);
  assert.equal(widget.value, "X");
  const thrown = await L.queuePromptsSequential({ prompts: ["a", "b"], setPrompt: () => {},
    queue: async () => { throw new Error("HTTP 400"); } });
  assert.deepEqual(thrown, [{ index: 0, ok: false, error: "HTTP 400" }]);
  await assert.rejects(() => L.queuePromptsSequential({ prompts: [], setPrompt: () => {}, queue: async () => true }));
});

test("progress k / N from /history: only jobs after `since`, matched by prompt text, errors counted", () => {
  const job = (num, text, status) => ({ prompt: [num, "id" + num, { 13: { class_type: "PrimitiveStringMultiline", inputs: { value: text } } }, {}],
    status: { status_str: status, completed: status === "success" } });
  const history = { a: job(5, "p1", "success"), b: job(11, "p1", "success"), c: job(12, "p2", "error"),
    d: job(13, "p3", "success"), e: job(14, "p1", "success") };
  assert.deepEqual(L.promptListProgress(history, ["p1", "p2", "p3", "p1"], 10, 13), { done: 3, failed: 1, total: 4 });
  assert.deepEqual(L.promptListProgress(history, ["p1"], 20, 13), { done: 0, failed: 0, total: 1 });
  assert.equal(L.maxPromptNumber(history, { queue_running: [[20, "r"]], queue_pending: [[21, "q"]] }), 21);
});

test("CODEX multi-prompt gated on a `prompts` input of the bridge node", () => {
  const cx = v4.nodes.find((n) => n.type === "CodexOAuthImageLane");
  assert.equal(L.codexMultiPromptSupport(cx), true, "v004r1: the live bridge node has a prompts input (recreate 19:38)");
  assert.equal(L.codexMultiPromptSupport({ inputs: [{ name: "prompt" }], widgets: { prompt: "" } }), false);
  assert.equal(L.codexMultiPromptSupport({ inputs: [{ name: "prompts" }] }), true);
  assert.deepEqual(L.codexMultiPromptEdits(["a", "b"]), { prompts: "a\nb", count: 2 });
  assert.equal(cx.widgets.count, 10);
});

test("fix08 default off on both routes; CODEX leaves no local loader/sampler outside 09 unless 08 is on", () => {
  assert.equal(L.currentChoice(v4.extra, v4.nodes, "fix08"), "off");
  const LOCAL = new Set(["UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly", "KSampler", "SamplerCustomAdvanced",
    "Krea2EditModelPatch", "CheckpointLoaderSimple", "UpscaleModelLoader", "ImageUpscaleWithModel"]);
  const s09 = v4Steps.find((s) => s.code === "09");
  const active = (g) => g.nodes.filter((n) => !n.mode && LOCAL.has(n.type) && !L.inBounds(n.pos, s09.bounding)).map((n) => n.type);
  const codex = choose(v4, "route", "codex");
  assert.deepEqual(active(codex), []);
  assert.ok(active(choose(codex, "fix08", "on")).includes("Krea2EditModelPatch"));
  const via09 = choose(codex, "source09", "08");
  assert.equal(L.currentChoice(via09.extra, via09.nodes, "fix08"), "on");
});

test("targetSize mirrors ImageScale width=0 (Python round half-even)", () => {
  assert.deepEqual(L.targetSize(1086, 1448, 1440), { width: 1080, height: 1440, is34: true });
  assert.deepEqual(L.targetSize(1086, 1448, 2048), { width: 1536, height: 2048, is34: true });
  assert.deepEqual(L.targetSize(1086, 1448, 3840), { width: 2880, height: 3840, is34: true });
  assert.equal(L.targetSize(1536, 864, 1440).is34, false);
  assert.equal(L.targetSize(1536, 864, 1440).width, 2560);
  assert.equal(L.roundHalfEven(2.5), 2);
  assert.equal(L.roundHalfEven(3.5), 4);
  assert.equal(L.roundHalfEven(2.4), 2);
});

// ---------------- v005 (02A NEO TRANG PHỤC, 02B ảnh nhân vật) ----------------
const v5 = snap("ProjectStudio5 - Film Newtecons/01 Workflow Image/NEWTECONS Image v005 - neo trang phuc.json");
const v5Steps = L.parseSteps(v5.groups);
const v5With = (nodes, extra) => ({ ...v5, nodes, extra });
function choose5(graph, dim, opt) {
  const ch = L.planChanges(graph.extra, graph.nodes, dim, opt);
  return v5With(L.applyChanges(graph.nodes, ch), { ...graph.extra, ...ch.extra });
}

test("v005 steps include 02A right after 01, detection does not depend on the folder", () => {
  assert.equal(L.workflowKind(v5.extra), "image");
  assert.deepEqual(v5Steps.map((s) => s.code).slice(0, 5), ["00", "01", "02A", "02", "02B"]);
});

test("02A wardrobe status: context, attached refs, never blocked with the real presets", () => {
  const ws = L.wardrobeStatus(v5);
  assert.equal(ws.context, "cong_truong");
  assert.equal(ws.blocked, false);
  assert.equal(ws.attached, 7);
  const office = choose5(v5, "wardrobe", "van_phong");
  const wo = L.wardrobeStatus(office);
  assert.equal(wo.context, "van_phong");
  assert.equal(wo.attached, 3);
  assert.equal(office.extra.newtecons_wardrobe_context, "van_phong");
  const cx = office.nodes.find((n) => n.type === "CodexOAuthImageLane");
  assert.equal(cx.widgets.context, "van_phong");
  const blank = v5With(v5.nodes.map((n) => (n.id === ws.slots[0].id ? { ...n, widgets: { image: "" } } : n)), v5.extra);
  assert.equal(L.wardrobeStatus(blank).blocked, true);
});

test("02B character switch fills the character's own files; MẪU MỚI off by default", () => {
  for (const c of ["CHAR_01", "CHAR_06", "CHAR_08"]) {
    const g = choose5(v5, "character", c);
    const cs = L.characterStatus(g);
    assert.equal(cs.context, c);
    assert.ok(cs.slots.every((s) => new RegExp(`^newtecons(-characters/|_ch_)${c}[/_]`, "u").test(s.value)), JSON.stringify(cs.slots.map((s) => s.value)));
    assert.ok(cs.slots.every((s) => !/newtecons_ref_|reference-library/u.test(s.value)));
  }
  assert.equal(L.currentChoice(v5.extra, v5.nodes, "mau_moi"), "off");
  const on = choose5(v5, "mau_moi", "on");
  assert.equal(L.currentChoice(on.extra, on.nodes, "mau_moi"), "on");
  assert.deepEqual(L.switchProblems(on), []);
});

test("presetFiles reads jjv/wardrobe-presets/v1 rows", () => {
  const p = { contexts: { cong_truong: [{ file: "newtecons-wardrobe/a.png" }, { name: "x" }], van_phong: ["b.png"] } };
  assert.deepEqual(L.presetFiles(p, "cong_truong"), ["newtecons-wardrobe/a.png"]);
  assert.deepEqual(L.presetFiles(p, "van_phong"), ["b.png"]);
  assert.deepEqual(L.presetFiles(null, "x"), []);
});

test("presetMatches accepts the registry path or the sha12 top-level copy; saved v005 matches the real presets", () => {
  const p = { contexts: { a: [{ file: "newtecons-wardrobe/x.png", sha256: "59aba9523b6177e3" }, { file: "y.png" }] } };
  assert.equal(L.presetMatches(p, "a", ["newtecons_wd_59aba9523b61.png", "y.png"]), true);
  assert.equal(L.presetMatches(p, "a", ["newtecons-wardrobe/x.png", "y.png"]), true);
  assert.equal(L.presetMatches(p, "a", ["other.png", "y.png"]), false);
  assert.equal(L.presetMatches(p, "a", ["newtecons_wd_59aba9523b61.png"]), false);
  const real = JSON.parse(readFileSync(path.resolve(here, "../web/data/wardrobe/newtecons_live_action.json"), "utf8"));
  for (const ctx of Object.keys(real.contexts)) {
    const g = choose5(v5, "wardrobe", ctx);
    const ws = L.wardrobeStatus(g);
    assert.equal(L.presetMatches(real, ctx, ws.slots.map((s) => s.value).filter(Boolean)), true, ctx);
  }
});

test("TARGET_HEIGHTS is frozen and equals the ImageScale heights saved in v004/v005 group 09", () => {
  assert.deepEqual({ ...L.TARGET_HEIGHTS }, { "1080": 1440, "2K": 2048, "4K": 3840 });
  assert.ok(Object.isFrozen(L.TARGET_HEIGHTS));
  for (const file of ["NEWTECONS_IMAGE_8STEP/NEWTECONS_IMAGE_8STEP_v004r1_grouped.json",
    "ProjectStudio5 - Film Newtecons/01 Workflow Image/NEWTECONS Image v005 - neo trang phuc.json"]) {
    const g = JSON.parse(readFileSync(path.join(WF, file), "utf8"));
    const saved = Object.fromEntries(g.nodes.filter((n) => n.type === "ImageScale" && /^ĐÍCH /u.test(n.title))
      .map((n) => [n.title.split(" ")[1], n.widgets_values[2]]));
    assert.deepEqual(saved, { ...L.TARGET_HEIGHTS }, file);
  }
});

await Promise.all(asyncTests);
for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] !== "ok").length;
console.log(`${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
