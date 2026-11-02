"""The per-episode delivery contract through the real loader: ep04, a 60 s, a 110 s and a 150 s film."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from config_fixtures import REAL_EPISODE_ENGINE
from contract_fixtures import locked_world, make_script_world, plan, write_shots_from_plan
from engine.config import cli as contract_cli
from engine.config import loader, rules
from engine.config.budget import BudgetRefused
from engine.core.io import canonical_sha256, sha256_file

LINES_60 = [4.5] * 6
LINES_110 = [5.2] * 10
LINES_150 = [6.0] * 12


def build(world):
    return loader.build_config(world.episode_file, skill_root=world.skill_root, machine_path=world.machine_path)


def args(world, **kw) -> argparse.Namespace:
    base = dict(episode=str(world.episode_file), inputs=None, plan=False, write=False, target_seconds=None,
                min_seconds=None, max_seconds=None, pin=[], revision=None, from_episode=False)
    return argparse.Namespace(**{**base, **kw})


def run(world, **kw) -> int:
    return contract_cli.run_config_contract(args(world, **kw), skill_root=world.skill_root, machine_path=world.machine_path)


# ---- ep04: the live episode reproduces 3384 + 60 = 3444 from its own WAVs and clips ----------------------
def test_ep04_validates_at_3384_plus_60() -> None:
    report = loader.build_config(REAL_EPISODE_ENGINE / "episode.json")
    assert report.ok, report.violations
    frames = rules.timeline_frames(report.config.episode, report.config.domain)
    assert (frames["main_frames"], frames["end_card_frames"], frames["total_frames"]) == (3384, 60, 3444)
    assert report.config.episode["contract"]["vocab_count"] == 12
    assert report.config.delivery_contract_sha256 == sha256_file(REAL_EPISODE_ENGINE.parent / "DELIVERY-CONTRACT.json")


def test_ep04_plan_from_its_own_wavs_equals_the_locked_contract() -> None:
    planned = contract_cli.plan_contract(REAL_EPISODE_ENGINE / "episode.json")
    locked = json.loads((REAL_EPISODE_ENGINE / "episode.json").read_text(encoding="utf-8"))["contract"]
    assert planned["contract"] == locked
    assert (locked["main_frames"], locked["end_card_frames"], locked["total_frames"]) == (3384, 60, 3444)


def test_ep04_unpinned_floor_is_the_honest_minimum() -> None:
    planned = contract_cli.plan_contract(REAL_EPISODE_ENGINE / "episode.json")
    floor = sum(s.unpinned_low if s.unpinned_low is not None else s.low for s in planned["sections"])
    assert floor == 3433  # holds at their domain floors: 11 f shorter than the approved v015 cut


# ---- no domain edit for any length --------------------------------------------------------------------
@pytest.mark.parametrize("lines,vocab,seconds", [(LINES_60, [0.8] * 4, 60), (LINES_110, [0.8] * 8, 110),
                                                 (LINES_150, [0.8] * 12, 150)])
def test_other_lengths_validate_with_no_domain_edit(tmp_path: Path, lines, vocab, seconds) -> None:
    world, planned = locked_world(tmp_path, lines=lines, vocab=vocab, seconds=seconds)
    domain_file = world.skill_root / "domains" / "jenniejoy_cartoon_3d.json"
    before = sha256_file(domain_file)
    report = build(world)
    assert report.ok, report.violations
    assert report.config.episode["contract"]["total_frames"] == seconds * 30
    real = json.loads((loader.SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json").read_text(encoding="utf-8"))
    assert sha256_file(domain_file) == before and report.config.domain["delivery"] == real["delivery"]  # no domain edit
    assert rules.timeline_frames(report.config.episode, report.config.domain)["total_frames"] == seconds * 30


def test_a_short_film_is_balanced_not_just_valid(tmp_path: Path) -> None:
    world, planned = locked_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4, seconds=60)
    by_kind: dict[str, list[int]] = {}
    for section in planned["sections"]:
        by_kind.setdefault(section.kind, []).append(section.frames)
        assert section.low <= section.frames <= section.high
    assert min(by_kind["vocab_card"]) >= 90 and by_kind["logo_hold"][0] >= 60 and by_kind["end_card"] == [60]
    assert sum(by_kind["dialogue"]) > sum(s.low for s in planned["sections"] if s.kind == "dialogue")  # pauses used first


def test_shorter_than_the_floors_is_refused_exit_1_with_options_and_nothing_written(tmp_path: Path, capsys) -> None:
    world, inputs = make_script_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4)
    episode_before = world.episode_file.read_text(encoding="utf-8")
    code = run(world, plan=True, target_seconds=30, inputs=str(inputs))
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["ok"] is False and "below the sum of floors" in out["refused"]
    assert any(o["option"].startswith("drop") for o in out["options"]) and out["table"]
    assert run(world, write=True, target_seconds=30, inputs=str(inputs)) == 1
    assert world.episode_file.read_text(encoding="utf-8") == episode_before
    assert not (world.engine_dir.parent / "DELIVERY-CONTRACT.json").exists()


def test_longer_than_the_holds_can_reach_is_refused_too(tmp_path: Path) -> None:
    world, inputs = make_script_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4)
    with pytest.raises(BudgetRefused, match="never stretched"):
        plan(world, inputs, target_seconds=400)


def test_plan_prints_the_table_and_write_locks_it(tmp_path: Path, capsys) -> None:
    world, inputs = make_script_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4)
    planned = plan(world, inputs, target_seconds=65)
    write_shots_from_plan(world, planned)
    assert run(world, plan=True, target_seconds=65, inputs=str(inputs)) == 0
    captured = capsys.readouterr()
    assert "main " in captured.err and "= 1950 f" in captured.err and json.loads(captured.out)["total_frames"] == 1950
    assert run(world, write=True, target_seconds=65, inputs=str(inputs)) == 0
    written = json.loads(world.episode_file.read_text(encoding="utf-8"))
    assert written["contract"]["total_frames"] == 1950 and list(world.episode_file.parent.glob("episode.json.bak-*"))
    assert json.loads((world.engine_dir.parent / "DELIVERY-CONTRACT.json").read_text(encoding="utf-8"))["master"]["frames"] == 1950
    assert build(world).ok


# ---- the contract is hashed and bound ----------------------------------------------------------------------
def test_editing_the_contract_by_hand_fails_validate(tmp_path: Path) -> None:
    world, _ = locked_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4, seconds=60)
    world.edit_episode(lambda d: d["contract"].update(main_frames=d["contract"]["main_frames"] + 30,
                                                      total_frames=d["contract"]["total_frames"] + 30))
    text = " | ".join(build(world).violations)
    assert "sum of its sections" in text and "contract.sha256 does not match" in text


def test_the_delivery_file_is_generated_bound_and_stale_when_edited(tmp_path: Path) -> None:
    world, _ = locked_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4, seconds=60)
    delivery = world.engine_dir.parent / "DELIVERY-CONTRACT.json"
    first = build(world).config
    assert first.delivery_contract_sha256 == sha256_file(delivery)
    document = json.loads(delivery.read_text(encoding="utf-8"))
    document["master"]["frames"] += 1
    delivery.write_text(json.dumps(document, indent=2), encoding="utf-8")
    report = build(world)
    assert not report.ok and any("not the file generated from episode.contract" in v for v in report.violations)
    assert run(world, write=True, from_episode=True) == 0
    again = build(world).config
    assert again.config_sha256 == first.config_sha256 and again.delivery_contract_sha256 == first.delivery_contract_sha256
    delivery.unlink()
    assert any("does not exist" in v for v in build(world).violations)


def test_the_delivery_file_sha_changes_config_sha256(tmp_path: Path) -> None:
    world, _ = locked_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4, seconds=60)
    config = build(world).config
    body = {k: getattr(config, k) for k in ("machine", "domain", "recipes", "episode", "shots", "mouth_boxes")}
    assert config.config_sha256 != canonical_sha256(body, mode="ascii")  # the file sha is part of the hash


def test_a_contract_that_disagrees_with_a_review_config_total_fails_validate(tmp_path: Path) -> None:
    world, planned = locked_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4, seconds=60)
    review = world.engine_dir.parent / "review-config.json"
    total = planned["contract"]["total_frames"]
    review.write_text(json.dumps({"main_frames": total - 60, "end_hold_frames": 60, "total_frames_with_endlogo": total}),
                      encoding="utf-8")
    world.edit_episode(lambda d: d["files"].update(review_config="../review-config.json"))
    assert build(world).ok
    review.write_text(json.dumps({"main_frames": total - 60, "end_hold_frames": 60, "total_frames_with_endlogo": total - 90}),
                      encoding="utf-8")
    report = build(world)
    assert not report.ok and any(f"total {total - 90} f != contract total_frames {total}" in v for v in report.violations)
    review.write_text(json.dumps({"main_frames": 1, "total_frames_with_endlogo": total}), encoding="utf-8")
    assert any("main_frames 1 != contract" in v for v in build(world).violations)
    world.edit_episode(lambda d: d["files"].update(review_config="../../escape.json"))
    assert any("does not match pattern" in v for v in build(world).violations)


def test_contract_vs_domain_ranges_and_shots(tmp_path: Path) -> None:
    world, _ = locked_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4, seconds=60)

    def shrink(domain: dict) -> None:
        domain["delivery"]["length"]["main_frames_max"] = 900
        domain["delivery"]["sections"]["vocab_card"].update(min=200, max=200)

    world.edit(world.data("domains/jenniejoy_cartoon_3d.json"), shrink)
    text = " | ".join(build(world).violations)
    assert "outside the domain jenniejoy_cartoon_3d range 600..900" in text and "(vocab_card)" in text
    world.edit(world.engine_dir / "shots.json", lambda d: d["shots"][0]["clip"].update(frames=d["shots"][0]["clip"]["frames"] + 4))
    assert any("contract section S01_A" in v or "clip frames" in v for v in build(world).violations)


def test_a_film_without_a_contract_is_only_held_to_the_domain_range(tmp_path: Path) -> None:
    world, _ = make_script_world(tmp_path, lines=LINES_60, vocab=[0.8] * 4)
    planned = plan(world, world.engine_dir / "contract-inputs.json")
    write_shots_from_plan(world, planned)
    dialogue = sum(s.frames for s in planned["sections"] if s.kind == "dialogue") / 30
    world.edit_episode(lambda d: d.update(timeline={"intro_s": 2.0, "dialogue_s": dialogue, "outro_s": 20.0}))
    assert build(world).ok
    world.edit_episode(lambda d: d.update(timeline={"intro_s": 0.0, "dialogue_s": dialogue, "outro_s": 200.0}))
    assert any("outside the domain range" in v for v in build(world).violations)


def test_the_live_domain_has_no_length_lock_either() -> None:
    domain = json.loads((loader.SKILL_ROOT / "domains" / "newtecons_live_action.json").read_text(encoding="utf-8"))
    assert "duration_s" not in domain["delivery"]["master"] and domain["delivery"]["length"]["main_frames_min"] < 1080
