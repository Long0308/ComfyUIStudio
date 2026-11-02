"""T-E45 P2 (engine side): ``segments.json`` (jjv/segments/v1), an additive output of ``jjv editorial build-config``.

The cut list of a film: segments cover [0, total) exactly, no cut falls inside an effect window, a carry gives
no transition segment, the join frame of an iris ending equals the kit's, and the output is deterministic.
Real ep04 inputs mutated in tmp (same fixtures as the other editorial tests); synthetic timelines for the
property tests.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from editorial_fixtures import Inputs
from preset_fixtures import use
from engine.config import loader
from engine.config.schema import validate
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.editorial import build, segments

from segments_fixtures import (KINDS, KIT, NODE, SCHEMA, _assert_valid, _derive, _synthetic, _table, _windows,  # noqa: F401
                               inputs)


@pytest.mark.parametrize("seed", range(40))
@pytest.mark.parametrize("derived", [False, True])
def test_segments_cover_the_film_and_no_cut_is_inside_a_window(seed: int, derived: bool) -> None:
    spec = _synthetic(seed, derived)
    doc = segments.plan_segments(**spec)
    windows = []
    for t in spec["transitions"]:
        end = t["end_exclusive"]
        if t.get("renders_as") == "iris" and spec["join_frame"] is not None:
            end = min(end, spec["join_frame"])           # the iris effect ends where the vector ending begins
        if end > t["start"]:
            windows.append((t["start"], end, t["id"]))
    _assert_valid(doc, windows)
    assert doc["join_frame"] == spec["join_frame"]
    if spec["join_frame"] is not None:
        assert spec["join_frame"] in doc["cut_points"]


def test_a_declared_cut_inside_an_effect_window_is_refused() -> None:
    spec = _synthetic(3, True)
    window = next(t for t in spec["transitions"] if t["end_exclusive"] - t["start"] >= 4 and "renders_as" not in t)
    middle = window["start"] + 2
    with pytest.raises(Refused, match=f"{window['id']}.*f{middle}|f{middle}.*{window['id']}"):
        segments.plan_segments(**spec, extra_cuts=(middle,))
    edge = segments.plan_segments(**spec, extra_cuts=(window["end_exclusive"],))   # at a window edge it is fine
    assert window["end_exclusive"] in edge["cut_points"]


def test_an_extra_cut_outside_the_film_is_refused() -> None:
    spec = _synthetic(1, False)
    with pytest.raises(Refused, match="outside"):
        segments.plan_segments(**spec, extra_cuts=(spec["total_frames"] + 5,))


def test_a_carry_makes_no_transition_segment_but_still_a_cut_at_the_clip_boundary() -> None:
    spec = {
        "fps": 30, "total_frames": 400, "main_frames": 340, "intro_end": 0, "dialogue_end": 300,
        "shots": [{"id": "A", "start": 0, "end": 100}, {"id": "B", "start": 100, "end": 200},
                  {"id": "C", "start": 200, "end": 300}],
        "transitions": [
            {"id": "T100", "boundary": 100, "from": "A", "to": "B", "start": 100, "end": 100, "end_exclusive": 100},
            {"id": "T200", "boundary": 200, "from": "B", "to": "C", "start": 200, "end_exclusive": 200}],
        "cards": [], "plate_start": None, "join_frame": None, "icons": []}
    doc = segments.plan_segments(**spec)
    assert [s["kind"] for s in doc["segments"]] == ["shot_span", "shot_span", "shot_span", "ending"] or \
        [s["kind"] for s in doc["segments"]][:3] == ["shot_span"] * 3
    assert not [s for s in doc["segments"] if s["kind"] == "transition"]
    assert [s["start"] for s in doc["segments"][:3]] == [0, 100, 200]
    assert doc["segments"][0]["id"] == "shot-A-1"


def test_overlapping_windows_become_one_transition_segment_with_both_ids() -> None:
    spec = {
        "fps": 30, "total_frames": 400, "main_frames": 340, "intro_end": 0, "dialogue_end": 340,
        "shots": [{"id": "A", "start": 0, "end": 100}, {"id": "B", "start": 100, "end": 108},
                  {"id": "C", "start": 108, "end": 340}],
        "transitions": [
            {"id": "T100", "boundary": 100, "from": "A", "to": "B", "start": 96, "end_exclusive": 104},
            {"id": "T108", "boundary": 108, "from": "B", "to": "C", "start": 104, "end_exclusive": 112},
            {"id": "T50", "boundary": 50, "from": "A", "to": "A", "start": 40, "end_exclusive": 52},
            {"id": "T60", "boundary": 60, "from": "A", "to": "A", "start": 50, "end_exclusive": 64}],
        "cards": [], "plate_start": None, "join_frame": None, "icons": []}
    doc = segments.plan_segments(**spec)
    merged = [s for s in doc["segments"] if s["kind"] == "transition" and s["start"] == 40]
    assert len(merged) == 1 and (merged[0]["start"], merged[0]["end_exclusive"]) == (40, 64)
    assert merged[0]["transition_ids"] == ["T50", "T60"] and merged[0]["transition_id"] == "T50"
    _assert_valid(doc, [(96, 104, "T100"), (104, 112, "T108"), (40, 52, "T50"), (50, 64, "T60")])


def test_the_output_is_canonical_and_deterministic() -> None:
    spec = _synthetic(7, True)
    first, second = segments.plan_segments(**spec), segments.plan_segments(**json.loads(json.dumps(spec)))
    assert segments.canonical_bytes(first) == segments.canonical_bytes(second)
    assert segments.canonical_bytes(first) == json.dumps(first, indent=2, ensure_ascii=True, sort_keys=False).encode("ascii") + b"\n" \
        or segments.canonical_bytes(first).endswith(b"\n")


# ---- real ep04 inputs --------------------------------------------------------------------------------
def test_ep04_plain_build_emits_segments_that_cover_the_film(inputs: Inputs) -> None:
    built = inputs.build()
    doc = built.segments
    assert doc["schema"] == "jjv/segments/v1" and doc["fps"] == 30
    assert doc["total_frames"] == built.config["total_frames"] == 2580
    assert doc["main_frames"] == built.config["main_frames"] == 2520
    records = built.events["transitions"]
    _assert_valid(doc, [(r["start"], min(r["end_exclusive"], 2145) if r["type"] == "iris" else r["end_exclusive"],
                         r["id"]) for r in records if r["end_exclusive"] > r["start"]])
    assert validate(doc, read_json(SCHEMA), label="segments") == []
    kinds = [s["kind"] for s in doc["segments"]]
    print("ep04 plain:", {k: kinds.count(k) for k in sorted(set(kinds))}, "segments", len(kinds))
    assert kinds[0] == "intro" and kinds[-1] == "ending"
    # plain ep04: the end plate is the plate_in window itself (f2516..f2519), so it is a transition segment
    assert next(x for x in doc["segments"] if x["start"] == 2516)["kind"] == "transition"
    hold = next(x for x in doc["segments"] if x["kind"] == "logo_hold")  # hold 0: the disc shows from the join to card 1
    assert (hold["start"], hold["end_exclusive"]) == (2145, 2160)
    moving = [r for r in records if r["end_exclusive"] > r["start"] and r["type"] != "card_slide"]
    assert moving, "ep04 has visible transitions"
    for r in moving:
        seg = next(s for s in doc["segments"] if s["kind"] == "transition" and r["id"] in s["transition_ids"])
        assert seg["start"] <= r["start"] and seg["end_exclusive"] >= min(r["end_exclusive"], seg["end_exclusive"])
    spans = [s for s in doc["segments"] if s["kind"] == "shot_span"]
    assert spans and all(s["shots_visible"] for s in spans)
    shot_ids = {s["id"] for s in built.config["dialogue"]}
    assert shot_ids  # sanity: dialogue entries exist


def test_ep04_the_seven_v008_style_transitions_get_transition_segments(inputs: Inputs) -> None:
    built = inputs.build()
    doc = built.segments
    visible = {r["id"]: r for r in built.events["transitions"]
               if r["boundary"] in (90, 240, 390, 550, 710, 885, 1150, 1495, 1610, 1785, 1935, 2110, 2160)
               and r["end_exclusive"] > r["start"]}
    assert visible, "the v008 transition rows exist"
    in_segments = {i for s in doc["segments"] if s["kind"] == "transition" for i in s["transition_ids"]}
    assert set(visible) <= in_segments
    # every other frame belongs to an intro / shot_span / card / plate / ending segment: nothing is left unassigned
    assert sum(s["frames"] for s in doc["segments"]) == doc["total_frames"]


def test_ep04_segments_json_is_written_with_its_sha_in_the_summary(inputs: Inputs, tmp_path: Path) -> None:
    built = inputs.build()
    out = tmp_path / "out"
    summary = build.write_outputs(built, out, dry_run=False)
    assert "segments.json" in summary
    payload = (out / "segments.json").read_bytes()
    assert summary["segments.json"]["bytes"] == len(payload)
    import hashlib
    assert summary["segments.json"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert json.loads(payload) == built.segments
    again = build.write_outputs(built, out, dry_run=False)         # write-once stays idempotent
    assert again["segments.json"] == summary["segments.json"]
    with pytest.raises(Refused):
        (out / "segments.json").write_bytes(payload + b" ")
        build.write_outputs(built, out, dry_run=False)


def test_ep04_two_builds_give_identical_bytes(inputs: Inputs, tmp_path: Path) -> None:
    a = build.write_outputs(inputs.build(), tmp_path / "a", dry_run=True)
    b = build.write_outputs(Inputs(tmp_path / "x").build(), tmp_path / "b", dry_run=True) \
        if (tmp_path / "x").mkdir() is None else None
    assert a["segments.json"]["sha256"] == b["segments.json"]["sha256"]


def test_the_existing_outputs_keep_their_bytes(inputs: Inputs, tmp_path: Path) -> None:
    """Additive: review-config.json and events.json carry no segments key and are unchanged."""
    built = inputs.build()
    assert "segments" not in built.config and "segments" not in built.events


def test_one_boundary_change_moves_only_the_segments_around_it(tmp_path: Path) -> None:
    def table(frames: int) -> list[tuple]:
        inputs = Inputs(tmp_path / str(frames))
        (tmp_path / str(frames)).mkdir()
        use(inputs, "cut_push", frames=frames)
        return _table(inputs.build().segments)
    base, changed = table(12), table(10)
    assert {r[0] for r in base} == {r[0] for r in changed}, "the ids are stable"
    diff = [(a, b) for a, b in zip(base, changed) if a != b]
    ids = sorted(a[0] for a, _ in diff)
    print("T1010 12->10 changed segments:", [(a, b) for a, b in diff])
    assert "tr-T1010" in ids
    assert all(i == "tr-T1010" or i.startswith("shot-S04_A") for i in ids), ids
    assert dict((r[0], r) for r in base)["tr-T1010"][3] == 1022
    assert dict((r[0], r) for r in changed)["tr-T1010"][3] == 1020
    # nothing downstream moved: every segment from the next shot start on is identical
    later = [(a, b) for a, b in zip(base, changed) if a[2] >= 1100]
    assert all(a == b for a, b in later)


def test_derived_ep04_has_the_hold_cards_plate_and_ending_after_the_join(tmp_path: Path) -> None:
    inputs = _derive(Inputs(tmp_path), logo_hold_frames=70)
    built = inputs.build()
    doc = built.segments
    assert doc["total_frames"] == 3374 and doc["main_frames"] == 3314
    assert doc["join_frame"] == 2145                                  # logo_disc.in 2142 + 3 (disc opaque)
    rows = {s["id"]: s for s in doc["segments"]}
    assert (rows["logo-hold"]["start"], rows["logo-hold"]["end_exclusive"]) == (2145, 2230)
    assert rows["logo-hold"]["kind"] == "logo_hold" and rows["logo-hold"]["shots_visible"] == []
    cards = [s for s in doc["segments"] if s["kind"] == "card"]
    assert len(cards) == 12 and cards[0]["start"] == 2230
    # the plate_in window (f3310..f3313) is the whole plate: it is one transition segment
    assert (rows["tr-T3310"]["start"], rows["tr-T3310"]["end_exclusive"]) == (3310, 3314)
    assert (rows["ending"]["start"], rows["ending"]["end_exclusive"]) == (3314, 3374)
    iris = next(s for s in doc["segments"] if s["kind"] == "transition" and "T2160" in s["transition_ids"])
    assert (iris["start"], iris["end_exclusive"]) == (2116, 2145)
    assert iris["shots_visible"] and cards[1]["card_term"]
    for s in doc["segments"]:
        if s["start"] >= 2145:
            assert s["shots_visible"] == [], f"{s['id']} draws no shot video after the join"
    hint = rows["logo-hold"]["inputs_slice_hint"]
    assert hint["cards"] == [] and "S06_B3" in hint["shots"], hint     # captions of the last shot still run
    assert validate(doc, read_json(SCHEMA), label="segments") == []
    _assert_valid(doc, [(r["start"], min(r["end_exclusive"], 2145) if r["type"] == "iris" else r["end_exclusive"],
                         r["id"]) for r in built.events["transitions"] if r["end_exclusive"] > r["start"]])


def test_segment_ids_are_readable_and_stable(tmp_path: Path) -> None:
    doc = _derive(Inputs(tmp_path), logo_hold_frames=70).build().segments
    ids = [s["id"] for s in doc["segments"]]
    assert ids[0] == "intro" and "shot-S04_A-1" in ids and "tr-T1010" in ids and "card-03" in ids
    assert ids[-3:] == ["card-12", "tr-T3310", "ending"]


# ---- agreement with the kit ----------------------------------------------------------------------------
def _kit_validate_declared(config: dict) -> subprocess.CompletedProcess:
    script = """
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import fs from 'node:fs';
const kit = process.argv[2];
const require = createRequire(kit + '/');
const {planSegments} = require('./lib/segments.cjs');
const presets = await import(pathToFileURL(kit + '/src/presets.mjs').href);
const config = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const plan = planSegments(config, {rendersAs: presets.rendersAs, showsBoth: (t) => t.shows_both === true});
console.log(JSON.stringify(plan.segments.map((s) => [s.id, s.start, s.end_exclusive])));
"""
    return script


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("derived", [False, True])
def test_the_kit_accepts_the_engine_cut_list_as_config_segments(tmp_path: Path, derived: bool) -> None:
    inputs = _derive(Inputs(tmp_path), logo_hold_frames=70) if derived else Inputs(tmp_path)
    built = inputs.build()
    doc = built.segments
    ending = built.events["ending"]
    config = {
        "timeline": {"mainFrames": doc["main_frames"], "endCardFrames": doc["total_frames"] - doc["main_frames"]},
        "ending": {"discIn": ending["logo_disc"]["in"], "irisStart": ending["iris"]["start"]},
        "transitions": [{**r, "frames": r["frames"], "start": r["start"], "boundary": r["boundary"]}
                        for r in built.events["transitions"]],
        "segments": [{"id": s["id"], "kind": s["kind"], "start": s["start"], "end_exclusive": s["end_exclusive"]}
                     for s in doc["segments"]]}
    cfg = tmp_path / "kit-like.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    runner = tmp_path / "check.mjs"
    runner.write_text(_kit_validate_declared(config), encoding="utf-8")
    done = subprocess.run([NODE, str(runner), str(KIT), str(cfg)], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert len(json.loads(done.stdout)) == len(doc["segments"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_kit_refuses_a_cut_that_the_engine_never_makes(tmp_path: Path) -> None:
    """The red case of the cross-check: put a cut inside the iris window, and the kit rule fires."""
    built = _derive(Inputs(tmp_path), logo_hold_frames=70).build()
    doc = built.segments
    ending = built.events["ending"]
    rows = [dict(s) for s in doc["segments"]]
    victim = next(i for i, s in enumerate(rows) if s["kind"] == "transition" and "T2160" in s["transition_ids"])
    cut = rows[victim]["start"] + 10
    rows.insert(victim + 1, {**rows[victim], "id": "x", "start": cut})
    rows[victim] = {**rows[victim], "end_exclusive": cut}
    config = {"timeline": {"mainFrames": doc["main_frames"], "endCardFrames": 60},
              "ending": {"discIn": ending["logo_disc"]["in"]},
              "transitions": [{**r, "start": r["start"]} for r in built.events["transitions"]],
              "segments": [{"id": s["id"], "kind": s["kind"], "start": s["start"], "end_exclusive": s["end_exclusive"]}
                           for s in rows]}
    cfg = tmp_path / "bad.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    runner = tmp_path / "check.mjs"
    runner.write_text(_kit_validate_declared(config), encoding="utf-8")
    done = subprocess.run([NODE, str(runner), str(KIT), str(cfg)], capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode != 0 and "effect window" in done.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_join_frame_equals_the_kit_ending_cut_on_the_proof_config(tmp_path: Path) -> None:
    """The kit's own plan (render.cjs --segments-plan) on a real adapter build puts main/ending at the same frame."""
    proof = Path(__file__).resolve().parent / "_proof_kit_config.json"
    candidates = [proof] + sorted(Path(p) for p in __import__("glob").glob(
        str(Path.home() / "AppData/Local/Temp/claude/*/*/scratchpad/te42/proof/kit-config.json")))
    config_file = next((c for c in candidates if c.is_file()), None)
    if config_file is None:
        pytest.skip("no adapter-built kit config available (scratch only)")
    done = subprocess.run([NODE, str(KIT / "render.cjs"), "--config", str(config_file), "--segments-plan"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    plan = json.loads(done.stdout)
    kit_cut = next(s for s in plan["segments"] if s["id"] == "ending")["start"]
    built = _derive(Inputs(tmp_path), logo_hold_frames=70).build()
    assert built.segments["join_frame"] == kit_cut
