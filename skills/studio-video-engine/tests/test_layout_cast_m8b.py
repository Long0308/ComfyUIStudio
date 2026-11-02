"""M8b (a): ``layout plan --cast`` reads the ``cast-bindings.json`` that ``script ingest`` writes.

Ingest writes ``canonical_path`` / ``canonical_sha256`` + ``role`` per row (and ``reference_status: unbound`` rows
with null paths); older cast files (the shipped reuse cast) use ``canonical_png``. Both load; a row whose two
path (or sha) keys disagree is refused, never guessed.
"""

from __future__ import annotations

import json

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.layout.cast import bind, load_cast
from engine.script.ingest import derive
from images_fixtures import World, run_layout, sha


def _ingest_cast(world: World) -> dict:
    """The REAL ingest output for a two-role script whose `mother` role plays character `mom-alice`."""
    script = {"schema": "jjv/script/v1", "film_id": "t-ep", "title": "t", "duration_s": 110, "fps": 30,
              "status": "DRAFT", "structure": {"intro": {"duration_s": 3}},
              "character_references": {
                  "mother": {"speech_allowed": True, "canonical_path": world.mom.as_posix(),
                             "canonical_sha256": sha(world.mom)},
                  "alice": {"speech_allowed": True, "canonical_path": world.alice.as_posix(),
                            "canonical_sha256": sha(world.alice)},
                  "worker": {"speech_allowed": False, "canonical_path": None}},
              "voice_reference": {"mother": {"profile_id": "v-a"}, "alice": {"profile_id": "v-b"}},
              "vocabulary_speaker": "alice",
              "shots": [{"id": f"S{i:02d}_A", "speaker": "mother", "listener": "alice",
                         "speech_text": f"Look at word {i}.", "duration_s": 5.4, "visual": "two seated",
                         "continuity": {"setting_id": "g", "camera_id": "w", "seat_id": "b"}} for i in range(1, 11)],
              "vocabulary_cards": [{"term": f"word {i}", "target_duration_s": .8} for i in range(8)]}
    episode = {"episode_id": "t-ep", "film_id": "t-ep", "title": "t", "domain": "jenniejoy_cartoon_3d",
               "cast_roles": {"mother": "mom-alice"}}
    domain = read_json(SKILL_ROOT / "domains/jenniejoy_cartoon_3d.json")
    return derive(script, episode, domain)["cast-bindings.json"]


def _write(world: World, document: dict):
    path = world.cast_dir / "cast-bindings.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_ingest_cast_bindings_load_and_bind_roles_without_a_map(tmp_path) -> None:
    world = World(tmp_path)
    path = _write(world, _ingest_cast(world))
    cast = load_cast(path)
    assert set(cast) == {"mom-alice", "alice"}                       # the unbound `worker` row is not a reference
    assert cast["mom-alice"]["sha256"] == sha(world.mom)
    bound, unbound = bind(["mother", "alice", "worker"], cast, {})
    assert [(b["role"], b["character_id"]) for b in bound] == [("mother", "mom-alice"), ("alice", "alice")]
    assert unbound == ["worker"]
    assert set(bound[0]) == {"role", "character_id", "path", "sha256"}  # brief/plan rows keep their shape
    out = tmp_path / "layout"
    code, summary = run_layout(["plan", "--episode", str(world.root), "--out", str(out), "--cast", str(path),
                                "--machine", str(world.machine_path)])  # no --map: the row's role binds
    assert code == 0, summary
    plan = json.loads((out / "layout-plan.json").read_text("utf-8"))
    assert {c["role"]: c["character_id"] for c in plan["shots"][0]["cast"]} == {"mother": "mom-alice", "alice": "alice"}


def test_legacy_canonical_png_cast_still_loads_unchanged(tmp_path) -> None:
    world = World(tmp_path)
    cast = load_cast(world.cast)
    assert cast == {"alice": {"path": world.alice.resolve().as_posix(), "sha256": sha(world.alice)},
                    "mom-alice": {"path": world.mom.resolve().as_posix(), "sha256": sha(world.mom)}}


@pytest.mark.parametrize("extra, match", [
    ({"canonical_png": "other.png"}, "AMBIGUOUS_PATH"),       # two path keys naming different files
    ({"sha256": "0" * 64}, "AMBIGUOUS_SHA"),                  # two sha keys that disagree
    ({"canonical_sha256": None}, "HALF_BOUND"),               # a path without a sha
    ({"reference_status": "unbound"}, "UNBOUND_WITH_REF"),    # says unbound but carries a reference
])
def test_ambiguous_or_half_bound_rows_are_refused(tmp_path, extra, match) -> None:
    world = World(tmp_path)
    document = _ingest_cast(world)
    document["characters"][0].update(extra)
    with pytest.raises(Refused, match=match):
        load_cast(_write(world, document))


def test_same_value_under_two_keys_is_not_ambiguous_and_duplicate_roles_are_refused(tmp_path) -> None:
    world = World(tmp_path)
    document = _ingest_cast(world)
    row = document["characters"][0]
    row["canonical_png"] = row["canonical_path"]
    assert "mom-alice" in load_cast(_write(world, document))
    document["characters"][1]["role"] = "mother"
    with pytest.raises(Refused, match="DUPLICATE_ROLE"):
        load_cast(_write(world, document))


def test_explicit_map_still_wins_over_the_declared_role(tmp_path) -> None:
    world = World(tmp_path)
    cast = load_cast(_write(world, _ingest_cast(world)))
    bound, _ = bind(["mother"], cast, {"mother": "alice"})
    assert bound[0]["character_id"] == "alice"
