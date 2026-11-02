"""Nhánh LONG-TAKE của ``jjv video`` (BP-42): một shot MỘT CÚ dài hơn ~15 s bằng H3 + ``ContextWindowsManual``.

CPU thuần: không GPU, không mạng, không ghi production.  Dữ liệu (template, sha, ngưỡng, số window tối đa, node của từng window)
nằm trong khối ``long_take`` của hàng domain ở ``recipes/video/routes-v001.json``; code ở đây không nêu tên domain: domain nào
KHÔNG có khối ``long_take`` (hay khối đó khai domain khác) thì bị từ chối bằng mã ``LONG_TAKE_DOMAIN_REFUSED`` (không trộn domain).

CHƯA ĐO TRÊN GPU.  ``WINDOW_TABLE`` bên dưới là BẢNG THAM KHẢO lấy từ một bài đăng bên thứ ba (Pika H3 Flex), KHÔNG phải số đo của
máy này; công thức giữa các điểm là fit tay.  Chỉ sau pilot GPU 20 s (docs/plans/2026-11-01-two-systems/LONGTAKE-UAT-RUNBOOK.md)
mới có số thật, và route cần receipt qualification RIÊNG (receipt h3 30cd429b chỉ phủ ``h3-ref2va``).

Chọn chế độ (``take_mode`` = short | long | auto, mặc định auto): auto -> long khi ``duration_s`` > ``auto_long_over_s`` (15) hoặc shot
đặt ``long_take: true``.  Shot dài mà rơi vào route ngắn ⇒ Refused ``TAKE_SHORT_ROUTE_REFUSED`` / ``LONG_TAKE_ON_SHORT_ROUTE``;
engine không bao giờ lặng lẽ cắt một cú dài thành ngắn.
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..layout.context import REPO_ROOT
from . import routes as routes_mod

TAKE_MODES = ("short", "long", "auto")
DEFAULT_TAKE_MODE = "auto"

# BẢNG THAM KHẢO (không đo): độ dài cú (giây) -> số window, theo ảnh bảng user gửi 01/11.  Giữa các điểm dùng fit
# n = floor(0.275*T + 0.5) (khớp đủ 6 điểm; ngoài 20-60 s chưa kiểm).  Đừng coi đây là đặc tính của H3 trên máy này.
WINDOW_TABLE: dict[int, int] = {20: 6, 25: 7, 30: 8, 40: 11, 50: 14, 60: 17}
_FIT_SLOPE = 0.275


def window_count(duration_s: float, max_windows: int | None = None) -> int:
    """Số window cho một cú dài ``duration_s`` giây (BẢNG THAM KHẢO, xem đầu file).  Tối thiểu 1; vượt ``max_windows`` ⇒ Refused."""
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or duration_s <= 0:
        raise Refused(f"LONG_TAKE_DURATION_INVALID: duration_s must be a positive number, got {duration_s!r}")
    exact = WINDOW_TABLE.get(int(duration_s)) if float(duration_s).is_integer() else None
    count = exact if exact is not None else max(1, math.floor(_FIT_SLOPE * float(duration_s) + 0.5))
    if max_windows is not None and count > max_windows:
        raise Refused(f"LONG_TAKE_TOO_MANY_WINDOWS: {duration_s:g} s needs {count} windows (reference table) but the template "
                      f"holds {max_windows}; nothing was cut short - a bigger template is needed")
    return count


def long_block(domain_id: str, route_row: dict[str, Any]) -> dict[str, Any]:
    """Khối ``long_take`` của hàng routes; domain khác khối khai (hoặc không có khối) ⇒ Refused (không trộn domain)."""
    block = route_row.get("long_take")
    if not isinstance(block, dict) or block.get("domain") != domain_id:
        raise Refused(f"LONG_TAKE_DOMAIN_REFUSED: domain {domain_id!r} has no long-take route (only "
                      f"{(block or {}).get('domain')!r} does); a long-take template is per domain, never shared; "
                      "nothing was written")
    for key in ("route", "template", "auto_long_over_s", "max_windows", "windows"):
        if key not in block:
            raise Refused(f"video routes: long_take of {domain_id!r} is missing {key!r}")
    return block


def wants_long(shot: dict[str, Any], threshold_s: float) -> str | None:
    """Lý do shot cần cú dài (``None`` nếu không): ``long_take: true`` hoặc ``duration_s`` > ngưỡng."""
    if shot.get("long_take") is True:
        return "shot sets long_take: true"
    duration = shot.get("duration_s")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > threshold_s:
        return f"duration_s {duration:g} > {threshold_s:g} s"
    return None


def decide_take_mode(domain_id: str, route_row: dict[str, Any], shot: dict[str, Any],
                     take_mode: str | None = None) -> dict[str, Any]:
    """Quyết định ``{take_mode, route, reason, ...}`` để ghi vào plan/run receipt (lý do luôn được ghi).

    short -> route ngắn ``h3_route``; long -> ``long_take.route``; auto -> long khi shot cần cú dài, ngược lại short."""
    requested = take_mode or DEFAULT_TAKE_MODE
    if requested not in TAKE_MODES:
        raise Refused(f"TAKE_MODE_INVALID: take_mode {requested!r} is not one of {list(TAKE_MODES)}")
    block = route_row.get("long_take") if isinstance(route_row.get("long_take"), dict) else None
    threshold = float(block["auto_long_over_s"]) if block and "auto_long_over_s" in block else 15.0
    need = wants_long(shot, threshold)
    if requested == "short":
        if need:
            raise Refused(f"TAKE_SHORT_ROUTE_REFUSED: shot {shot.get('id')!r} is a long take ({need}) but take_mode=short would "
                          "cut it short; use take_mode=long or auto (nothing was cut)")
        mode, reason = "short", "take_mode=short requested; shot is within the short-route range"
    elif requested == "long":
        mode, reason = "long", "take_mode=long requested" + (f" ({need})" if need else "")
    elif need:
        mode, reason = "long", f"take_mode=auto: {need}"
    else:
        mode, reason = "short", (f"take_mode=auto: duration_s {shot.get('duration_s')} <= {threshold:g} s "
                                 "and no long_take flag")
    route = route_row.get("h3_route")
    if mode == "long":
        route = long_block(domain_id, route_row)["route"]  # domain khác ⇒ Refused tại đây
    return {"take_mode_requested": requested, "take_mode": mode, "route": route, "reason": reason,
            "duration_s": shot.get("duration_s"), "threshold_s": threshold, "long_take_flag": shot.get("long_take") is True}


def guard_route(decision: dict[str, Any], route_name: str) -> None:
    """Route CLI đưa vào phải khớp quyết định; cú dài trên route ngắn ⇒ Refused (không cắt lặng lẽ)."""
    if decision["route"] == route_name:
        return
    if decision["take_mode"] == "long":
        raise Refused(f"LONG_TAKE_ON_SHORT_ROUTE: the shot is a long take ({decision['reason']}) so route "
                      f"{decision['route']!r} is required, got {route_name!r}; nothing was sent")
    raise Refused(f"TAKE_ROUTE_MISMATCH: take_mode={decision['take_mode']} needs route {decision['route']!r}, "
                  f"got {route_name!r}; nothing was sent")


def long_template(domain_id: str, route_row: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Template long-take của domain: đường dẫn + sha đã kiểm (đổi byte ⇒ Refused)."""
    return routes_mod.template_for({"template": long_block(domain_id, route_row)["template"]}, repo_root)


def _beat_text(item: Any) -> str:
    text = item.get("beat") if isinstance(item, dict) else item
    if not isinstance(text, str) or not text.strip():
        raise Refused(f"LONG_TAKE_BEAT_INVALID: a beat must be a non-empty string (or {{'beat': text}}), got {item!r}")
    return text.strip()


def window_beats(shot: dict[str, Any], windows: int) -> list[str]:
    """Một beat cho mỗi window.  ``windows[]`` của shot phải ĐÚNG ``windows`` phần tử; ``beats[]`` ngắn hơn được trải đều
    (window k lấy beat ``floor(k*len/windows)``), dài hơn ⇒ Refused.  Không có cả hai ⇒ Refused: không tự bịa hành động."""
    explicit = shot.get("windows")
    if explicit is not None:
        if not isinstance(explicit, list) or len(explicit) != windows:
            got = len(explicit) if isinstance(explicit, list) else explicit
            raise Refused(f"LONG_TAKE_WINDOWS_MISMATCH: shot {shot.get('id')!r} lists {got!r} windows[] but the duration "
                          f"needs {windows}")
        return [_beat_text(item) for item in explicit]
    beats = shot.get("beats")
    if not isinstance(beats, list) or not beats:
        raise Refused(f"LONG_TAKE_NO_BEATS: shot {shot.get('id')!r} needs beats[] or windows[] (never invented by the engine)")
    if len(beats) > windows:
        raise Refused(f"LONG_TAKE_BEATS_MISMATCH: {len(beats)} beats do not fit {windows} windows; merge beats or lengthen "
                      "the take")
    return [_beat_text(beats[k * len(beats) // windows]) for k in range(windows)]


def split_prompt(global_block: str, beats: list[str], duration_s: float) -> dict[str, Any]:
    """``{"global": khối CHUNG, "windows": [prompt đầy đủ mỗi window]}``.

    ``global_block`` là prompt do ``prompt.compose`` dựng (cast, luật trang phục, props, style, lens, light, luật âm thanh) và được
    dùng NGUYÊN VĂN, không sửa; mỗi window = khối chung + một dòng ``Window k of n (t0-t1 s): beat``.  Vì mỗi window được mã hoá
    riêng bằng một node R2V, luật trang phục/props có mặt trong MỌI window."""
    count = len(beats)
    if not global_block.strip() or count < 1:
        raise Refused("LONG_TAKE_PROMPT_EMPTY: need a global block and at least one beat")
    rows = []
    for k, beat in enumerate(beats):
        t0, t1 = duration_s * k / count, duration_s * (k + 1) / count
        line = (f"Window {k + 1} of {count} ({t0:.1f}-{t1:.1f} s of one continuous take, same camera, same character, "
                f"same wardrobe): {beat}")
        rows.append(global_block.rstrip("\n") + "\n" + line + "\n")
    return {"global": global_block, "windows": rows}


def window_log(duration_s: float, frames: int, prompts: list[str]) -> list[dict[str, Any]]:
    """Một hàng nhật ký mỗi window (STEP_IO_ALWAYS_SAVED): chỉ số, giây, khoảng frame, sha256 prompt.  Khoảng frame là chia đều
    trên số frame của cả cú; ánh xạ window -> latent THẬT của ContextWindowsManual chưa đo (UAT phải đo)."""
    count = len(prompts)
    return [{"window": k, "t0_s": round(duration_s * k / count, 3), "t1_s": round(duration_s * (k + 1) / count, 3),
             "frame_start": frames * k // count, "frame_end": frames * (k + 1) // count - 1,
             "prompt_sha256": hashlib.sha256(p.encode("utf-8")).hexdigest()} for k, p in enumerate(prompts)]


def build_graph(template: dict[str, Any], block: dict[str, Any], prompts: list[str], *, width: int | None = None,
                height: int | None = None, length: int | None = None) -> dict[str, Any]:
    """Bản sao graph: điền prompt từng window, bỏ slot thừa (ít window hơn 8), nối lại ``AddGuide.positive``, đồng bộ cỡ/độ dài
    cho mọi node R2V đang dùng.  ``template`` không bị sửa."""
    nodes = block["windows"]
    n, cap = len(prompts), int(block["max_windows"])
    if not 1 <= n <= cap:
        raise Refused(f"LONG_TAKE_TOO_MANY_WINDOWS: {n} windows, the template holds 1..{cap}")
    graph = copy.deepcopy(template)
    for k, text in enumerate(prompts):
        graph[nodes["prompt_nodes"][k]]["inputs"]["value"] = text
    for k in range(n, cap):
        for key in ("prompt_nodes", "r2v_nodes"):
            graph.pop(nodes[key][k], None)
        if k >= 1:
            graph.pop(nodes["combine_nodes"][k - 1], None)
    last = nodes["r2v_nodes"][0] if n == 1 else nodes["combine_nodes"][n - 2]
    graph[nodes["guide_node"]]["inputs"]["positive"] = [last, 0]
    for k in range(n):
        for key, value in (("width", width), ("height", height), ("length", length)):
            if value is not None:
                graph[nodes["r2v_nodes"][k]]["inputs"][key] = value
    return graph


__all__ = ["TAKE_MODES", "DEFAULT_TAKE_MODE", "WINDOW_TABLE", "window_count", "long_block", "wants_long", "decide_take_mode",
           "guard_route", "long_template", "window_beats", "split_prompt", "window_log", "build_graph"]
