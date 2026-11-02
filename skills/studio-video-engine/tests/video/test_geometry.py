"""Geometry H3 (width/height) khai trong ``routes-v001.json``: plan ghi vào receipt, dry-run dựng graph đúng cỡ,
render từ chối h3-inputs lệch cỡ. Tier preview freezes 864x480 over legacy geometry numbers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from video_fixtures import VideoWorld, run_video, write_routes  # noqa: E402
from tier_workspace import workspace  # noqa: F401, E402

from engine.core.errors import Refused  # noqa: E402
from engine.video import render as render_mod  # noqa: E402
from engine.video import routes as routes_mod  # noqa: E402

PORTS = {"width_port": "6.width", "height_port": "6.height", "fps_port": "17.fps"}


def _world(tmp_path: Path, geometry: dict | None) -> VideoWorld:
    """Template fixture có thêm 6.width/6.height (864x480) để graph có ô mà geometry ghi đè."""
    world = VideoWorld(tmp_path)
    graph = json.loads(world.h3.template.read_text("utf-8"))
    graph["6"]["inputs"].update(width=864, height=480)
    world.h3.template.write_text(json.dumps(graph), encoding="utf-8")
    write_routes(world.routes, {world.domain: world.h3.template})
    routes = json.loads(world.routes.read_text("utf-8"))
    if geometry is not None:
        routes["domains"][world.domain]["geometry"] = geometry
    world.routes.write_text(json.dumps(routes), encoding="utf-8")
    return world


def _dry(world: VideoWorld) -> dict:
    code, planned = world.plan()
    assert code == 0, planned
    code, result = world.run("--completion", "--dry-run")
    assert code == 0, result
    return result["payloads"][0]


def test_preview_tier_reaches_graph_using_route_ports(workspace) -> None:
    payload = _dry(_world(workspace, {**PORTS, "width": 1280, "height": 704}))
    assert payload["geometry"] == {"width": 864, "height": 480, "fps": 24}


def test_preview_tier_overrides_legacy_geometry_numbers(workspace) -> None:
    payload = _dry(_world(workspace, {**PORTS, "width": 960, "height": 544}))
    assert (payload["geometry"]["width"], payload["geometry"]["height"]) == (864, 480)


def test_plan_receipt_freezes_the_geometry(workspace) -> None:
    world = _world(workspace, {**PORTS, "width": 1280, "height": 704})
    assert world.plan()[0] == 0
    receipt = json.loads((world.out / "S01" / "plan-receipt.json").read_text("utf-8")) if (world.out / "S01").is_dir() \
        else json.loads(next(world.out.glob("*/plan-receipt.json")).read_text("utf-8"))
    assert receipt["geometry"] == {"width": 864, "height": 480, "ports": {"width": "6.width", "height": "6.height"}}


def test_704_is_a_multiple_of_32_and_a_bad_height_is_refused() -> None:
    assert 704 % 32 == 0
    ok = {"width_port": "6.width", "height_port": "6.height", "width": 1280, "height": 704}
    assert routes_mod.geometry_for({"geometry": ok}) == {"width": 1280, "height": 704,
                                                          "ports": {"width": "6.width", "height": "6.height"}}
    with pytest.raises(Refused, match="multiple of 32"):
        routes_mod.geometry_for({"geometry": {**ok, "height": 700}})


def test_domain_without_geometry_numbers_gets_preview_size(workspace) -> None:
    payload = _dry(_world(workspace, dict(PORTS)))
    assert payload["geometry"] == {"width": 864, "height": 480, "fps": 24}
    assert routes_mod.geometry_for({}) is None and routes_mod.geometry_for({"geometry": dict(PORTS)}) is None


def test_render_refuses_h3_inputs_whose_size_drifts_from_the_plan(workspace) -> None:
    world = _world(workspace, {**PORTS, "width": 1280, "height": 704})
    assert world.plan()[0] == 0
    assert run_video(world.base("prompt"))[0] == 0
    receipt = json.loads(next(world.out.glob("*/plan-receipt.json")).read_text("utf-8"))
    shot = receipt["shot"]
    text = world.prompt_text(shot, world.state(shot)["revision"])
    world.write_h3_inputs(shot, **{"6.width": 1280, "6.height": 704})
    with pytest.raises(Refused, match="GEOMETRY_DRIFT"):
        render_mod.require_manifest(world.ctx(), world.out, receipt, text)
    world.write_h3_inputs(shot, **{"6.width": 864, "6.height": 480})
    render_mod.require_manifest(world.ctx(), world.out, receipt, text)
