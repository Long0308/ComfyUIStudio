"""M8b(c): ``jjv editorial boundaries write`` builds boundaries.json from storyboard check + contract (+ measured rows)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from engine.config.loader import SKILL_ROOT
from engine.config.schema import validate
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.editorial import boundaries as table
from engine.editorial import boundaries_write as bw
from engine.editorial.boundaries_suggest_cli import main as suggest_main

DOMAIN = read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json")
SCHEMA = read_json(SKILL_ROOT / "schemas" / "boundaries.schema.json")
SHA = "a" * 64
SHOTS = ["S01_A", "S01_B", "S02_A"]
TERMS = ["Toys", "Blocks"]


def _check(ok: bool = True) -> dict:
    pairs = [{"from_shot": a, "to_shot": b, "framing": {"framing": "same_framing", "source": "declared", "conflict": None},
              "continuity": "unknown", "preset": "cut_push", "rule": "R2_same_framing_push", "problems": []}
             for a, b in zip(SHOTS, SHOTS[1:])]
    return {"schema": "jjv/storyboard-check/v1", "episode_id": "e", "ok": ok, "pairs": pairs}


def _input() -> dict:
    rows = [{"from_shot": "INTRO", "to_shot": "S01_A", "frame": 90, "kind": "graphic"}]
    rows += [{"from_shot": a, "to_shot": b, "frame": 240, "kind": "cut"} for a, b in zip(SHOTS, SHOTS[1:])]
    return {"schema": "jjv/boundaries-input/v1", "episode_id": "e", "boundaries": rows}


def _contract() -> dict:
    sections = [{"id": "INTRO", "kind": "intro", "frames": 90}] + [{"id": s, "kind": "dialogue", "frames": 150} for s in SHOTS]
    sections += [{"id": "LOGO_HOLD", "kind": "logo_hold", "frames": 60}]
    sections += [{"id": f"CARD_{i + 1:02d}", "kind": "vocab_card", "frames": 90, "term": t} for i, t in enumerate(TERMS)]
    sections += [{"id": "END_PLATE", "kind": "end_plate", "frames": 114}, {"id": "END_CARD", "kind": "end_card", "frames": 60}]
    return {"film_id": "e", "production_domain": "jenniejoy_cartoon_3d", "sections": sections}


def _media() -> dict:
    return {"cards_audio": {t: {"path": f"audio/{t}.wav", "sha256": SHA} for t in TERMS},
            "icons": {"dir": "icons", "terms": [{"term": t.lower(), "icon": f"{t}.png"} for t in TERMS], "hold_frames": 30,
                      "fade_frames": 4, "pop_frames": 4, "lead_frames": 2}}


def _build(**over):
    args = {"check": _check(), "bounds_input": _input(), "contract": _contract(), "domain": DOMAIN, "media": _media()}
    args.update(over)
    return bw.build_document(**args)


def test_complete_inputs_give_a_schema_valid_document_with_domain_floors() -> None:
    document, pending = _build()
    assert pending == [] and validate(document, SCHEMA, label="b") == []
    assert document["ending"]["derive_timeline"] is True
    assert (document["ending"]["logo_hold_frames"], document["ending"]["card_min_frames"],
            document["ending"]["end_card_frames"]) == (60, 90, 60)
    kinds = {(r["from_shot"], r["to_shot"]): r["type"] for r in document["boundaries"]}
    assert kinds[("INTRO", "S01_A")] == "bloom" and kinds[("S01_A", "S01_B")] == "cut_push"
    assert kinds[("S02_A", "OUTRO")] == "iris" and kinds[("CARD_Toys", "CARD_Blocks")] == "card_slide"
    assert kinds[("CARD_Blocks", "END_PLATE")] == "plate_in" and kinds[("END_PLATE", "ENDLOGO")] == "none"


def test_a_red_storyboard_check_is_refused() -> None:
    with pytest.raises(Refused, match="storyboard check is not green"):
        _build(check=_check(ok=False))
    bad = _check()
    bad["pairs"][0]["problems"] = ["x"]
    with pytest.raises(Refused, match="storyboard check is not green"):
        _build(check=bad)


def test_a_missing_contract_is_refused() -> None:
    with pytest.raises(Refused, match="contract"):
        _build(contract=None)


def test_episode_ids_must_agree() -> None:
    other = _input()
    other["episode_id"] = "zz"
    with pytest.raises(Refused, match="episode_id"):
        _build(bounds_input=other)


def test_a_pair_the_check_did_not_cover_is_refused() -> None:
    check = _check()
    check["pairs"].pop()
    with pytest.raises(Refused, match="S01_B -> S02_A"):
        _build(check=check)


def test_without_card_audio_the_result_is_pending_not_invented() -> None:
    document, pending = _build(media=None)
    assert any("cards audio" in p for p in pending) and any("icons" in p for p in pending)
    assert "cards" not in document


def test_a_whip_needs_a_direction_so_it_is_pending_unless_measured() -> None:
    check = _check()
    check["pairs"][0]["preset"] = "whip"
    _, pending = _build(check=check)
    assert any("direction" in p and "S01_A -> S01_B" in p for p in pending)


def test_measured_rows_replace_the_storyboard_choice() -> None:
    row = {"frame": 240, "from_shot": "S01_A", "to_shot": "S01_B", "class": "cut", "type": "cut", "frames": 0,
           "direction": 0, "motivation": "measured", "continuity": "unknown"}
    document, _ = _build(suggested={"episode_id": "e", "rows": [row]})
    chosen = next(r for r in document["boundaries"] if r["to_shot"] == "S01_B")
    assert chosen["type"] == "cut" and chosen["motivation"] == "measured"


def test_the_written_document_loads_through_the_engine_loader(tmp_path: Path) -> None:
    document, _ = _build()
    path = tmp_path / "b.json"
    path.write_text(json.dumps(document), encoding="utf8")
    loaded = table.load_document(path, SKILL_ROOT / "schemas" / "boundaries.schema.json", "e", DOMAIN)
    assert loaded["ending"]["end_card_frames"] == 60


def test_write_is_versioned_and_write_once(tmp_path: Path) -> None:
    document, _ = _build()
    first = bw.write_outputs(tmp_path, document, [])
    again = bw.write_outputs(tmp_path, document, [])
    assert first["version"] == 1 and again["version"] == 1 and again["sha256"] == first["sha256"]
    changed = copy.deepcopy(document)
    changed["ending"]["end_card_frames"] = 61
    second = bw.write_outputs(tmp_path, changed, [])
    assert second["version"] == 2 and (tmp_path / "versions" / "boundaries-v001.json").is_file()
    assert read_json(tmp_path / "boundaries.json")["ending"]["end_card_frames"] == 61


def test_pending_writes_a_draft_and_never_boundaries_json(tmp_path: Path) -> None:
    document, pending = _build(media=None)
    out = bw.write_outputs(tmp_path, document, pending)
    assert out["complete"] is False and not (tmp_path / "boundaries.json").exists()
    assert read_json(tmp_path / "versions" / "boundaries-draft-v001.json")["pending"] == pending


def test_cli_refuses_a_missing_contract(tmp_path: Path, capsys) -> None:
    for name, value in (("check.json", _check()), ("input.json", _input())):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf8")
    code = suggest_main(["write", "--storyboard-check", str(tmp_path / "check.json"), "--boundaries-input",
                         str(tmp_path / "input.json"), "--contract", str(tmp_path / "nope.json"), "--out", str(tmp_path / "o")])
    assert code != 0 and "contract" in capsys.readouterr().out


def test_schema_floors_are_not_literals() -> None:
    ending = SCHEMA["properties"]["ending"]["properties"]
    assert [ending[k]["minimum"] for k in ("logo_hold_frames", "end_card_frames", "card_min_frames")] == [1, 1, 1]
    floors = {k: bw.end_card.domain_floor(DOMAIN, k) for k in ("logo_hold_frames", "end_card_frames", "card_min_frames")}
    assert all(ending[k]["minimum"] <= v for k, v in floors.items())


def test_a_domain_floor_below_the_old_literals_is_accepted_by_the_schema() -> None:
    document, _ = _build()
    document["ending"]["card_min_frames"] = 70
    assert validate(document, SCHEMA, label="b") == []
