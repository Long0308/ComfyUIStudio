"""BP-42 long-take (CPU, không GPU, không mạng): số window, chia prompt, chọn take_mode, route chỉ NEWTECONS, template + graph.

Bảng số window là BẢNG THAM KHẢO (bài đăng bên thứ ba), test chỉ khoá hành vi của bảng, không chứng minh H3 cần đúng số đó.
"""

from __future__ import annotations

import json

import pytest

from engine.core.errors import Refused
from engine.video import longtake as lt
from engine.video import prompt as prompt_mod
from engine.video import routes as routes_mod

ROUTES = routes_mod.ROUTES
LIVE = "newtecons_live_action"
RULE = "Wardrobe (cong_truong, outdoors on site): full PPE over the company shirt; helmet worn."


def _row() -> dict:
    return routes_mod.load_routes(ROUTES)["domains"][LIVE]


def test_window_count_reference_table() -> None:
    assert [lt.window_count(t) for t in (20, 25, 30, 40, 50, 60)] == [6, 7, 8, 11, 14, 17]
    assert lt.window_count(20.0) == 6 and lt.window_count(16) >= 1


def test_window_count_over_template_capacity_is_refused_not_cut() -> None:
    with pytest.raises(Refused, match="LONG_TAKE_TOO_MANY_WINDOWS"):
        lt.window_count(40, max_windows=8)
    assert lt.window_count(30, max_windows=8) == 8


def test_prompt_split_keeps_wardrobe_and_props_in_every_window() -> None:
    receipt = {"shot": "S1", "scene_id": "SC", "duration_s": 20, "continuity": {"camera_id": "c", "setting_id": "s"},
               "refs": [], "props": ["white helmet (prop, not worn)"], "speech": "none",
               "wardrobe": {"context": "cong_truong", "rules": {"cong_truong": {"rule": RULE, "forbid": []}}},
               "prompt_as_code": {"subject": "walk", "style": "real", "composition": "tracking", "lighting": "sun",
                                  "material": "dust", "negative": "cartoon"}}
    global_block = prompt_mod.compose("TEMPLATE", receipt)
    beats = [f"beat {k}" for k in range(6)]
    parts = lt.split_prompt(global_block, beats, 20)
    assert len(parts["windows"]) == 6
    for k, text in enumerate(parts["windows"]):
        assert RULE in text and "Props: white helmet" in text and "Negative: cartoon" in text
        assert text.startswith(global_block.rstrip("\n")) and f"beat {k}" in text and f"Window {k + 1} of 6" in text


def test_window_beats_rules() -> None:
    assert lt.window_beats({"windows": ["a", {"beat": "b"}]}, 2) == ["a", "b"]
    assert lt.window_beats({"beats": ["a", "b"]}, 4) == ["a", "a", "b", "b"]
    with pytest.raises(Refused, match="LONG_TAKE_WINDOWS_MISMATCH"):
        lt.window_beats({"windows": ["a"]}, 2)
    with pytest.raises(Refused, match="LONG_TAKE_NO_BEATS"):
        lt.window_beats({"id": "x"}, 2)
    with pytest.raises(Refused, match="LONG_TAKE_BEATS_MISMATCH"):
        lt.window_beats({"beats": ["a", "b", "c"]}, 2)


def test_take_mode_auto_and_explicit() -> None:
    row = _row()
    short = lt.decide_take_mode(LIVE, row, {"id": "s", "duration_s": 5})
    assert (short["take_mode"], short["route"]) == ("short", "h3-ref2va") and "auto" in short["reason"]
    long_ = lt.decide_take_mode(LIVE, row, {"id": "s", "duration_s": 20}, "auto")
    assert (long_["take_mode"], long_["route"]) == ("long", "h3-longtake") and "20" in long_["reason"]
    assert lt.decide_take_mode(LIVE, row, {"id": "s", "duration_s": 5, "long_take": True})["take_mode"] == "long"
    assert lt.decide_take_mode(LIVE, row, {"id": "s", "duration_s": 15})["take_mode"] == "short"  # ngưỡng là "over 15"
    assert lt.decide_take_mode(LIVE, row, {"id": "s", "duration_s": 5}, "long")["route"] == "h3-longtake"
    with pytest.raises(Refused, match="TAKE_MODE_INVALID"):
        lt.decide_take_mode(LIVE, row, {"duration_s": 5}, "medium")


def test_explicit_short_on_a_long_shot_is_refused_never_cut() -> None:
    with pytest.raises(Refused, match="TAKE_SHORT_ROUTE_REFUSED.*would cut it short"):
        lt.decide_take_mode(LIVE, _row(), {"id": "s", "duration_s": 20}, "short")
    with pytest.raises(Refused, match="TAKE_SHORT_ROUTE_REFUSED"):
        lt.decide_take_mode(LIVE, _row(), {"id": "s", "duration_s": 5, "long_take": True}, "short")
    decision = lt.decide_take_mode(LIVE, _row(), {"id": "s", "duration_s": 20})
    with pytest.raises(Refused, match="LONG_TAKE_ON_SHORT_ROUTE"):
        lt.guard_route(decision, "h3-ref2va")
    lt.guard_route(decision, "h3-longtake")


def test_long_take_refuses_non_newtecons_domain() -> None:
    row = _row()
    with pytest.raises(Refused, match="LONG_TAKE_DOMAIN_REFUSED"):
        lt.decide_take_mode("jenniejoy_cartoon_3d", row, {"id": "s", "duration_s": 5}, "long")
    with pytest.raises(Refused, match="LONG_TAKE_DOMAIN_REFUSED"):
        lt.decide_take_mode("jenniejoy_cartoon_3d", row, {"id": "s", "duration_s": 20})  # auto -> long -> refused
    bare = {k: v for k, v in row.items() if k != "long_take"}
    with pytest.raises(Refused, match="LONG_TAKE_DOMAIN_REFUSED"):
        lt.long_template("jenniejoy_cartoon_3d", bare)
    assert lt.decide_take_mode("jenniejoy_cartoon_3d", bare, {"id": "s", "duration_s": 5})["take_mode"] == "short"


def test_routes_pin_matches_template_and_cartoon_has_no_long_take() -> None:
    row = _row()
    info = lt.long_template(LIVE, row)  # sha thật của file template
    assert info["sha256"] == row["long_take"]["template"]["sha256"]
    raw = json.loads(ROUTES.read_text("utf-8"))
    assert list(raw["domains"]) == [LIVE, "jenniejoy_cartoon_3d"]
    assert raw["allowed_domains"] == [LIVE, "jenniejoy_cartoon_3d"]
    assert "long_take" not in raw["domains"]["jenniejoy_cartoon_3d"]


@pytest.mark.parametrize("n", [1, 2, 6, 8])
def test_build_graph_prunes_unused_windows(n: int) -> None:
    row = _row()
    block = row["long_take"]
    template = json.loads(open(lt.long_template(LIVE, row)["path"], encoding="utf-8").read())
    before = json.dumps(template, sort_keys=True)
    graph = lt.build_graph(template, block, [f"p{k}" for k in range(n)], width=864, height=480, length=481)
    assert json.dumps(template, sort_keys=True) == before  # template không bị sửa
    nodes = block["windows"]
    assert [k for k in nodes["r2v_nodes"] if k in graph] == nodes["r2v_nodes"][:n]
    assert [k for k in nodes["combine_nodes"] if k in graph] == nodes["combine_nodes"][:max(0, n - 1)]
    last = nodes["r2v_nodes"][0] if n == 1 else nodes["combine_nodes"][n - 2]
    assert graph["9"]["inputs"]["positive"] == [last, 0]
    assert graph["22"]["class_type"] == "ContextWindowsManual" and graph["10"]["inputs"]["model"] == ["22", 0]
    for k in range(n):
        assert graph[nodes["prompt_nodes"][k]]["inputs"]["value"] == f"p{k}"
        assert graph[nodes["r2v_nodes"][k]]["inputs"]["width"] == 864
    # mọi liên kết còn trỏ tới node tồn tại
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in graph


def test_window_log_rows() -> None:
    rows = lt.window_log(20, 481, ["a", "b"])
    assert [r["window"] for r in rows] == [0, 1] and rows[0]["frame_start"] == 0 and rows[1]["frame_end"] == 480
    assert len(rows[0]["prompt_sha256"]) == 64
