import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildArgs, episodeFor, missingHint, prefill } from "../web/video_step_defaults.js";
const table = JSON.parse(readFileSync(new URL("../web/data/video/step_defaults.json", import.meta.url), "utf8"));
test("prefill uses known shot and episode; unknown shot yields only safe defaults", () => {
  const ep = episodeFor({}, table);
  assert.equal(ep, "Newtecons-TienDo-KichTinh-30s");
  const logo = prefill("post.logo", "S02_A", ep, table);
  assert.match(logo.video, /S02_A_seedvr2_1440\.mp4$/);
  assert.ok(logo.out.startsWith(`production-local/JennieJoyKids-Story/${ep}/preview/`));
  assert.equal(prefill("post.logo", "ZZ", ep, table).video, undefined);
  assert.equal(episodeFor({ episode_id: "x" }, table), "x");
});
test("blank required fields are reported instead of sent; blank optional are dropped", () => {
  const r = buildArgs("seedvr2.plan", { out: "AUTO", segments_root: "", reads: " " });
  assert.deepEqual(r.args, { out: "AUTO" }); assert.deepEqual(r.missing, []);
  const bad = buildArgs("post.logo", { video: "", out: "o" });
  assert.deepEqual(bad.missing, ["video"]);
  assert.match(missingHint(bad.missing, false), /Shot chưa xác định/);
});
