"""Q1b caption gate on the REAL episode-04 review exports (skipped without the production folder).

v015 lights every word where its config says; v014 was rendered from the OLD word timing, so judged against the corrected
(v015) timing its picture lights words early (Where / look! / I ...).  The same v014 picture judged against its OWN config
passes: Q1b proves the picture follows the config, Q1 (audio onset) proves the config follows the voice."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from test_qa_review_support import FFMPEG, ep_config, ep_video, needs_ep, needs_ffmpeg, review_clip
from engine.qa.gates import FAIL, PASS, q1b_caption as q1b

pytestmark = [needs_ep, needs_ffmpeg]
RECIPE, SHA = q1b.load_recipe()
MOVED_EARLY = {"S01_A:look!", "S02_A:Where", "S04_B:I"}  # the words the user and the verifier saw lit early in v014


def run(cfg: dict, video: Path, origin: int = 0) -> dict:
    return q1b.run_q1b(cfg, video, ffmpeg=FFMPEG, recipe=copy.deepcopy(RECIPE), recipe_sha256=SHA, origin=origin)


def row(result: dict, shot: str, word: str) -> dict:
    return next(r for r in result["words"] if r["shot"] == shot and r["word"] == word)


def test_v015_export_passes_on_every_testable_word() -> None:
    result = run(ep_config("015"), ep_video("015"))
    s = result["summary"]
    assert result["status"] == PASS and s["words"] == 108 and s["tested"] == 103 and s["fail"] == 0 and s["n/a"] == 5
    assert result["control"]["detected"] and result["control"]["words_checked"] == 103
    keyword, plain = [r["delta_f"] for r in result["words"] if r.get("keyword") and "delta_f" in r], \
        [r["delta_f"] for r in result["words"] if not r.get("keyword") and "delta_f" in r]
    assert set(keyword) == {1} and set(plain) <= {0, 1} and plain.count(0) >= 70  # plain: dt 0; keyword: pink ramp, dt +1


def test_v014_export_judged_against_the_corrected_timing_fails_early_on_where_look_i() -> None:
    result = run(ep_config("015"), ep_video("014"))
    early = set(result["summary"]["early"])
    assert result["status"] == FAIL and MOVED_EARLY <= early
    where = row(result, "S02_A", "Where")
    assert (where["startF"], where["first_lit"], where["status"]) == (477, 470, "FAIL-early")  # v014 config said 470
    assert row(result, "S01_A", "look!")["first_lit"] == 142  # v014 config 141 + keyword ramp +1
    assert row(result, "S04_B", "I")["first_lit"] == 1184 and row(result, "S01_A", "Alice,")["status"] == PASS


def test_v014_export_against_its_own_config_passes() -> None:
    assert run(ep_config("014"), ep_video("014"))["status"] == PASS


def test_a_clip_with_an_origin_gives_the_same_verdict_as_the_whole_film(tmp_path: Path) -> None:
    first, count = 90, 150  # shot S01_A
    for version, expected in (("015", PASS), ("014", FAIL)):
        clip = review_clip(version, tmp_path, first, count)
        result = run(ep_config("015"), clip, origin=first)
        assert result["status"] == expected, result["failures"][:3]
        assert row(result, "S01_A", "look!")["status"] == ("PASS" if expected == PASS else "FAIL-early")
        assert row(result, "S02_A", "Where")["why"] == "shot is not in this file"
