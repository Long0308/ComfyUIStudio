"""Critic T-E15e fix round: geometry pinned, allowed ports exact, --out guard, segment probe, naming."""

from __future__ import annotations

import copy
import json
import shutil
from fractions import Fraction
from pathlib import Path

import pytest

import parity_v004
from config_fixtures import make_world
from engine.config import loader
from engine.core.errors import Refused
from engine.core.io import canonical_sha256
from engine.media.probe import VideoInfo, probe_video
from engine.seedvr2 import chunking, plan as plan_mod, recipe as recipe_mod

V003 = "seedvr2/v003-7b-int8-tile768-int17-raw21"
FROZEN_SEGMENTS = parity_v004.SEGMENTS_ROOT
PORTS = {"$.1.inputs.file", "$.15.inputs.filename_prefix"}


def _recipe_path(world) -> Path:
    return world.data(f"recipes/{V003}.json")


def _build(world, **extra):
    return loader.build_config(world.episode_file, skill_root=world.skill_root,
                               machine_path=world.machine_path, **extra)


@pytest.fixture(scope="module")
def config():
    return loader.resolve_episode("04-milk-and-mom")


def _jjv():
    import importlib.util
    spec = importlib.util.spec_from_file_location("jjv_cli_m3b", loader.SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- geometry is pinned (critic probes G1/G2/G3) ----------------------------------------
GEOMETRIES = {
    "G1 core15 ctx6 max27": dict(core_frames=15, context_frames_each_side=6, max_raw_segment_frames=27),
    "G2 core11 ctx5 max21": dict(core_frames=11, context_frames_each_side=5),
    "G3 core17 ctx4 max25": dict(core_frames=17, context_frames_each_side=4, max_raw_segment_frames=25),
}


@pytest.mark.parametrize("label", sorted(GEOMETRIES))
def test_re_balanced_geometry_is_refused_at_config(tmp_path: Path, label: str) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["geometry"].update(GEOMETRIES[label]))
    report = _build(world)
    assert any("geometry canonical sha256" in v for v in report.violations), report.violations
    assert report.config is None


def test_widened_envelope_is_also_contradicted_by_the_receipt(tmp_path: Path) -> None:
    for label in ("G1 core15 ctx6 max27", "G3 core17 ctx4 max25"):
        world = make_world(tmp_path / label[:2])
        world.edit(_recipe_path(world), lambda d: d["geometry"].update(GEOMETRIES[label]))
        joined = "\n".join(_build(world).violations)
        assert "qualification receipt frames.raw 21 != recipe" in joined, label
        assert "qualification receipt qualifies_only.raw_frames 21 != recipe" in joined, label


@pytest.mark.parametrize("key,value,text", [
    ("tile_size", 512, "qualifies_only.tile_size 768 != recipe 512"),
    ("tile_overlap", 32, "qualifies_only.tile_overlap 64 != recipe 32"),
    ("internal_sampler_max_pixel_frames", 13, "qualifies_only.internal_sampler_max_pixel_frames 17 != recipe 13"),
])
def test_receipt_tile_and_internal_frames_must_equal_the_recipe(tmp_path: Path, key, value, text) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["geometry"].update({key: value}))
    assert any(text in v for v in _build(world).violations)


def test_geometry_and_block_pins_are_both_rewritten_still_refused_by_the_receipt(tmp_path: Path) -> None:
    """Coordinated edit of values AND their pin: the receipt still contradicts the envelope."""
    world = make_world(tmp_path)

    def forge(data: dict) -> None:
        data["geometry"].update(GEOMETRIES["G3 core17 ctx4 max25"])
        data["pilot"]["geometry_block_sha256"] = canonical_sha256(data["geometry"], mode="ascii")

    world.edit(_recipe_path(world), forge)
    report = _build(world)
    assert not any("geometry canonical sha256" in v for v in report.violations)
    assert any("qualification receipt frames.raw 21 != recipe 25" in v for v in report.violations)


def test_plan_refuses_a_recipe_whose_geometry_differs_from_the_pin_with_or_without_segments(config) -> None:
    for label in sorted(GEOMETRIES):
        recipe = copy.deepcopy(config.recipes["seedvr2"])
        recipe["geometry"].update(GEOMETRIES[label])
        forged = loader.ResolvedConfig(**{**config.__dict__, "recipes": {"seedvr2": recipe}})
        for root in (None, FROZEN_SEGMENTS):
            with pytest.raises(Refused, match="geometry canonical sha256"):
                plan_mod.build_plan(forged, repo_root=loader.REPO_ROOT, segments_root=root)


def test_plan_refuses_a_recipe_block_differing_from_its_pin(config) -> None:
    recipe = copy.deepcopy(config.recipes["seedvr2"])
    recipe["graph_recipe"]["denoise"] = 0.5
    forged = loader.ResolvedConfig(**{**config.__dict__, "recipes": {"seedvr2": recipe}})
    with pytest.raises(Refused, match="graph_recipe canonical sha256"):
        plan_mod.build_plan(forged, repo_root=loader.REPO_ROOT)


def test_real_geometry_pin_is_self_consistent() -> None:
    recipe = json.loads((loader.SKILL_ROOT / "recipes" / f"{V003}.json").read_text("utf-8"))
    assert canonical_sha256(recipe["geometry"], mode="ascii") == recipe["pilot"]["geometry_block_sha256"]


# ---- allowed ports are exactly input file + output prefix -------------------------------
def test_widened_port_allow_list_is_refused_at_config(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["allowed_api_diff_paths"].append("$.10.inputs.seed"))
    assert any("allowed_api_diff_paths must be exactly" in v for v in _build(world).violations)


def test_narrowed_port_allow_list_is_refused_too(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d.update(allowed_api_diff_paths=["$.1.inputs.file"]))
    assert any("allowed_api_diff_paths must be exactly" in v for v in _build(world).violations)


def test_clone_refuses_any_allow_list_other_than_the_two_ports(config) -> None:
    recipe = config.recipes["seedvr2"]
    pilot = recipe_mod.load_pilot_graph(recipe, loader.REPO_ROOT)
    for paths in (sorted(PORTS | {"$.10.inputs.seed"}), ["$.1.inputs.file"], []):
        bad = dict(recipe, allowed_api_diff_paths=paths)
        with pytest.raises(Refused, match="allowed_api_diff_paths must be exactly"):
            recipe_mod.clone_api_graph(pilot, bad, input_name="a.mp4", output_prefix="p/q")
    graph, changes = recipe_mod.clone_api_graph(pilot, recipe, input_name="a.mp4", output_prefix="p/q")
    assert {c["path"] for c in changes} == PORTS


def test_plan_with_a_widened_allow_list_is_refused(config) -> None:
    recipe = dict(config.recipes["seedvr2"], allowed_api_diff_paths=sorted(PORTS | {"$.10.inputs.seed"}))
    forged = loader.ResolvedConfig(**{**config.__dict__, "recipes": {"seedvr2": recipe}})
    with pytest.raises(Refused, match="allowed_api_diff_paths must be exactly"):
        plan_mod.build_plan(forged, repo_root=loader.REPO_ROOT, segments_root=FROZEN_SEGMENTS)


# ---- --out guard: ancestors, equality, freshness ----------------------------------------
def test_out_that_is_an_ancestor_of_or_equal_to_a_protected_root_is_refused(config) -> None:
    episode, comfy = Path(config.episode_root), Path(config.machine["comfy"]["root"])
    protected = [episode, comfy, FROZEN_SEGMENTS, loader.REPO_ROOT / "production-local", loader.REPO_ROOT]
    for bad in (loader.REPO_ROOT, loader.REPO_ROOT / "production-local", episode.parent, episode, comfy,
                comfy.parent, FROZEN_SEGMENTS, FROZEN_SEGMENTS.parent, episode / "technical" / "x"):
        with pytest.raises(Refused, match="protected tree"):
            plan_mod.refuse_output_inside(bad, protected)


def test_out_must_be_absent_or_an_empty_directory(tmp_path: Path) -> None:
    plan_mod.require_fresh_out(tmp_path / "absent")
    empty = tmp_path / "empty"
    empty.mkdir()
    plan_mod.require_fresh_out(empty)
    full = tmp_path / "full"
    full.mkdir()
    (full / "x.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Refused, match="not empty"):
        plan_mod.require_fresh_out(full)
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    with pytest.raises(Refused, match="not a directory"):
        plan_mod.require_fresh_out(afile)


def test_cli_refuses_an_ancestor_out_and_a_non_empty_out(tmp_path: Path, capsys) -> None:
    cli = _jjv()
    code = cli.main(["seedvr2", "plan", "--episode", "04-milk-and-mom", "--out", str(loader.REPO_ROOT / "production-local")])
    assert code == 1 and "protected tree" in json.loads(capsys.readouterr().out)["error"]
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "old.json").write_text("{}", encoding="utf-8")
    code = cli.main(["seedvr2", "plan", "--episode", "04-milk-and-mom", "--out", str(tmp_path / "used")])
    assert code == 1 and "not empty" in json.loads(capsys.readouterr().out)["error"]
    assert [p.name for p in (tmp_path / "used").iterdir()] == ["old.json"]


# ---- bound segments are probed for fps and size, like the source ------------------------
def _segment_root(tmp_path: Path) -> Path:
    root = tmp_path / "segments"
    target = root / "S01_A" / "chunks" / "chunk-0000"
    target.mkdir(parents=True)
    shutil.copyfile(FROZEN_SEGMENTS / "S01_A" / "chunks" / "chunk-0000" / "source-segment.mp4",
                    target / "source-segment.mp4")
    return root


@pytest.mark.parametrize("fps,width,height,text", [
    (Fraction(30), 864, 480, "segment fps 30 != source fps 24"),
    (Fraction(24), 640, 360, "segment size 640x360 != source 864x480"),
])
def test_segment_with_other_fps_or_size_than_its_source_is_refused(tmp_path: Path, config, fps, width, height, text) -> None:
    def probe(path, *, count_packets=False):
        info = probe_video(path, count_packets=count_packets)
        if path.name == "source-segment.mp4":
            return VideoInfo(frames=info.frames, width=width, height=height, fps=fps)
        return info
    with pytest.raises(Refused, match=text):
        plan_mod.build_plan(config, repo_root=loader.REPO_ROOT, segments_root=_segment_root(tmp_path), probe=probe)


# ---- naming -----------------------------------------------------------------------------
def test_plan_chunks_have_no_redundant_start_end_keys(config) -> None:
    result = plan_mod.build_plan(config, repo_root=loader.REPO_ROOT)
    chunk = result.plan["shots"][0]["chunks"][0]
    assert "start" not in chunk and "end" not in chunk
    assert chunk["segment_start_frame"] == 0 and chunk["segment_end_frame_exclusive"] == 17


def test_seam_pair_output_frames_are_named_as_indices(config) -> None:
    result = plan_mod.build_plan(config, repo_root=loader.REPO_ROOT)
    pair = result.plan["shots"][0]["seam_pairs_to_inspect"][0]
    assert pair["left_expected_core_output_frame_index"] == 12 and pair["right_expected_core_output_frame_index"] == 0
    assert "left_expected_core_output_frame" not in pair
    chunks = chunking.seam_pairs([{"chunk_name": "a", "core_end_frame_exclusive": 13, "core_start_frame": 0,
                                   "core_frames": 13, "segment_start_frame": 0, "segment_end_frame_exclusive": 17},
                                  {"chunk_name": "b", "core_end_frame_exclusive": 26, "core_start_frame": 13,
                                   "core_frames": 13, "segment_start_frame": 9, "segment_end_frame_exclusive": 30}])
    assert chunks[0]["left_expected_core_output_frame_index"] == 12
