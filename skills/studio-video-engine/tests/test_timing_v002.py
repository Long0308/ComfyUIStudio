"""Recipe timing/words-onset-v002 (root decision 2026-10-27): the Q1 gate that no longer reads closures and breaths as onsets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_timing_parity_ep04 import needs_wavs, produce
from test_timing_q1 import LINE, entry
from test_timing_support import FPS, RECIPE, sound, word

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.timing.gate import run_q1
from engine.timing.q1 import q1_rows
from engine.timing.recipe import load_timing_recipe, select_recipe_id

V2 = load_timing_recipe("timing/words-onset-v002")
Q2 = V2.block("q1")
CONFIG = SimpleNamespace(episode={}, domain={"domain_id": "jenniejoy_cartoon_3d"})


def test_v003_is_the_domain_default_and_v001_v002_stay_selectable() -> None:
    assert select_recipe_id(CONFIG, None) == ("timing/words-onset-v003", "default recipe for the domain")
    for older in ("timing/words-onset-v001", "timing/words-onset-v002"):
        assert select_recipe_id(CONFIG, older) == (older, "cli")
    assert "default_for_domain" not in V2.data and "default_for_domain" not in RECIPE.data


def test_default_selection_needs_exactly_one_default_or_one_recipe(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    (skill / "recipes" / "timing").mkdir(parents=True)
    source = SKILL_ROOT / "recipes" / "timing"
    shutil.copy(source / "words-onset-v001.json", skill / "recipes" / "timing")
    assert select_recipe_id(CONFIG, None, skill_root=skill)[1] == "unique recipe for the domain"
    shutil.copy(source / "words-onset-v002.json", skill / "recipes" / "timing")
    with pytest.raises(Refused, match="no timing recipe selected"):
        select_recipe_id(CONFIG, None, skill_root=skill)  # two recipes, none flagged: never a silent pick
    shutil.copy(source / "words-onset-v003.json", skill / "recipes" / "timing")
    assert select_recipe_id(CONFIG, None, skill_root=skill)[0] == "timing/words-onset-v003"
    twin = json.loads((source / "words-onset-v003.json").read_text(encoding="utf-8"))
    twin["recipe_id"] = "timing/words-onset-v004"
    (skill / "recipes" / "timing" / "words-onset-v004.json").write_text(json.dumps(twin), encoding="utf-8")
    with pytest.raises(Refused, match="no timing recipe selected"):
        select_recipe_id(CONFIG, None, skill_root=skill)  # two defaults: ambiguous


def test_v002_changes_only_the_q1_gate_and_the_new_keys_are_validated(tmp_path: Path) -> None:
    for block in ("first_word", "all_words", "recognition", "language", "document_schema"):
        assert V2.data[block] == RECIPE.data[block]
    assert (Q2["pause_min_s"], Q2["onset_voiced_dbfs"], Q2["onset_sustain_s"], Q2["warn_late_frames"]) == (0.10, -35.0, 0.03, 6)
    assert (Q2["max_early_frames"], Q2["max_late_frames"]) == (0, 2)
    skill = tmp_path / "skill"
    (skill / "recipes" / "timing").mkdir(parents=True)
    for patch, message in (({"onset_sustain_s": None}, "go together"), ({"warn_late_frames": 1}, "below max_late_frames")):
        data = json.loads((SKILL_ROOT / "recipes" / "timing" / "words-onset-v002.json").read_text(encoding="utf-8"))
        data["q1"] = {k: v for k, v in {**data["q1"], **patch}.items() if v is not None}
        (skill / "recipes" / "timing" / "words-onset-v002.json").write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(Refused, match=message):
            load_timing_recipe("timing/words-onset-v002", skill_root=skill)


def test_a_breath_before_the_word_is_not_an_onset_in_v002_but_was_in_v001() -> None:
    snd = sound(("tone", 0.5), ("sil", 0.3), ("soft", 0.15), ("tone", 0.7))  # word at 0.95 s, a -42 dBFS breath at 0.8 s
    line = {"id": "S01", "start_frame": 0, "words": [word(1, "What", 0.0, 0.5), word(2, "look", 0.95, 1.65)]}
    assert q1_rows([line], lambda e: snd, Q2, FPS)[1]["status"] == "PASS"
    assert q1_rows([line], lambda e: snd, RECIPE.block("q1"), FPS)[1]["status"].startswith("LATE")


def test_a_stop_closure_inside_a_word_is_not_a_pause_in_v002_but_was_in_v001() -> None:
    snd = sound(("tone", 0.35), ("sil", 0.08), ("tone", 0.8))
    line = {"id": "S01", "start_frame": 0, "words": [word(1, "liquid", 0.1, 1.2)]}
    assert q1_rows([line], lambda e: snd, Q2, FPS)[0]["status"].startswith("n/a")
    assert q1_rows([line], lambda e: snd, RECIPE.block("q1"), FPS)[0]["status"] == "FAIL-early"


@pytest.mark.parametrize("lit, status", [(24, "PASS"), (26, "PASS"), (27, "WARN-late"), (30, "WARN-late"), (31, "LATE>6f"), (23, "FAIL-early")])
def test_late_tiers_pass_warn_fail_and_early_is_always_a_fail(lit: int, status: str) -> None:
    assert q1_rows([entry(lit)], lambda e: LINE, Q2, FPS)[1]["status"] == status


def test_warn_is_listed_but_does_not_block_and_a_failing_late_word_does() -> None:
    warned = run_q1([entry(27), {**entry(25), "id": "S02"}], lambda e: LINE, Q2, FPS)
    assert warned["verdict"] == "PASS" and warned["summary"]["warn_words"] == ["S01:look(+3f)"] and warned["negative_control"]["detected"]
    failing = run_q1([entry(31)], lambda e: LINE, Q2, FPS)
    assert failing["verdict"] == "FAIL" and failing["summary"]["late_words"] == ["S01:look"]
    early = run_q1([entry(23)], lambda e: LINE, Q2, FPS)
    assert early["verdict"] == "FAIL" and early["summary"]["early_words"] == ["S01:look"]


@needs_wavs
def test_v002_on_the_hand_run_v004_reference_is_pinned(tmp_path: Path) -> None:
    """Measured 2026-10-27: 33 words tested, 26 pass, 2 WARN (+3, +4 f), 0 late FAIL, 5 FAIL-early at -1 f (the correction's
    -45 dBFS edge vs the -35 dBFS voiced onset).  Pinned so a change of the gate or the rules is seen; the verdict is FAIL."""
    summary, _ = produce(tmp_path, recipe=V2)
    qa = json.loads((tmp_path / "out" / "WORD-TIMING-QA.json").read_text(encoding="utf-8"))["q1"]
    stats = qa["summary"]
    assert (stats["words_tested"], stats["pass"], stats["warn"], stats["late"], stats["early"]) == (33, 26, 2, 0, 5)
    assert stats["warn_words"] == ["S01_B:and(+3f)", "S06_B:and(+4f)"]
    assert stats["early_words"] == ["S03_B:fresh", "S04_B:both", "S06_A:from", "S06_B:cheese", "S06_B:ice"]
    assert {r["delta_f"] for r in qa["rows"] if r["status"] == "FAIL-early"} == {-1}
    assert summary["verdict"] == "FAIL" and qa["negative_control"]["detected"] is True
