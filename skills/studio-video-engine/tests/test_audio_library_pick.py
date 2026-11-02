"""Library first: eligibility, scoring, the previous-episode rule, own-use stability, and the generation fall-through (no GPU)."""

from __future__ import annotations

import pytest
from test_audio_library_support import (BRIEF, EVIDENCE, GOOD_GATE, PICK_RECIPE, SCHEMA, bed_row, make_library, standard_rows)

from engine.audio import library, musicpick
from engine.core.io import read_json

DATA = read_json(PICK_RECIPE)
DOMAIN = "jenniejoy_cartoon_3d"
TARGET = 23.0  # a 20 s film + 3 s


def run_pick(tmp_path, rows, *, film="05-next", brief=BRIEF, target=TARGET, verify=True):
    lib = make_library(tmp_path, rows(tmp_path / "lib") if callable(rows) else rows)
    document, _ = library.load_registry(lib, SCHEMA)
    return musicpick.pick(DATA, document, lib_dir=lib, brief=brief, evidence=EVIDENCE, target_s=target, film=film,
                          domain_id=DOMAIN, verify=verify), lib


def test_the_bed_that_matches_the_brief_is_picked_and_the_reason_says_why(tmp_path) -> None:
    decision, _ = run_pick(tmp_path, standard_rows)
    assert decision["decision"] == "library" and decision["bed_id"] == "B-PASTORAL"
    top = decision["ranking"][0]
    assert top["components"]["instruments"] == 1.0 and top["components"]["tempo"] == 1.0 and top["components"]["key"] == 1.0
    assert top["components"]["shared_instruments"] == ["glockenspiel", "percussion", "piano", "ukulele"]
    assert "B-PASTORAL: score" in decision["reason"] and "100 BPM, C major" in decision["reason"]
    by_id = {r["id"]: r for r in decision["ranking"]}
    assert by_id["B-GUITAR"]["fits"] is False and by_id["B-LULLABY"]["eligible"] is True


def test_a_bed_shorter_than_the_film_plus_three_seconds_is_never_picked(tmp_path) -> None:
    decision, _ = run_pick(tmp_path, standard_rows)
    short = next(r for r in decision["ranking"] if r["id"] == "B-SHORT")
    assert short["eligible"] is False and "lasts 9.0 s, the film needs 23 s" in short["refused_because"][0]
    decision, _ = run_pick(tmp_path / "long", standard_rows, target=35.0)  # now every 30 s bed is too short
    assert decision["decision"] == "generate" and all(not r["eligible"] for r in decision["ranking"])
    assert decision["reason"].startswith("no bed is eligible") and "the film needs 35 s" in decision["reason"]


def test_a_bed_used_by_the_previous_episode_is_skipped_but_other_films_do_not_count(tmp_path) -> None:
    def rows(root):
        beds = standard_rows(root)
        beds[0]["used_in"] = [{"film": "04-earlier", "where": "x"}]
        beds[1]["used_in"] = [{"film": "02-older", "where": "x"}, {"film": "_brand/intro-v001", "where": "x"}]
        return beds
    decision, _ = run_pick(tmp_path, rows, film="05-next")
    assert decision["previous_film"] == "04-earlier"
    first = next(r for r in decision["ranking"] if r["id"] == "B-PASTORAL")
    assert first["eligible"] is False and first["refused_because"] == ["used by the previous episode 04-earlier"]
    assert decision["bed_id"] != "B-PASTORAL"
    # for episode 04 itself the previous one is 02 (04 is not "before" 04): B-PASTORAL is free again
    again, _ = run_pick(tmp_path / "b", rows, film="04-earlier")
    assert again["previous_film"] == "02-older" and again["bed_id"] == "B-PASTORAL"


def test_a_bed_the_same_episode_already_used_is_kept_even_when_the_brief_alone_would_not_pick_it(tmp_path) -> None:
    def rows(root):
        beds = standard_rows(root)
        beds[1]["used_in"] = [{"film": "05-next", "where": "film bed"}]  # guitar/marimba: a poor match for the brief
        return beds
    decision, _ = run_pick(tmp_path, rows, film="05-next")
    chosen = decision["ranking"][0]
    assert decision["bed_id"] == "B-GUITAR" == chosen["id"] and chosen["fits_by_content"] is False  # even above B-PASTORAL
    assert "this episode already used it" in decision["reason"] and chosen["score"] > chosen["score_without_own_use"]
    best_by_content = max(decision["ranking"], key=lambda r: r["score_without_own_use"])
    assert best_by_content["id"] == "B-PASTORAL"  # what a fresh episode would get stays visible in the table


def test_nothing_fits_means_generation_with_the_best_candidate_named(tmp_path) -> None:
    def rows(root):
        return [bed_row("B-GUITAR", "nylon guitar and marimba, 108 BPM F major", 30.0, 330.0, root),
                bed_row("B-LULLABY", "music box and celesta, 90 BPM G major", 30.0, 392.0, root)]
    decision, _ = run_pick(tmp_path, rows)
    assert decision["decision"] == "generate" and decision["bed_id"] is None
    assert decision["reason"].startswith("no bed fits: 2 eligible, best ") and "instrument match 0.0" in decision["reason"]


@pytest.mark.parametrize("change,why", [
    ({"status": "candidate"}, "is not approved"),
    ({"vocal_gate": {**GOOD_GATE, "vocal_minus_bed_rms_db": -20.0}}, "vocal-free numbers do not pass"),
    ({"vocal_gate": {**GOOD_GATE, "windows_over_-40dBFS": 2}}, "vocal-free numbers do not pass"),
    ({"vocal_gate": {**GOOD_GATE, "pass": False}}, "vocal-free numbers do not pass"),
    ({"domain": "other_domain"}, "belongs to domain"),
    ({"sha256": "1" * 64}, "bytes differ"),
])
def test_a_bed_that_fails_a_hard_rule_is_not_eligible(tmp_path, change, why) -> None:
    def rows(root):
        beds = standard_rows(root)
        beds[0].update(change)
        return beds
    decision, _ = run_pick(tmp_path, rows)
    row = next(r for r in decision["ranking"] if r["id"] == "B-PASTORAL")
    assert row["eligible"] is False and any(why in reason for reason in row["refused_because"]), row
    assert decision["bed_id"] != "B-PASTORAL"


def test_a_missing_file_makes_a_bed_ineligible_and_attributes_come_from_the_brief_field_when_present(tmp_path) -> None:
    def rows(root):
        beds = standard_rows(root)
        beds[0]["file"] = "gone.wav"
        beds[1]["brief"] = {"bpm": 100, "key": "C major", "instruments": "ukulele, glockenspiel, piano, percussion", "energy": "gentle"}
        return beds
    decision, _ = run_pick(tmp_path, rows)
    gone = next(r for r in decision["ranking"] if r["id"] == "B-PASTORAL")
    assert gone["refused_because"][0] == "file missing: gone.wav"
    assert decision["bed_id"] == "B-GUITAR" and decision["ranking"][0]["attributes"]["basis"] == "registry brief"


def test_ties_prefer_the_bed_that_was_used_by_fewer_films(tmp_path) -> None:
    def rows(root):
        a = bed_row("B-A", "ukulele, glockenspiel and soft piano with hand percussion, 100 BPM C major", 30.0, 262.0, root)
        b = bed_row("B-B", "ukulele, glockenspiel and soft piano with hand percussion, 100 BPM C major", 30.0, 270.0, root)
        a["used_in"] = [{"film": "01-old", "where": "x"}]
        return [a, b]
    decision, _ = run_pick(tmp_path, rows, film="05-next")
    assert decision["bed_id"] == "B-B"


def test_the_recipe_weights_must_sum_to_one_and_the_domain_must_match(tmp_path) -> None:
    from audio_fixtures import audio_world
    from engine.core.errors import Refused
    config, _ = audio_world(tmp_path)
    assert musicpick.load_pick_recipe(config).data["fit"]["weights"]["instruments"] == 0.5
    skill = tmp_path / "skill_copy" / "recipes" / "audio"
    skill.mkdir(parents=True)
    bad = {**DATA, "fit": {**DATA["fit"], "weights": {"instruments": 0.9, "tempo": 0.2, "key": 0.1, "energy": 0.2}}}
    import json
    (skill / "music-pick-v001.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(Refused, match="weights must sum to 1.0"):
        musicpick.load_pick_recipe(config, skill_root=tmp_path / "skill_copy")
    (skill / "music-pick-v001.json").write_text(json.dumps({**DATA, "domain": "other"}), encoding="utf-8")
    with pytest.raises(Refused, match="belongs to domain"):
        musicpick.load_pick_recipe(config, skill_root=tmp_path / "skill_copy")
