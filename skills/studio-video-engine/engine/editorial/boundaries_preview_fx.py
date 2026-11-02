"""PROXY compositor for ``boundaries preview``: numpy frames of one transition from two source clips.

This is a quick look, not the kit renderer: the same timing (window, tail frames, schedule) and the same
parameters, but simple pixel maths, so the user can choose by eye without a full render.  Where the proxy has no
faithful version (story-specific cloud / bubble wipes, the ending iris, card slide, end plate) ``compose`` raises
``ProxyUnavailable`` and the gallery says so instead of faking an effect.

``compose(preset, frames, direction, params, t, A, B)`` returns the frame at global offset ``t`` from the
boundary (``t = 0`` is the first frame of the incoming shot); ``A(t)`` / ``B(t)`` return uint8 ``(h, w, 3)`` arrays.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from ..qa.review_media import numpy_module
from . import presets

Source = Callable[[int], Any]
UNSUPPORTED = ("cloud", "bubble", "iris", "card_slide", "plate_in")
WARM = {"leak": (255, 214, 140), "burn": (255, 150, 70)}


class ProxyUnavailable(Exception):
    """The proxy has no faithful version of this preset."""


def ease(kind: str, x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 2 if kind == "out" else x * x * (3 - 2 * x)


def mix(a: Any, b: Any, weight: Any) -> Any:
    """``a * (1 - weight) + b * weight`` as uint8; ``weight`` is a scalar or an ``(h, w)`` / ``(h, w, 1)`` map."""
    np = numpy_module()
    w = np.asarray(weight, dtype=np.float32)
    w = w[..., None] if w.ndim == 2 else w
    return np.clip(a.astype(np.float32) * (1 - w) + b.astype(np.float32) * w + 0.5, 0, 255).astype(np.uint8)


def _taps(size: int, scale: float) -> tuple[Any, Any, Any, Any]:
    np = numpy_module()
    pos = (np.arange(size) - (size - 1) / 2) / scale + (size - 1) / 2
    lo = np.floor(pos).astype(int)
    frac = (pos - lo).astype(np.float32)
    inside = (pos >= 0) & (pos <= size - 1)
    return np.clip(lo, 0, size - 1), np.clip(lo + 1, 0, size - 1), frac, inside


def scale_xy(img: Any, sx: float, sy: float) -> tuple[Any, Any]:
    """Bilinear scale about the centre; returns ``(image, inside_mask)`` (outside pixels are edge copies)."""
    np = numpy_module()
    h, w = img.shape[:2]
    y0, y1, fy, iy = _taps(h, sy)
    x0, x1, fx, ix = _taps(w, sx)
    rows = img[y0].astype(np.float32) * (1 - fy)[:, None, None] + img[y1].astype(np.float32) * fy[:, None, None]
    cols = rows[:, x0] * (1 - fx)[None, :, None] + rows[:, x1] * fx[None, :, None]
    return np.clip(cols + 0.5, 0, 255).astype(np.uint8), iy[:, None] & ix[None, :]


def blur(img: Any, px: float) -> Any:
    """Box blur of radius ``px`` (separable, cumulative sums)."""
    np = numpy_module()
    radius = int(round(px))
    if radius < 1:
        return img
    out = img.astype(np.float32)
    for axis in (0, 1):
        n = out.shape[axis]
        padded = np.concatenate([np.repeat(np.take(out, [0], axis), radius, axis), out,
                                 np.repeat(np.take(out, [n - 1], axis), radius, axis)], axis)
        csum = np.cumsum(padded, axis=axis, dtype=np.float64)
        csum = np.concatenate([np.zeros_like(np.take(csum, [0], axis)), csum], axis)
        hi = np.take(csum, np.arange(2 * radius + 1, n + 2 * radius + 1), axis)
        lo = np.take(csum, np.arange(0, n), axis)
        out = ((hi - lo) / (2 * radius + 1)).astype(np.float32)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def shift_x(img: Any, dx: float, smear: float) -> Any:
    """Slide horizontally by ``dx`` px with edge pixels extended and a horizontal motion smear of ``smear`` px."""
    np = numpy_module()
    w = img.shape[1]
    taps = max(1, int(smear / 6) + 1)
    acc = np.zeros(img.shape, np.float32)
    for j in range(taps):
        offset = (j / max(taps - 1, 1) - 0.5) * smear if taps > 1 else 0.0
        acc += img[:, np.clip(np.round(np.arange(w) - dx + offset).astype(int), 0, w - 1)]
    return np.clip(acc / taps + 0.5, 0, 255).astype(np.uint8)


def _progress(t: int, frames: int) -> float:
    return (t + 1) / (frames + 1)


def _cut(p, frames, direction, params, t, A, B):
    return A(t) if t < 0 else B(t)


def _cut_push(p, frames, direction, params, t, A, B):
    if t < 0:
        return A(t)
    if t >= frames:
        return B(t)
    s = 1 + (params["scale_from"] - 1) * (1 - ease(params["ease"], t / frames))
    return scale_xy(B(t), s, s)[0]


def _whip(p, frames, direction, params, t, A, B):
    half = frames // 2
    if t < -half:
        return A(t)
    if t >= half:
        return B(t)
    if t < 0:
        frame, x, sign = A(t), (t + half + 1) / half, -direction
    else:
        frame, x, sign = B(t), (half - 1 - t) / half, direction
    width = frame.shape[1]
    return shift_x(frame, sign * width * 0.55 * x * x, width * 0.05 * x)


def _dip(p, frames, direction, params, t, A, B):
    np = numpy_module()
    rows = {row["t"]: row for row in p.data["schedule"]}
    if t < min(rows):
        return A(t)
    if t > max(rows):
        return B(t)
    row = rows[t]
    overlay = p.data["overlay"]
    colour = overlay.get("colour")
    rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5)) if colour else WARM[overlay["kind"]]
    base = {"out": A, "out_tail": A, "in": B}.get(row["shot"])
    frame = base(t) if base else A(-1)
    flat = np.empty_like(frame)
    flat[...] = rgb
    return mix(frame, flat, row["white"])


def _fade(p, frames, direction, params, t, A, B):
    if t < 0:
        return A(t)
    if t >= frames:
        return B(t)
    x = _progress(t, frames)
    a, b = A(t), B(t)
    if p.renders_as == "dissolve":
        return mix(a, b, ease(params.get("curve", "in_out"), x))
    px = params["blur_px"] * math.sin(math.pi * x)
    if p.name == "focus_pull":
        return mix(blur(a, params["blur_px"] * x), blur(b, params["blur_px"] * (1 - x)), ease("in_out", x))
    return mix(blur(a, px), blur(b, px), ease("in_out", x))


def _push_slide(p, frames, direction, params, t, A, B):
    np = numpy_module()
    if t < 0:
        return A(t)
    if t >= frames:
        return B(t)
    a, b = A(t), B(t)
    axis = 1 if params["axis"] == "x" else 0
    n = a.shape[axis]
    cut = int(round(ease(params["ease"], _progress(t, frames)) * n))
    if direction > 0:   # the new shot pushes the old one out towards the start of the axis
        return np.concatenate([np.take(a, np.arange(cut, n), axis), np.take(b, np.arange(0, cut), axis)], axis)
    return np.concatenate([np.take(b, np.arange(n - cut, n), axis), np.take(a, np.arange(0, n - cut), axis)], axis)


def _mask_reveal(shape: tuple, kind: str, x: float, direction: int, params: dict) -> Any:
    """Weight map (0 = outgoing, 1 = incoming) of a wipe at progress ``x``."""
    np = numpy_module()
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = params.get("centre_x", 0.5) * w, params.get("centre_y", 0.5) * h
    if kind == "wipe":
        edge, soft = (x * (w + 0.2 * w) - 0.1 * w), 0.1 * w
        coord = xx if direction > 0 else w - xx
        return np.clip((edge - coord) / soft + 0.5, 0, 1)
    if kind == "iris_circle":
        return np.clip((x * math.hypot(w, h) * 0.55 - np.hypot(xx - cx, yy - cy)) / max(params["softness_px"], 1) + 0.5, 0, 1)
    if kind == "iris_diamond":
        return np.clip((x * (w + h) * 0.55 - (np.abs(xx - cx) + np.abs(yy - cy))) / max(params["softness_px"], 1) + 0.5, 0, 1)
    if kind == "clock_wipe":
        angle = (np.degrees(np.arctan2(xx - cx, -(yy - cy))) - params["start_angle_deg"]) % 360
        angle = angle if params["clockwise"] else 360 - angle
        return np.clip((x * 360 - angle) / 3 + 0.5, 0, 1)
    count = params["count"]
    local = (yy / h if params["axis"] == "h" else xx / w) * count % 1.0
    return np.clip((x * 1.1 - local) * 12, 0, 1)


def _wipe(p, frames, direction, params, t, A, B):
    if t < 0:
        return A(t)
    if t >= frames:
        return B(t)
    a = A(t)
    return mix(a, B(t), _mask_reveal(a.shape, p.renders_as, ease("in_out", _progress(t, frames)), direction, params))


def _zoom(p, frames, direction, params, t, A, B):
    if t < 0:
        return A(t)
    if t >= frames:
        return B(t)
    x = _progress(t, frames)
    a, b = A(t), B(t)
    if p.renders_as == "zoom_out":
        s = 1 + (params["scale_to"] - 1) * ease("in_out", x)
        small, inside = scale_xy(a, s, s)
        return mix(b, small, inside.astype("float32"))
    big, _ = scale_xy(a, 1 + (params["scale_out"] - 1) * x, 1 + (params["scale_out"] - 1) * x)
    s_in = params["scale_in_from"] + (1 - params["scale_in_from"]) * x
    new, inside = scale_xy(b, s_in, s_in)
    return mix(blur(big, params["blur_px"] * x), new, inside.astype("float32") * ease("in_out", x))


def _flip(p, frames, direction, params, t, A, B):
    np = numpy_module()
    if t < 0:
        return A(t)
    if t >= frames:
        return B(t)
    x = _progress(t, frames)
    first = x < 0.5
    theta = (x if first else 1 - x) * math.pi
    s = max(math.cos(theta), 0.02)
    sx, sy = (s, 1.0) if params["axis"] == "y" else (1.0, s)
    img, inside = scale_xy(A(t) if first else B(t), sx, sy)
    return mix(np.zeros_like(img), img, inside.astype("float32"))


def _bloom(p, frames, direction, params, t, A, B):
    half = frames // 2
    if t < -half:
        return A(t)
    if t >= half:
        return B(t)
    base = A(t) if t < 0 else B(t)
    flat = base.copy()
    flat[...] = (255, 235, 200)
    return mix(base, flat, 0.55 * math.sin(math.pi * (t + half + 0.5) / frames))


FAMILIES = {"cut": _cut, "none": _cut, "cut_push": _cut_push, "whip": _whip, "dip_white": _dip, "dissolve": _fade,
            "blur_crossfade": _fade, "focus_pull": _fade, "push_slide": _push_slide, "wipe": _wipe,
            "iris_circle": _wipe, "iris_diamond": _wipe, "clock_wipe": _wipe, "blinds": _wipe,
            "zoom_through": _zoom, "zoom_out": _zoom, "card_flip_3d": _flip, "bloom": _bloom}


def supported(preset: presets.Preset) -> bool:
    return preset.renders_as in FAMILIES and preset.name not in UNSUPPORTED


def compose(preset: presets.Preset, frames: int, direction: int, params: dict, t: int, A: Source, B: Source) -> Any:
    if not supported(preset):
        raise ProxyUnavailable(f"the proxy has no faithful version of '{preset.name}' (renders_as {preset.renders_as}); "
                               "use the kit renderer")
    return FAMILIES[preset.renders_as](preset, frames, direction, params, t, A, B)
