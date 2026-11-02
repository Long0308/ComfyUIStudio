"""Per-run section kinds on ``jjv script ingest --section-kinds``.

The domain file declares the vocabulary and every declared kind is on by default. A run may switch
kinds on or off, but only among the kinds the domain declares; the choice is written to the receipt
and never edits the domain file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.script.ingest import effective_section_kinds, ingest

NTC = "newtecons_live_action"
JJ = "jenniejoy_cartoon_3d"


def _domain_path(name: str) -> Path:
    return SKILL_ROOT / "domains" / f"{name}.json"


def _domain(name: str) -> dict:
    return json.loads(_domain_path(name).read_text(encoding="utf-8"))


def _ntc_script(*, rows: list[dict] | None = None, cards: list[dict] | None = None) -> dict:
    return {
        "schema": "jjv/script/v1", "film_id": "fixture", "title": "Fixture",
        "domain": NTC, "duration_s": 13, "fps": 24,
        "structure": {"intro": {"duration_s": 4}},
        "film_sequence": rows if rows is not None else [
            {"id": "OPEN_BROLL", "duration_s": 1.5, "dialogue": None},
            {"id": "S01_A", "duration_s": 2, "dialogue": {"speaker": "speaker", "text": "One."}},
            {"id": "PRODUCT_INSERT", "kind": "insert", "duration_s": 1, "dialogue": None},
            {"id": "S02_A", "duration_s": 2, "dialogue": {"speaker": "speaker", "text": "Two."}},
            {"id": "SITE_STILL", "kind": "motion_still", "duration_s": 2.5, "dialogue": None},
            {"id": "END_TITLE", "kind": "title", "duration_s": 2, "dialogue": None},
        ],
        "shots": [
            {"id": "S01_A", "speaker": "speaker", "speech_text": "One.", "duration_s": 2, "visual": "One."},
            {"id": "S02_A", "speaker": "speaker", "speech_text": "Two.", "duration_s": 2, "visual": "Two."},
        ],
        "vocabulary_cards": cards or [],
        "character_references": {"speaker": {"speech_allowed": True}},
    }


def _jj_script(*, cards: list[dict] | None = None) -> dict:
    domain = _domain(JJ)
    return {
        "schema": "jjv/script/v1", "film_id": "n18", "title": "Test film",
        "domain": JJ, "duration_s": 20,
        "fps": domain["frame_rates"]["delivery_fps"],
        "structure": {"intro": {"duration_s": 1}},
        "shots": [{"id": "S01_A", "speaker": "speaker", "speech_text": "Hello.",
                   "duration_s": 20, "visual": "A speaker."}],
        "vocabulary_cards": cards if cards is not None else [
            {"term": "Moon", "target_duration_s": 0.8, "speaker": "speaker", "shot_ids": ["S01_A"]}],
        "character_references": {"speaker": {"speech_allowed": True}},
    }


def _run(tmp_path: Path, script: dict, domain_name: str, spec: str | None = None) -> dict:
    """Ingest into a fresh derived folder outside the episode tree; returns the ingest result."""
    source = tmp_path / "src" / "episode"
    source.mkdir(parents=True, exist_ok=True)
    episode = {"episode_id": "fixture", "film_id": script["film_id"], "title": "Fixture", "domain": domain_name}
    episode_file = source / "episode.json"
    episode_file.write_text(json.dumps(episode), encoding="utf-8")
    script_file = tmp_path / "script.json"
    script_file.write_text(json.dumps(script), encoding="utf-8")
    return ingest(script_file, episode_file, tmp_path / "out", section_kinds_spec=spec)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ntc_default_has_no_vocab_card() -> None:
    kinds = effective_section_kinds(_domain(NTC), None)
    assert "vocab_card" not in kinds["effective"]
    assert {"broll", "insert", "motion_still", "title"} <= set(kinds["effective"])
    assert kinds["requested"] is None


def test_ntc_default_ingest_records_effective_kinds_in_receipt(tmp_path: Path) -> None:
    result = _run(tmp_path, _ntc_script(), NTC)
    receipt = json.loads((tmp_path / "out" / "ingest-receipt.json").read_text(encoding="utf-8"))
    assert result["section_kinds"]["effective"] == receipt["section_kinds"]["effective"]
    assert "vocab_card" not in receipt["section_kinds"]["effective"]
    assert receipt["section_kinds"]["requested"] is None
    assert result["status"] == "planned_unmeasured"


def test_turning_on_kind_the_domain_does_not_declare_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="'vocab_card' is not declared by domain 'newtecons_live_action'"):
        _run(tmp_path, _ntc_script(), NTC, spec="+vocab_card")
    assert not (tmp_path / "out").exists()


def test_unknown_kind_gets_a_named_refusal(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="'bogus' is not declared by domain 'newtecons_live_action'"):
        _run(tmp_path, _ntc_script(), NTC, spec="+bogus")
    with pytest.raises(Refused, match="is not a section kind name"):
        _run(tmp_path, _ntc_script(), NTC, spec="+Bad Kind")


def test_switching_off_a_kind_the_script_uses_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="'broll' is not enabled for domain 'newtecons_live_action' in this run"):
        _run(tmp_path, _ntc_script(), NTC, spec="-broll")


def test_switching_off_an_unused_kind_is_recorded(tmp_path: Path) -> None:
    rows = [row for row in _ntc_script()["film_sequence"] if row.get("kind") != "broll" and row["id"] != "OPEN_BROLL"]
    result = _run(tmp_path, _ntc_script(rows=rows), NTC, spec="-broll")
    assert result["section_kinds"]["requested"] == "-broll"
    assert "broll" not in result["section_kinds"]["effective"]
    assert {"insert", "motion_still", "title"} <= set(result["section_kinds"]["effective"])
    receipt = json.loads((tmp_path / "out" / "ingest-receipt.json").read_text(encoding="utf-8"))
    assert receipt["section_kinds"] == result["section_kinds"]


def test_structural_kind_cannot_be_switched_off(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="'dialogue' is structural and cannot be switched off"):
        _run(tmp_path, _ntc_script(), NTC, spec="-dialogue")


def test_repeated_kind_with_both_signs_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="more than once"):
        _run(tmp_path, _ntc_script(), NTC, spec="+title,-title")


def test_all_fixed_kinds_off_refuses_rather_than_ignoring_film_sequence(tmp_path: Path) -> None:
    spec = "-broll,-insert,-motion_still,-title"
    with pytest.raises(Refused, match="enables no fixed section kind"):
        _run(tmp_path, _ntc_script(), NTC, spec=spec)


def test_ntc_script_with_vocab_card_is_refused_not_a_key_error(tmp_path: Path) -> None:
    cards = [{"term": "Moon", "target_duration_s": 0.8, "speaker": "speaker", "shot_ids": ["S01_A"]}]
    with pytest.raises(Refused, match="vocabulary card\\(s\\) but section kind 'vocab_card' is not enabled "
                                      "for domain 'newtecons_live_action'"):
        _run(tmp_path, _ntc_script(cards=cards), NTC)


def test_jenniejoy_default_kinds_are_unchanged(tmp_path: Path) -> None:
    kinds = effective_section_kinds(_domain(JJ), None)
    assert kinds["effective"] == ["intro", "dialogue", "logo_hold", "vocab_card", "end_plate", "end_card"]
    result = _run(tmp_path, _jj_script(), JJ)
    assert result["section_kinds"]["effective"] == kinds["effective"]
    assert "vocab_card" in result["section_kinds"]["effective"]


def test_jenniejoy_vocab_card_off_is_refused_while_cards_exist(tmp_path: Path) -> None:
    with pytest.raises(Refused, match="vocabulary card\\(s\\) but section kind 'vocab_card' is not enabled"):
        _run(tmp_path, _jj_script(), JJ, spec="-vocab_card")


def test_jenniejoy_vocab_card_off_runs_without_cards_and_never_edits_the_domain_file(tmp_path: Path) -> None:
    before = _sha256(_domain_path(JJ))
    result = _run(tmp_path, _jj_script(cards=[]), JJ, spec="-vocab_card")
    assert "vocab_card" not in result["section_kinds"]["effective"]
    assert result["section_kinds"]["requested"] == "-vocab_card"
    assert _sha256(_domain_path(JJ)) == before
    assert "section_kinds" not in _domain(JJ)["delivery"]
