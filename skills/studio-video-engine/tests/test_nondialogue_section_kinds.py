"""Domain-declared non-dialogue sections stay inside the shared frame budget."""

from __future__ import annotations

import json

import pytest

from engine.config.budget import BudgetRefused, allocate, build_sections, section_kinds
from engine.config.loader import SKILL_ROOT
from engine.core.io import canonical_sha256
from engine.script.ingest import derive

def _domain(name: str) -> dict:
    return json.loads((SKILL_ROOT / "domains" / f"{name}.json").read_text(encoding="utf-8"))

def _episode(name: str) -> dict:
    return {"episode_id": "fixture", "film_id": "fixture", "title": "Fixture", "domain": name}

def _ntc_script() -> dict:
    return {
        "schema": "jjv/script/v1", "film_id": "fixture", "title": "Fixture",
        "domain": "newtecons_live_action", "duration_s": 13, "fps": 24,
        "structure": {"intro": {"duration_s": 4}},
        "film_sequence": [
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
        "vocabulary_cards": [],
        "character_references": {"speaker": {"speech_allowed": True}},
    }

def test_ntc_film_sequence_ingests_with_default_and_explicit_fixed_kinds() -> None:
    docs = derive(_ntc_script(), _episode("newtecons_live_action"), _domain("newtecons_live_action"))
    plan = docs["contract-plan.json"]
    rows = [(row["id"], row["kind"], row["frames"]) for row in plan["contract"]["sections"]]
    assert rows == [
        ("OPEN_BROLL", "broll", 36),
        ("S01_A", "dialogue", 48),
        ("PRODUCT_INSERT", "insert", 24),
        ("S02_A", "dialogue", 48),
        ("SITE_STILL", "motion_still", 60),
        ("END_TITLE", "title", 48),
        ("LOGO_HOLD", "logo_hold", 48),
    ]
    assert plan["total_frames"] == 312
    assert plan["contract"]["vocab_count"] == 0

def test_ntc_refusal_only_offers_kinds_the_domain_declares() -> None:
    domain = _domain("newtecons_live_action")
    inputs = {
        "intro_frames": 0,
        "lines": [{"id": "S01_A", "wav_s": 1.75}],
        "sequence": [
            {"id": "OPEN_BROLL", "kind": "broll", "duration_s": 1.0},
            {"id": "S01_A", "kind": "dialogue", "line_id": "S01_A"},
        ],
        "vocab": [], "end_card": True,
    }
    ceiling = sum(section.high for section in build_sections(domain, inputs))
    with pytest.raises(BudgetRefused) as caught:
        allocate(domain, inputs, target_frames=ceiling + 1)
    text = json.dumps(caught.value.options).lower()
    assert "vocab" not in text
    assert {option["kind"] for option in caught.value.options} <= set(section_kinds(domain))

def test_jenniejoy_derived_documents_are_byte_identical_to_the_baseline() -> None:
    domain = _domain("jenniejoy_cartoon_3d")
    episode = {"episode_id": "n18", "film_id": "n18", "title": "Test film", "domain": "jenniejoy_cartoon_3d"}
    script = {
        "schema": "jjv/script/v1", "film_id": "n18", "title": "Test film",
        "domain": "jenniejoy_cartoon_3d", "duration_s": 20,
        "fps": domain["frame_rates"]["delivery_fps"],
        "structure": {"intro": {"duration_s": 1}},
        "shots": [{"id": "S01_A", "speaker": "speaker", "speech_text": "Hello.",
                   "duration_s": 20, "visual": "A speaker."}],
        "vocabulary_cards": [{"term": "Moon", "target_duration_s": 0.8, "speaker": "speaker",
                              "shot_ids": ["S01_A"]}],
        "character_references": {"speaker": {"speech_allowed": True}},
    }
    docs = derive(script, episode, domain)
    assert canonical_sha256(docs, mode="ascii") == (
        "3fd37816a4bca4112240783757037d9f93a8b6173220e21ce640f5da55f9ec20")
