"""M3: SeedVR2 recipe helpers, chunking and plan v2 (plan only; nothing cut or submitted)."""

from __future__ import annotations

import copy
import json
import shutil
from fractions import Fraction
from pathlib import Path

import pytest

from config_fixtures import make_live_action_world, make_world
from engine.config import loader
from engine.core.errors import Refused
from engine.media.probe import VideoInfo
from engine.seedvr2 import chunking, plan as plan_mod, recipe as recipe_mod

V003 = "seedvr2/v003-7b-int8-tile768-int17-raw21"
FROZEN_SEGMENTS = (loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
                   / "technical" / "seedvr2-production-v004")


@pytest.fixture(scope="module")
def config():
    return loader.resolve_episode("04-milk-and-mom")


@pytest.fixture(scope="module")
def recipe(config):
    return config.recipes["seedvr2"]


@pytest.fixture(scope="module")
def pending(config):
    return plan_mod.build_plan(config, repo_root=loader.REPO_ROOT)


def _jjv():
    import importlib.util
    spec = importlib.util.spec_from_file_location("jjv_cli_m3", loader.SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- chunking ---------------------------------------------------------------------------
def test_chunk_ranges_for_120_frames(recipe) -> None:
    chunks = chunking.plan_chunks(120, recipe["geometry"])
    assert [(c["segment_start_frame"], c["segment_end_frame_exclusive"]) for c in chunks][:3] == [(0, 17), (9, 30), (22, 43)]
    assert [(c["core_start_frame"], c["core_frames"]) for c in chunks][-2:] == [(104, 13), (117, 3)]
    assert [c["seedvr2_padded_frames"] for c in chunks][-2:] == [21, 9]
    assert chunks[0]["overlap"]["with_previous"] is None and chunks[-1]["overlap"]["with_next"] is None
    assert chunks[1]["overlap"]["with_previous"] == {"frames": 8, "source_start_frame": 9, "source_end_frame_exclusive": 17}


def test_cores_tile_the_source_without_gap_or_overlap(recipe) -> None:
    for total in (1, 12, 13, 14, 40, 92, 128, 1656):
        chunks = chunking.plan_chunks(total, recipe["geometry"])
        assert chunks[0]["core_start_frame"] == 0 and chunks[-1]["core_end_frame_exclusive"] == total
        assert all(a["core_end_frame_exclusive"] == b["core_start_frame"] for a, b in zip(chunks, chunks[1:]))
        assert all(c["segment_frames"] <= recipe["geometry"]["max_raw_segment_frames"] for c in chunks)


def test_the_old_40_frame_cap_is_not_ported_the_recipe_envelope_governs(recipe) -> None:
    geometry = dict(recipe["geometry"], context_frames_each_side=10)  # 13 + 20 = 33 raw > 21
    with pytest.raises(Refused, match="exceeds 21 raw frames"):
        chunking.plan_chunks(120, geometry)
    small = dict(recipe["geometry"], max_raw_segment_frames=16)
    with pytest.raises(Refused, match="exceeds 16 raw frames"):
        chunking.plan_chunks(120, small)


@pytest.mark.parametrize("n,expected", [(1, 1), (7, 9), (17, 17), (20, 21), (21, 21), (3, 5)])
def test_padded_frame_count(n: int, expected: int) -> None:
    assert recipe_mod.padded_frame_count(n, 4) == expected
    with pytest.raises(Refused):
        recipe_mod.padded_frame_count(0, 4)


def test_chunk_plan_input_validation() -> None:
    for args in ((0, 13, 4), (10, 0, 4), (10, 13, -1)):
        with pytest.raises(Refused):
            chunking.build_chunk_plan(*args)


def test_seam_pairs_name_adjacent_chunks(pending) -> None:
    shot = pending.plan["shots"][0]
    pairs = shot["seam_pairs_to_inspect"]
    assert len(pairs) == shot["chunk_count"] - 1
    assert pairs[0]["left_chunk"] == "chunk-0000" and pairs[0]["right_core_first_source_frame"] == 13


# ---- plan v2 contract -------------------------------------------------------------------
def test_expected_raw_output_frames_equal_segment_frames_and_padded_is_informational(pending) -> None:
    chunks = [c for s in pending.plan["shots"] for c in s["chunks"]]
    assert len(chunks) == 134
    assert all(c["expected_raw_output_frames"] == c["segment_frames"] for c in chunks)
    assert all("expected_output_frame_count" not in c for c in chunks)
    assert sum(c["seedvr2_padded_frames"] != c["segment_frames"] for c in chunks) == 15
    assert pending.plan["schema"] == "jjv/seedvr2-plan/v2"


def test_without_segments_the_plan_is_pending_and_emits_no_graphs(pending) -> None:
    plan = pending.plan
    assert plan["status"] == "PLANNED_SEGMENTS_PENDING" and pending.graphs == {}
    assert plan["totals"]["segments_bound"] == 0 and plan["totals"]["total_api_graphs"] == 0
    chunk = plan["shots"][0]["chunks"][0]
    assert chunk["segment_sha256"] is None and chunk["comfy_input_name"] is None
    assert chunk["api_graph_canonical_sha256"] is None and chunk["pilot_diff"] is None
    assert chunk["gpu_submitted"] is False and chunk["comfy_post_called"] is False
    assert plan["execution"]["comfy_post_called"] is False and plan["registration_allowed"] is False


def test_plan_carries_totals_target_and_estimates(pending) -> None:
    plan = pending.plan
    assert plan["totals"]["total_sources"] == 14 and plan["totals"]["total_source_frames"] == 1656
    assert plan["target"]["crop_filter"] == "crop=3840:2160:24:0"
    assert plan["estimate"]["gpu_seconds_conservative"] == round(134 * 175.15, 2)
    assert plan["canonicalization"] == "ascii" and plan["domain"] == "jenniejoy_cartoon_3d"


def test_partial_segment_binding_emits_graphs_for_the_bound_chunks_only(tmp_path: Path, config) -> None:
    root = tmp_path / "segments"
    for name in ("chunk-0000", "chunk-0001"):
        target = root / "S01_A" / "chunks" / name
        target.mkdir(parents=True)
        shutil.copyfile(FROZEN_SEGMENTS / "S01_A" / "chunks" / name / "source-segment.mp4", target / "source-segment.mp4")
    result = plan_mod.build_plan(config, repo_root=loader.REPO_ROOT, segments_root=root)
    assert result.plan["status"] == "PLANNED_SEGMENTS_PENDING"
    assert result.plan["totals"]["segments_bound"] == 2 and len(result.graphs) == 2
    bound = [c for c in result.plan["shots"][0]["chunks"] if c["segment_sha256"]]
    assert [c["chunk_name"] for c in bound] == ["chunk-0000", "chunk-0001"]
    assert bound[0]["api_graph_canonical_sha256"] == "316bbba0316a256fd4268cef9d6065b00ddc7ce744d96151b1e93212b4f7d564"
    assert {tuple(sorted(d["path"] for d in c["pilot_diff"]["api_changed_keys"])) for c in bound} == {
        ("$.1.inputs.file", "$.15.inputs.filename_prefix")}


def test_segment_with_the_wrong_frame_count_is_refused(tmp_path: Path, config) -> None:
    root = tmp_path / "segments"
    target = root / "S01_A" / "chunks" / "chunk-0000"
    target.mkdir(parents=True)
    shutil.copyfile(FROZEN_SEGMENTS / "S01_A" / "chunks" / "chunk-0001" / "source-segment.mp4",
                    target / "source-segment.mp4")  # a 21-frame file where 17 are planned
    with pytest.raises(Refused, match="segment has 21 frames, plan needs 17"):
        plan_mod.build_plan(config, repo_root=loader.REPO_ROOT, segments_root=root)


# ---- refusals ---------------------------------------------------------------------------
def test_live_action_episode_is_refused_with_no_recipe(tmp_path: Path) -> None:
    world = make_live_action_world(tmp_path)
    live = loader.resolve_episode(str(world.episode_file), skill_root=world.skill_root,
                                  machine_path=world.machine_path)
    with pytest.raises(Refused, match="no qualified seedvr2 recipe"):
        plan_mod.build_plan(live, repo_root=loader.REPO_ROOT)


def test_cli_plan_refuses_a_live_action_episode_with_exit_one(tmp_path: Path, capsys) -> None:
    world = make_live_action_world(tmp_path)
    code = _jjv().main(["seedvr2", "plan", "--episode", str(world.episode_file), "--out", str(tmp_path / "out")])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["ok"] is False and "no qualified seedvr2 recipe" in out["error"]
    assert not (tmp_path / "out").exists()


def test_cli_plan_refuses_a_config_violation_before_planning(tmp_path: Path, capsys) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update({"domain.forbid_partner_nodes": False}))
    code = _jjv().main(["seedvr2", "plan", "--episode", str(world.episode_file), "--out", str(tmp_path / "out")])
    assert code == 1 and json.loads(capsys.readouterr().out)["ok"] is False


def test_episode_without_naming_templates_is_refused(tmp_path: Path, config) -> None:
    bare = copy.deepcopy(config.episode)
    bare.pop("seedvr2")
    mutated = loader.ResolvedConfig(**{**config.__dict__, "episode": bare})
    with pytest.raises(Refused, match="no seedvr2 block"):
        plan_mod.build_plan(mutated, repo_root=loader.REPO_ROOT)


@pytest.mark.parametrize("key,value,text", [
    ("input_name_template", "x-{shot}-{seg_sha12}.mp4", "must use {chunk}"),
    ("input_name_template", "x-{shot}-{chunk}.mp4", "must use {seg_sha12}"),
    ("input_name_template", "x-{shot}-{chunk}-{seg_sha12}-{nope}.mp4", "not a valid template"),
    ("input_name_template", "../x-{shot}-{chunk}-{seg_sha12}.mp4", "plain file name"),
    ("output_prefix_template", "{shot}", "must use {chunk}"),
    ("output_prefix_template", "../out/{shot}/{chunk}", "relative forward-slash path"),
    ("output_prefix_template", "C:/out/{shot}/{chunk}", "relative forward-slash path"),
    ("output_prefix_template", "/abs/{shot}/{chunk}", "relative forward-slash path"),
])
def test_unsafe_naming_templates_are_refused(config, key: str, value: str, text: str) -> None:
    block = dict(config.episode["seedvr2"], **{key: value})
    with pytest.raises(Refused, match=text.replace("{", r"\{").replace("}", r"\}")):
        plan_mod.check_templates(block)


def test_missing_source_and_wrong_frames_are_refused(tmp_path: Path, config) -> None:
    world = make_world(tmp_path)  # episode root is a copy without media
    moved = loader.resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    with pytest.raises(Refused, match="source clip not found"):
        plan_mod.build_plan(moved, repo_root=loader.REPO_ROOT)

    def lying_probe(path, *, count_packets=False):
        return VideoInfo(frames=99, width=864, height=480, fps=Fraction(24))
    with pytest.raises(Refused, match="source has 99 frames, config says 120"):
        plan_mod.build_plan(config, repo_root=loader.REPO_ROOT, probe=lying_probe)


@pytest.mark.parametrize("info,text", [
    (VideoInfo(frames=120, width=864, height=480, fps=Fraction(30)), "source fps"),
    (VideoInfo(frames=120, width=800, height=480, fps=Fraction(24)), "aspect"),
])
def test_wrong_fps_or_aspect_is_refused(config, info, text) -> None:
    with pytest.raises(Refused, match=text):
        plan_mod.build_plan(config, repo_root=loader.REPO_ROOT, probe=lambda p, count_packets=False: info)


def test_probe_without_nb_frames_falls_back_to_packet_count(config) -> None:
    seen = []

    def probe(path, *, count_packets=False):
        seen.append(count_packets)
        frames = None if not count_packets else 120
        return VideoInfo(frames=frames, width=864, height=480, fps=Fraction(24))
    with pytest.raises(Refused, match="source has 120 frames, config says 128"):
        plan_mod.build_plan(config, repo_root=loader.REPO_ROOT, probe=probe)  # S01_A passes, S02_A (128) fails
    assert seen[:2] == [False, True]


# ---- graph cloning ----------------------------------------------------------------------
def test_clone_changes_only_the_two_allowed_ports(recipe) -> None:
    pilot = recipe_mod.load_pilot_graph(recipe, loader.REPO_ROOT)
    graph, changes = recipe_mod.clone_api_graph(pilot, recipe, input_name="a.mp4", output_prefix="p/q")
    assert {c["path"] for c in changes} == {"$.1.inputs.file", "$.15.inputs.filename_prefix"}
    assert graph["1"]["inputs"]["file"] == "a.mp4" and pilot["1"]["inputs"]["file"] != "a.mp4"


def test_clone_refuses_a_port_not_on_the_allow_list(recipe) -> None:
    pilot = recipe_mod.load_pilot_graph(recipe, loader.REPO_ROOT)
    narrow = dict(recipe, allowed_api_diff_paths=["$.1.inputs.file"])
    with pytest.raises(Refused, match="allowed_api_diff_paths must be exactly"):
        recipe_mod.clone_api_graph(pilot, narrow, input_name="a.mp4", output_prefix="p/q")


def test_clone_refuses_when_the_graph_no_longer_matches_the_recipe(recipe) -> None:
    pilot = recipe_mod.load_pilot_graph(recipe, loader.REPO_ROOT)
    drifted = copy.deepcopy(pilot)
    drifted["10"]["inputs"]["denoise"] = 0.5
    with pytest.raises(Refused, match="differs from the qualified recipe"):
        recipe_mod.clone_api_graph(drifted, recipe, input_name="a.mp4", output_prefix="p/q")


def test_pilot_graph_with_a_wrong_pin_is_refused(recipe) -> None:
    bad = copy.deepcopy(recipe)
    bad["pilot"]["graph_file_sha256"] = "1" * 64
    with pytest.raises(Refused, match="pilot graph sha256"):
        recipe_mod.load_pilot_graph(bad, loader.REPO_ROOT)
    with pytest.raises(Refused, match="not found"):
        recipe_mod.load_pilot_graph(recipe, Path("nowhere"))


# ---- output guard and no-overwrite ------------------------------------------------------
def test_out_inside_protected_trees_is_refused(tmp_path: Path, config) -> None:
    root = Path(config.episode_root)
    for bad in (root / "technical" / "x", root, Path(config.machine["comfy"]["root"]) / "input" / "x"):
        with pytest.raises(Refused, match="protected tree"):
            plan_mod.refuse_output_inside(bad, [root, Path(config.machine["comfy"]["root"])])
    with pytest.raises(Refused):
        plan_mod.refuse_output_inside(FROZEN_SEGMENTS / "new", [FROZEN_SEGMENTS])
    assert plan_mod.refuse_output_inside(tmp_path / "ok", [root, None]) == (tmp_path / "ok").resolve()


def test_cli_refuses_out_inside_the_episode_tree(capsys, config) -> None:
    out = Path(config.episode_root) / "technical" / "never-written"
    code = _jjv().main(["seedvr2", "plan", "--episode", "04-milk-and-mom", "--out", str(out)])
    assert code == 1 and "protected tree" in json.loads(capsys.readouterr().out)["error"]
    assert not out.exists()


def test_write_plan_is_idempotent_and_never_overwrites(tmp_path: Path, pending) -> None:
    first = plan_mod.write_plan(tmp_path / "out", pending)
    assert plan_mod.write_plan(tmp_path / "out", pending)["plan_sha256"] == first["plan_sha256"]
    changed = plan_mod.PlanResult({**pending.plan, "status": "TAMPERED"}, pending.graphs)
    with pytest.raises(Refused, match="refusing to overwrite"):
        plan_mod.write_plan(tmp_path / "out", changed)


def test_cli_plan_writes_a_pending_plan_to_scratch(tmp_path: Path, capsys) -> None:
    code = _jjv().main(["seedvr2", "plan", "--episode", "04-milk-and-mom", "--out", str(tmp_path / "plan")])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "PLANNED_SEGMENTS_PENDING" and out["totals"]["total_chunks"] == 134
    written = json.loads((tmp_path / "plan" / "seedvr2-plan-v2.json").read_text("utf-8"))
    assert written["schema"] == "jjv/seedvr2-plan/v2" and written["config_sha256"] == out["config_sha256"]


# ---- hygiene ----------------------------------------------------------------------------
def test_seedvr2_modules_stay_under_400_lines() -> None:
    for source in (loader.SKILL_ROOT / "engine" / "seedvr2").glob("*.py"):
        assert len(source.read_text("utf-8").splitlines()) < 400, source
