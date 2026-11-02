"""Graph adapter ``comfy-realesrgan-1080`` phải khớp ``/object_info`` thật (snapshot đọc-chỉ 2026-10-31)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from engine.video.upscale_comfy import SAVE_NODE, build_graph

SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "object_info_upscale.json").read_text("utf-8"))
DYNAMIC = "COMFY_DYNAMICCOMBO_V3"
SECTIONS = ("required", "optional")


def _entry(raw: list) -> tuple[Any, dict]:
    """Tách ``[kind, spec]``; enum ``[[...]]`` không có spec."""
    return raw[0], (raw[1] if len(raw) > 1 else {})


def _check_value(node_id: str, key: str, kind: Any, spec: dict, value: Any,
                 graph: dict[str, Any], problems: list[str]) -> None:
    """Kiểm một input vô hướng (hoặc link) theo kiểu đã khai trong object_info."""
    where = f"{node_id}: {key}={value!r}"
    if isinstance(value, list):  # link [node_id, output_index]
        if len(value) != 2 or value[0] not in graph:
            problems.append(f"{node_id}: {key} has bad link {value!r}")
            return
        src = graph[value[0]]["class_type"]
        outs = SNAPSHOT[src]["output"]
        idx = value[1]
        if not isinstance(idx, int) or idx >= len(outs):
            problems.append(f"{node_id}: {key} <- {src}[{idx!r}] out of range")
        elif not isinstance(kind, list) and kind != "COMBO" and outs[idx] != kind:
            problems.append(f"{node_id}: {key} <- {src}[{idx}] is {outs[idx]}, need {kind}")
        return
    if isinstance(kind, list):  # enum thô
        if value not in kind:
            problems.append(f"{where} not in {kind}")
        return
    if kind == "COMBO":
        options = spec.get("options")
        if options and value not in options:
            problems.append(f"{where} not in options {options}")
        return
    if kind == "INT":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "FLOAT":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "STRING":
        ok = isinstance(value, str)
    elif kind == "BOOLEAN":
        ok = isinstance(value, bool)
    else:  # kiểu link (IMAGE, VIDEO, AUDIO…) mà lại được truyền là literal
        problems.append(f"{where}: {kind} needs a link, got literal")
        return
    if not ok:
        problems.append(f"{where}: expected {kind}")
        return
    lo, hi = spec.get("min"), spec.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        problems.append(f"{where}: outside [{lo}, {hi}]")


def _walk(node_id: str, prefix: str, groups: dict, given: dict[str, Any], graph: dict[str, Any],
          problems: list[str], expected: set[str]) -> None:
    """Duyệt đúng nhánh DynamicCombo đang chọn; mỗi khoá hợp lệ được thêm vào ``expected``."""
    for section in SECTIONS:
        for name, raw in (groups.get(section) or {}).items():
            kind, spec = _entry(raw)
            if spec.get("hidden"):  # input ẩn (codec phẳng kiểu cũ) không được phát
                continue
            key = f"{prefix}{name}"
            expected.add(key)
            if key not in given:
                if section == "required":
                    problems.append(f"{node_id}: missing required {key}")
                continue
            value = given[key]
            if kind == DYNAMIC:
                option = next((o for o in spec.get("options", []) if o.get("key") == value), None)
                if option is None:
                    problems.append(f"{node_id}: {key}={value!r} not in {[o.get('key') for o in spec.get('options', [])]}")
                    continue
                _walk(node_id, f"{key}.", option.get("inputs", {}), given, graph, problems, expected)
            else:
                _check_value(node_id, key, kind, spec, value, graph, problems)


def schema_problems(graph: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for node_id, node in graph.items():
        info = SNAPSHOT.get(node["class_type"])
        if info is None:
            problems.append(f"{node_id}: unknown class_type {node['class_type']}")
            continue
        given = node["inputs"]
        expected: set[str] = set()
        _walk(node_id, "", info["input"], given, graph, problems, expected)
        problems += [f"{node_id}: unknown input {k!r} on {node['class_type']}" for k in given if k not in expected]
    return problems


def _graph() -> dict[str, Any]:
    return build_graph("jjv-up-x.mp4", "RealESRGAN_x4plus.pth", "center", 1920, 1080, "jjv-up/S01-r001-abc")


def test_emitted_graph_matches_live_object_info_snapshot() -> None:
    assert schema_problems(_graph()) == []


def test_save_video_uses_dynamic_combo_dotted_codec_key() -> None:
    inputs = _graph()[SAVE_NODE]["inputs"]
    assert inputs["format"] == "mp4" and inputs["format.codec"] == "h264" and "codec" not in inputs


def test_validator_catches_the_old_flat_codec_key() -> None:  # cổng phải đỏ được
    bad = copy.deepcopy(_graph())
    bad[SAVE_NODE]["inputs"].pop("format.codec")
    bad[SAVE_NODE]["inputs"]["codec"] = "h264"
    assert any("unknown input 'codec'" in p for p in schema_problems(bad))


def test_validator_catches_bad_link_type_and_bad_enum() -> None:
    bad = copy.deepcopy(_graph())
    bad["5"]["inputs"]["crop"] = "pad"
    bad["6"]["inputs"]["images"] = ["2", 1]  # AUDIO vào IMAGE
    problems = schema_problems(bad)
    assert any("crop='pad'" in p for p in problems) and any("images <- GetVideoComponents[1]" in p for p in problems)


def test_validator_rejects_misspelled_optional_nested_key() -> None:  # mutation: khoá lồng sai tên
    bad = copy.deepcopy(_graph())
    bad[SAVE_NODE]["inputs"]["format.codec.encodingg"] = "re-encode"
    assert any("unknown input 'format.codec.encodingg'" in p for p in schema_problems(bad))


def test_validator_rejects_wrong_scalar_type_in_nested_input() -> None:  # mutation: sai kiểu scalar lồng
    bad = copy.deepcopy(_graph())
    inputs = bad[SAVE_NODE]["inputs"]
    inputs["format.codec.encoding"] = "re-encode"
    inputs["format.codec.encoding.crf"] = "NOT_A_FLOAT"
    problems = schema_problems(bad)
    assert any("format.codec.encoding.crf" in p and "expected FLOAT" in p for p in problems)
