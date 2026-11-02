import { test } from "node:test";
import assert from "node:assert/strict";
import { legacyBarVisible } from "../web/step_ui_logic.js";
test("legacy blue bar shows only for image-step workflows", () => {
  assert.equal(legacyBarVisible("image", true, 8), true);
  assert.equal(legacyBarVisible("video", true, 8), false);
  assert.equal(legacyBarVisible("newtecons", false, 8), false);
  assert.equal(legacyBarVisible(null, false, 0), false);
  assert.equal(legacyBarVisible("image", true, 2), false);
});
