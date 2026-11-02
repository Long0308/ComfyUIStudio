"""UAT-R1 fix 1: ``jjv video plan`` ghi take_mode vào plan receipt; ``video render`` dùng ``guard_route`` (không còn so bằng)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from video_fixtures import LIVE, SHOT, TOKEN, VideoWorld, run_video, shot_row  # noqa: E402

from engine.video import routes as routes_mod  # noqa: E402


def _world(tmp_path: Path, duration: float, **extra) -> VideoWorld:
    row = {**shot_row(duration=duration), **extra}
    world = VideoWorld(tmp_path, domain=LIVE, shots=[row])
    real = routes_mod.load_routes(routes_mod.ROUTES)["domains"][LIVE]["long_take"]
    document = json.loads(world.routes.read_text("utf-8"))
    document["domains"][LIVE]["long_take"] = {k: v for k, v in real.items()}
    world.routes.write_text(json.dumps(document), encoding="utf-8")
    return world


def _receipt(world: VideoWorld) -> dict:
    return json.loads((world.out / SHOT / "plan-receipt.json").read_text("utf-8"))


def test_plan_20s_is_routed_to_longtake_and_receipt_records_why(tmp_path) -> None:
    world = _world(tmp_path, 20)
    assert world.plan()[0] == 0
    receipt = _receipt(world)
    assert receipt["take_mode"] == "long" and receipt["take_route"] == "h3-longtake" and receipt["h3_route"] == "h3-longtake"
    assert "20" in receipt["take_reason"]


def test_plan_5s_stays_on_short_route(tmp_path) -> None:
    world = _world(tmp_path, 5)
    assert world.plan()[0] == 0
    receipt = _receipt(world)
    assert (receipt["take_mode"], receipt["take_route"], receipt["h3_route"]) == ("short", "h3-ref2va", "h3-ref2va")
    assert "auto" in receipt["take_reason"]


def test_plan_explicit_short_at_20s_is_refused_and_writes_nothing(tmp_path) -> None:
    world = _world(tmp_path, 20, take_mode="short")
    code, result = world.plan()
    assert code != 0 and "TAKE_SHORT_ROUTE_REFUSED" in result["error"]
    assert not (world.out / "plan.json").exists()


def test_render_of_a_long_shot_on_the_short_route_is_refused_with_its_code(tmp_path) -> None:
    world = _world(tmp_path, 20)
    assert world.plan()[0] == 0
    code, result = run_video(world.base("render", "--shot", SHOT, "--revision", "1", "--route", "h3-ref2va",
                                        "--gpu-approved", TOKEN))
    assert code == 1 and "LONG_TAKE_ON_SHORT_ROUTE" in result["error"] and "nothing was sent" in result["error"]
