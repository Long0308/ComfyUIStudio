"""VENG-1 / A2: hai domain không bao giờ trộn — routes thật chỉ cho live-action, template/recipe tách theo domain,
backend SeedVR2 của hoạt hình không bao giờ được domain khác dùng, code engine/video không nêu tên domain."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from video_fixtures import CARTOON, LIVE, VideoWorld, shotlist_document, write_routes

from engine.core.errors import Refused
from engine.layout.context import REPO_ROOT, SKILL_ROOT
from engine.video import routes as routes_mod
from engine.video import upscale as upscale_mod

REAL_ROUTES = SKILL_ROOT / "recipes" / "video" / "routes-v001.json"
CARTOON_SEEDVR2_RECIPE = "seedvr2/v003-7b-int8-tile768-int17-raw21"
LIVE_TEMPLATE_SHA = "809fa9daa553e61df6e755786346b889e95f59b673c22f5cd8c23927dae58982"
CARTOON_TEMPLATE_SHA = "9d23360765c9891866570d6cb4d574e9f8e3d2ec8855adb5b04209a2b6de8036"


def test_real_routes_allow_both_domains_and_pin_each_own_template() -> None:
    routes = routes_mod.load_routes(REAL_ROUTES)
    assert routes["allowed_domains"] == [LIVE, CARTOON] and set(routes["domains"]) == {LIVE, CARTOON}
    row = routes["domains"][LIVE]
    assert row["template"]["sha256"] == LIVE_TEMPLATE_SHA
    assert "NEWTECONS_H3" in row["template"]["path"] and row["template"]["path"].endswith("v008-c2turbo.api.json")
    assert "04-milk-and-mom" not in row["template"]["path"]
    assert row["upscale"]["default_backend"] == "none" and row["upscale"]["qualified"] == {}
    cartoon = routes["domains"][CARTOON]
    assert cartoon["template"]["sha256"] == CARTOON_TEMPLATE_SHA
    assert cartoon["template"]["path"].endswith("S01_A_HYBRID_A.api.json")
    assert "04-milk-and-mom" in cartoon["template"]["path"] and "hybrid-v001" in cartoon["template"]["path"]
    assert cartoon["frame_grid"]["step"] == 17 and cartoon["frame_grid"]["offset"] == 5
    assert cartoon["geometry"]["width"] == 864 and cartoon["geometry"]["height"] == 480
    assert cartoon["upscale"]["qualified"]["seedvr2-7b"]["recipe_id"] == CARTOON_SEEDVR2_RECIPE
    h3 = json.loads((SKILL_ROOT / "recipes" / "h3" / "routes-v001.json").read_text("utf-8"))
    assert LIVE in h3["qualification_required"] and LIVE not in h3["allowed_domains"]  # pilot H3 vẫn là cổng


def test_cartoon_episode_is_accepted_by_the_real_video_routes(tmp_path) -> None:
    world = VideoWorld(tmp_path, domain=CARTOON)
    world.routes = REAL_ROUTES
    code, result = world.plan()
    assert code == 0 and result["template_sha256"] == CARTOON_TEMPLATE_SHA
    assert (world.out / "plan.json").is_file()


def test_shotlist_of_the_other_domain_is_refused(tmp_path) -> None:
    world = VideoWorld(tmp_path, domain=LIVE)
    world.shotlist.write_text(json.dumps(shotlist_document(CARTOON, {"alice": world.h3.face})), encoding="utf-8")
    code, result = world.plan()
    assert code == 1 and "VIDEO_DOMAIN_REFUSED" in result["error"] and "never mixed" in result["error"]
    assert not world.out.exists()


def test_two_domains_resolve_their_own_template_and_live_never_sees_the_cartoon_recipe(tmp_path) -> None:
    live = VideoWorld(tmp_path / "live", domain=LIVE)
    toon = VideoWorld(tmp_path / "toon", domain=CARTOON)
    other_template = tmp_path / "toon-template.api.json"
    other_template.write_text(toon.h3.template.read_text("utf-8").replace("template prompt", "cartoon prompt"), "utf-8")
    routes = write_routes(tmp_path / "routes.json", {LIVE: live.h3.template, CARTOON: other_template},
                          qualified={CARTOON: {"seedvr2-7b": {"path": str(other_template),
                                                              "sha256": routes_mod.sha256_file(other_template)}}})
    live.routes = toon.routes = routes
    assert live.plan()[0] == 0 and toon.plan()[0] == 0
    live_plan = json.loads((live.out / "plan.json").read_text("utf-8"))
    toon_plan = json.loads((toon.out / "plan.json").read_text("utf-8"))
    assert live_plan["template"]["sha256"] != toon_plan["template"]["sha256"]
    assert live_plan["domain"] == LIVE and toon_plan["domain"] == CARTOON
    # backend qualified cho hoạt hình KHÔNG lan sang live-action
    loaded = routes_mod.load_routes(routes)
    live_route = routes_mod.domain_route(live.ctx(), loaded)
    toon_route = routes_mod.domain_route(toon.ctx(), loaded)
    assert isinstance(upscale_mod.select_backend(live.ctx(), live_route, "seedvr2-7b"), upscale_mod.UnqualifiedBackend)
    with pytest.raises(Refused, match="UPSCALE_NOT_IMPLEMENTED"):  # hoạt hình: qualified nhưng chưa có adapter
        upscale_mod.select_backend(toon.ctx(), toon_route, "seedvr2-7b")
    with pytest.raises(Refused, match="UPSCALE_UNQUALIFIED"):
        upscale_mod.UnqualifiedBackend("seedvr2-7b").run(live.ctx())
    live.run("--lanes", "2")
    written = [p for p in live.out.rglob("*") if p.is_file()]
    for path in written:
        text = path.read_text("utf-8", errors="replace")
        assert CARTOON_SEEDVR2_RECIPE not in text and "cartoon prompt" not in text and CARTOON not in text, path
    assert "template prompt" in live.prompt_text()


def test_engine_video_source_names_no_domain_film_or_machine_path() -> None:
    folder = SKILL_ROOT / "engine" / "video"
    banned = re.compile(r"newtecons|jenniejoy|milk-and-mom|[A-Za-z]:\\\\", re.IGNORECASE)
    for path in sorted(folder.glob("*.py")):
        hits = [line for line in path.read_text("utf-8").splitlines() if banned.search(line)]
        assert not hits, (path.name, hits)


def test_real_template_exists_and_matches_the_pin() -> None:
    routes = routes_mod.load_routes(REAL_ROUTES)
    template = Path(REPO_ROOT / routes["domains"][LIVE]["template"]["path"])
    if not template.is_file():
        pytest.skip("production template graph not present on this machine")
    resolved = routes_mod.template_for(routes["domains"][LIVE])
    assert resolved["sha256"] == routes["domains"][LIVE]["template"]["sha256"]
    graph = json.loads(template.read_text("utf-8"))
    ports = routes["domains"][LIVE]["ports"]
    for node, key in [*ports["face"], *ports["anchor"], *ports["wav"], *ports["output_ports"]]:
        assert key in graph[node]["inputs"], (node, key)
    for dotted in (ports["prompt"], ports["length"], ports["seed"]):
        node, key = dotted.split(".")
        assert key in graph[node]["inputs"], dotted
    assert graph[ports["editorial_node"]]["class_type"] == "SaveVideo"
    assert graph["6"]["inputs"]["length"] == 124 and routes_mod.frame_length(5.167, 24, routes["domains"][LIVE]["frame_grid"])["frames"] == 124
