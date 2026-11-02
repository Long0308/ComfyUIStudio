"""LUT: generator (tools/make_lut.py) + parser (engine/post/grade/lut.py). Stdlib + the engine's own parser only."""
from __future__ import annotations

import importlib.util
import json
import math

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.post.grade.lut import parse_cube

GRADE_DIR = SKILL_ROOT / "recipes" / "grade"
TOOL = SKILL_ROOT / "tools" / "make_lut.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("make_lut_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mk = load_tool()


def identity_look() -> dict:
    return {"schema": "jjv/grade-look/v1", "name": "identity_test", "domain_id": "test_domain",
            "lift": [0, 0, 0], "gamma": [1, 1, 1], "gain": [1, 1, 1], "warmth": 0.0, "saturation": 1.0,
            "contrast": 1.0, "split": {"shadow_cool": 0.0, "highlight_warm": 0.0},
            "brand": [], "brand_de_max": 3.0}


def test_cube_round_trip_size_and_order(tmp_path):
    look = identity_look()
    table = mk.build_table(look, 33)
    assert len(table) == 33 ** 3
    cube = tmp_path / "id.cube"
    mk.write_cube(cube, table, 33, "identity_test")
    parsed = parse_cube(cube)
    assert parsed.size == 33
    assert len(parsed.table) == 33 ** 3
    # R varies fastest: entry 1 is (1/32, 0, 0)
    assert parsed.table[1] == pytest.approx((1 / 32, 0.0, 0.0), abs=1e-6)
    assert parsed.table[33] == pytest.approx((0.0, 1 / 32, 0.0), abs=1e-6)
    assert parsed.table[-1] == pytest.approx((1.0, 1.0, 1.0), abs=1e-6)


def test_identity_table_is_identity(tmp_path):
    table = mk.build_table(identity_look(), 9)
    for idx, (r, g, b) in enumerate(table):
        assert (r, g, b) == pytest.approx((
            (idx % 9) / 8, ((idx // 9) % 9) / 8, (idx // 81) / 8), abs=1e-9)


def test_parser_refuses_bad_cubes(tmp_path):
    bad_count = tmp_path / "bad_count.cube"
    bad_count.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n", encoding="utf-8")
    with pytest.raises(Refused):
        parse_cube(bad_count)
    no_size = tmp_path / "no_size.cube"
    no_size.write_text("0 0 0\n", encoding="utf-8")
    with pytest.raises(Refused):
        parse_cube(no_size)
    out_of_range = tmp_path / "range.cube"
    out_of_range.write_text("LUT_3D_SIZE 2\n" + "1.5 0 0\n" * 8, encoding="utf-8")
    with pytest.raises(Refused):
        parse_cube(out_of_range)


def test_look_validation_refuses_out_of_range_params():
    bad = identity_look()
    bad["saturation"] = 3.0
    with pytest.raises(ValueError):
        mk.validate_look(bad)
    bad = identity_look()
    bad["gain"] = [1.2, 1, 1]
    with pytest.raises(ValueError):
        mk.validate_look(bad)
    bad = identity_look()
    bad["name"] = "../escape"
    with pytest.raises(ValueError):
        mk.validate_look(bad)


def test_shipped_params_match_shipped_cubes_and_spec():
    soft = json.loads((GRADE_DIR / "jenniejoy_soft_v001.json").read_text(encoding="utf-8"))
    # Spec section (b): lift +0.02, gamma ~1.03, gain 0.92, saturation ~0.95, warmth +2..4 %, contrast 0.95..1.0
    assert soft["lift"][0] == pytest.approx(0.02)
    assert 1.00 <= soft["gamma"][0] <= 1.05
    assert soft["gain"][0] == pytest.approx(0.92)
    assert 0.92 <= soft["saturation"] <= 1.0 and abs(soft["saturation"] - 0.95) <= 0.01
    assert 0.02 <= soft["warmth"] <= 0.04
    assert 0.95 <= soft["contrast"] <= 1.0
    assert soft["post_defaults"] == {"grain": 0, "halation": 0, "soften": 0}
    film = json.loads((GRADE_DIR / "newtecons_film_v001.json").read_text(encoding="utf-8"))
    assert film["brand_de_max"] == 3.0
    names = {b["name"]: b["hex"] for b in film["brand"]}
    assert names == {"brand_blue": "#0B4FD9", "brand_red": "#E4302C"}


@pytest.mark.parametrize("name", ["newtecons_film_v001", "jenniejoy_soft_v001"])
def test_shipped_cube_is_what_the_generator_writes(name, tmp_path):
    look = mk.load_look(GRADE_DIR / f"{name}.json")
    fresh = tmp_path / f"{name}.cube"
    mk.write_cube(fresh, mk.build_table(look, 33), 33, name)
    assert fresh.read_bytes() == (GRADE_DIR / f"{name}.cube").read_bytes()
    assert parse_cube(GRADE_DIR / f"{name}.cube").size == 33


def test_brand_de_newtecons_film_within_3():
    look = mk.load_look(GRADE_DIR / "newtecons_film_v001.json")
    result = mk.brand_de(look, 33)
    for name, de in result.items():
        assert de <= 3.0, (name, de)


def test_brand_de_jenniejoy_reports_a_number():
    # Stage D (.jj-brand-locref-stage) removed the NEWTECONS brand colours from the JennieJoy grade recipe on purpose:
    # the domain-isolation rule keeps NEWTECONS and JennieJoy tokens apart, LUT and recipe included. So no brand token
    # remains for jenniejoy_soft_v001; the numeric report check stays for any token that does exist.
    look = mk.load_look(GRADE_DIR / "jenniejoy_soft_v001.json")
    result = mk.brand_de(look, 33)
    assert set(result) == set()
    assert all(math.isfinite(v) and v >= 0 for v in result.values())


def test_de2000_known_pair():
    # Sharma et al. 2005 test pair 1: Lab(50, 2.6772, -79.7751) vs Lab(50, 0, -82.7485) -> dE2000 = 2.0425
    assert mk.cie_de2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)) == pytest.approx(2.0425, abs=1e-3)


def test_brand_de_detects_a_real_shift():
    look = identity_look()
    look["brand"] = [{"name": "brand_blue", "hex": "#0B4FD9"}]
    look["brand_de_max"] = 3.0
    assert mk.brand_de(look, 33)["brand_blue"] == pytest.approx(0.0, abs=1e-6)
    shifted = dict(look, gain=[0.6, 0.6, 0.6])
    assert mk.brand_de(shifted, 33)["brand_blue"] > 3.0
