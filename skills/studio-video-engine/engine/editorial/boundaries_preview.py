"""``jjv editorial boundaries preview``: render ONLY a short window of one boundary per candidate preset.

Each candidate is composited from the two SOURCE clips (24 delivery frames each side of the cut by default,
1920x1080 @ delivery fps, CPU only: ffmpeg + numpy) into a gallery folder with a contact page, so the user picks
by eye without a full render.  The look is the PROXY compositor (:mod:`boundaries_preview_fx`): same timing,
tail frames and parameters as the kit, simpler pixel maths.  A preset the rule does not allow here is still
rendered when asked (to compare by eye) and labelled with the rule's verdict; a preset whose tail handle is too
short is never faked: its card carries the reason and no clip (no GPU work is ever requested).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file, write_json_atomic
from ..qa.review_media import numpy_module, write_png
from ..seedvr2.seam_media import ffmpeg_flags
from . import boundaries_preview_fx as fx
from . import boundaries_suggest as bs
from . import presets, transitions
from .boundaries_suggest_parity import normalise
from .boundaries_preview_html import write_index

SCHEMA = "jjv/boundaries-preview/v1"
CONTEXT_FRAMES = 24
WIDTH, HEIGHT = 1920, 1080
PREVIEW_ALIASES = {"flash": "dip_white"}
PARAM_TYPES = {"true": True, "false": False}


class TailMissing(Exception):
    """A frame beyond the clip's end was asked for (a preset that needs a tail the handle does not have)."""


def parse_tokens(text: str) -> list[dict]:
    """``push,dip,whip:direction=-1,cut_push:frames=8:scale_from=1.06`` -> ``[{name, frames, direction, params}]``."""
    out = []
    for token in (t.strip() for t in text.split(",") if t.strip()):
        name, *pairs = token.split(":")
        entry: dict[str, Any] = {"token": token, "name": PREVIEW_ALIASES.get(name, normalise(name)),
                                 "frames": None, "direction": None, "params": {}}
        for pair in pairs:
            key, _, raw = pair.partition("=")
            if not raw:
                raise Refused(f"preset option {pair!r} in {token!r} must be key=value")
            value = PARAM_TYPES.get(raw, raw)
            if isinstance(value, str):
                try:
                    value = json.loads(raw)
                except ValueError:
                    pass
            if key in ("frames", "direction"):
                entry[key] = value
            else:
                entry["params"][key] = value
        out.append(entry)
    if not out:
        raise Refused("--presets names no preset")
    return out


def decode_rgb(clip: Path, indices: list[int], ffmpeg: str) -> dict[int, Any]:
    """``{native index: RGB (HEIGHT, WIDTH, 3)}`` cover-scaled from the clip; indices past the end are absent."""
    np = numpy_module()
    wanted = sorted(set(indices))
    if not wanted:
        return {}
    select = "+".join(f"eq(n\\,{i})" for i in wanted)
    vf = (f"select='{select}',scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={WIDTH}:{HEIGHT}")
    result = subprocess.run([ffmpeg, "-v", "error", "-i", str(clip), "-an", "-vf", vf, "-fps_mode", "passthrough",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True,
                            creationflags=ffmpeg_flags(), check=False)
    size = WIDTH * HEIGHT * 3
    if result.returncode != 0 or len(result.stdout) % size:
        raise Uncertain(f"cannot decode {clip.name}: {result.stderr.decode(errors='replace')[:200]}")
    data = np.frombuffer(result.stdout, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)
    return {index: frame for index, frame in zip(wanted, data)}


class Sources:
    """The two sides of one boundary as ``A(t)`` / ``B(t)`` (``t`` = delivery frames from the cut, 0 = first B frame)."""

    def __init__(self, ctx: dict, a: dict, b: dict, clip: Path | None, span: tuple[int, int], ffmpeg: str) -> None:
        root, grid = ctx["root"], ctx["grid"]
        self.rate = grid["native_fps"] / grid["fps"]
        self.length_a, self.editorial = grid["lengths"][a["shot"]], a["clip"]["frames"]
        lo, hi = span
        pre = {self._index_a(t) for t in range(lo, 0)}
        post = {self._index_a(t) for t in range(0, hi)}
        self.a_edit = decode_rgb(root / a["clip"]["path"], sorted(pre), ffmpeg)
        self.a_tail = decode_rgb(clip, sorted(post), ffmpeg) if clip is not None and clip.is_file() else {}
        self.b = decode_rgb(root / b["clip"]["path"], sorted({self._index_b(t) for t in range(0, hi)}), ffmpeg)

    def _index_a(self, t: int) -> int:
        return int((self.length_a + t) * self.rate)

    def _index_b(self, t: int) -> int:
        return int(max(t, 0) * self.rate)

    def A(self, t: int) -> Any:
        index = self._index_a(t)
        frame = (self.a_edit if index < self.editorial else self.a_tail).get(index)
        if frame is None:
            raise TailMissing(f"outgoing frame {index} (t={t}) is not in the clip")
        return frame

    def B(self, t: int) -> Any:
        frame = self.b.get(self._index_b(t))
        if frame is None:
            raise TailMissing(f"incoming frame {self._index_b(t)} (t={t}) is not in the clip")
        return frame


def verdict(item: dict, name: str, pictures: frozenset) -> dict:
    """Is ``name`` something the rule allows on this boundary, and if not why not (engine row rules first)."""
    allowed = [item["chosen"]["type"]] + [o["type"] for o in item["alternatives"]]
    if name in allowed:
        return {"allowed": True, "chosen": name == item["chosen"]["type"], "rule": item["rule"],
                "text": ("the rule's choice" if name == item["chosen"]["type"] else "allowed alternative")
                + f" ({item['rule']})"}
    probe = {"from_shot": item["from"], "to_shot": item["to"], "class": "cut", "motivation": "preview", "frame": 0,
             "continuity": item["declared"].get("continuity") or "unknown"}
    engine = transitions.eligibility(probe, name, pictures)
    why = engine or (f"not suggested by {item['rule']} (framing {item['framing']['framing']}, ncc "
                     f"{item['measured']['ncc']}): the rule allows {', '.join(allowed)} here")
    return {"allowed": False, "chosen": False, "rule": item["rule"], "text": why}


def candidate_spec(item: dict, entry: dict) -> dict:
    """Frames / direction / params for one candidate: the token's own, else the rule's option, else the defaults."""
    preset = presets.get(entry["name"], label=entry["token"])
    known = {o["type"]: o for o in [item["chosen"], *item["alternatives"]]}
    base = known.get(entry["name"]) or {"frames": presets.default_frames(preset),
                                        "direction": item["chosen"].get("direction") or 1}
    frames = entry["frames"] if entry["frames"] is not None else base["frames"]
    direction = entry["direction"] if entry["direction"] is not None else base["direction"]
    if preset.direction != "required":
        direction = 0
    message = presets.frames_message(preset, frames, entry["token"]) or presets.direction_message(preset, direction,
                                                                                                  entry["token"])
    if message:
        raise Refused(message)
    presets.check_params(preset, entry["params"], entry["token"])
    return {"preset": preset, "frames": frames, "direction": direction,
            "params": presets.resolve_params(preset, entry["params"])}


def _encode(out: Path, ffmpeg: str, fps: int):
    return subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                             f"{WIDTH}x{HEIGHT}", "-framerate", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset",
                             "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=ffmpeg_flags())


def render_candidate(spec: dict, ctx: dict, src: Sources, span: tuple[int, int], out: Path, poster: Path,
                     ffmpeg: str) -> dict:
    """Composite one candidate window to ``out`` (mp4) and ``poster`` (png); returns seconds, window and the command."""
    preset, started = spec["preset"], time.perf_counter()
    command = _encode(out, ffmpeg, ctx["grid"]["fps"])
    start, end = presets.window(preset, 0, spec["frames"], spec["params"])
    peak = (start + end) // 2 if end > start else 0
    poster_frame = None
    try:
        for t in range(*span):
            frame = fx.compose(preset, spec["frames"], spec["direction"], spec["params"], t, src.A, src.B)
            command.stdin.write(frame.tobytes())
            if t == peak:
                poster_frame = frame
        command.stdin.close()
        if command.wait() != 0:
            raise Uncertain(f"ffmpeg encode failed: {command.stderr.read().decode(errors='replace')[:200]}")
    except BaseException:
        command.kill()
        raise
    finally:
        for stream in (command.stdin, command.stderr):
            stream.close()
    write_png(poster, poster_frame[::3, ::3], ffmpeg)
    return {"render_seconds": round(time.perf_counter() - started, 3), "window": [start, end], "peak_offset": peak,
            "sha256": sha256_file(out), "bytes": out.stat().st_size}


def _candidate_rows(item: dict, tokens: list[dict], specs: list[dict], ctx: dict, a: dict, b: dict) -> tuple:
    """One record row per candidate (verdict, tail availability at ITS frame count) + the shared tail clip."""
    rows, clip, source = [], None, None
    for token, spec in zip(tokens, specs):
        name = spec["preset"].name
        feas, outgoing, clip, source = bs.feasibility_for(ctx["root"], a, b, ctx["declared_rows"].get(
            (a["shot"], b["shot"])), ctx["grid"], ctx["probe"], preset=name, frames=spec["frames"])
        tail = bs.option(name, spec["direction"], feas, outgoing, ctx["grid"])["tail"]
        row = {"token": token["token"], "preset": name, "label": spec["preset"].label, "frames": spec["frames"],
               "direction": spec["direction"], "params": spec["params"],
               "verdict": verdict(item, name, ctx["pictures"]), "tail": tail, "clip": None, "poster": None,
               "proxy_supported": fx.supported(spec["preset"]), "status": "pending", "reason": None}
        if not row["proxy_supported"]:
            row.update(status="not_rendered", reason=f"the proxy has no faithful version of '{name}'; use the kit renderer")
        elif not tail["available"]:
            row.update(status="not_rendered", reason=tail["reason"])
        rows.append(row)
    return rows, clip, source


def preview(ctx: dict, item: dict, tokens: list[dict], out_dir: Path, ffmpeg: str, a: dict, b: dict,
            context_frames: int = CONTEXT_FRAMES, swap_hint: str = "") -> dict:
    """Render every token for boundary ``item`` into ``out_dir``; writes ``preview-record.json`` and ``index.html``."""
    started = time.perf_counter()
    specs = [candidate_spec(item, t) for t in tokens]
    rows, clip, clip_source = _candidate_rows(item, tokens, specs, ctx, a, b)
    windows = [presets.window(s["preset"], 0, s["frames"], s["params"]) for s in specs]
    span = (min([-context_frames] + [w[0] - 6 for w in windows]), max([context_frames] + [w[1] + 6 for w in windows]))
    todo = [(r, s) for r, s in zip(rows, specs) if r["status"] == "pending"]
    decode_started = time.perf_counter()
    src = Sources(ctx, a, b, clip if any(r["tail"]["needed"] for r, _ in todo) else None, span, ffmpeg) if todo else None
    decode_seconds = round(time.perf_counter() - decode_started, 3)
    for sub in ("clips", "posters"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    for row, spec in todo:
        key = row["token"].replace(":", "_").replace("=", "-")
        try:
            done = render_candidate(spec, ctx, src, span, out_dir / "clips" / f"{key}.mp4",
                                    out_dir / "posters" / f"{key}.png", ffmpeg)
        except TailMissing as error:
            (out_dir / "clips" / f"{key}.mp4").unlink(missing_ok=True)
            row.update(status="not_rendered", reason=f"{error}; no GPU work is requested")
            continue
        row.update(status="rendered", clip=f"clips/{key}.mp4", poster=f"posters/{key}.png", **done)
    record = {"schema": SCHEMA, "boundary": item["id"], "from": item["from"], "to": item["to"],
              "renderer": "proxy (numpy + ffmpeg composite of the SOURCE clips; not the kit renderer)",
              "frame_range_from_cut": list(span), "context_frames": context_frames, "size": [WIDTH, HEIGHT],
              "fps": ctx["grid"]["fps"], "measured": item["measured"], "framing": item["framing"], "rule": item["rule"],
              "chosen_by_rule": item["chosen"]["type"], "tail_clip_source": clip_source,
              "decode_seconds": decode_seconds, "render_seconds_total": round(time.perf_counter() - started, 3),
              "candidates": rows, "swap_hint": swap_hint,
              "note": "composite only: no shot video was rendered or requested, no GPU, no network"}
    write_json_atomic(out_dir / "preview-record.json", record, mode="utf8", stamp=True)
    (out_dir / "index.html").write_text(write_index(record), encoding="utf-8")
    return record
