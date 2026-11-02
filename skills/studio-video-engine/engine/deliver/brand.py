"""Wrap the configured brand kit's audio, mux and join tools; keep originals read-only."""
import re
import sys
from pathlib import Path

from ..core.errors import Refused
from ..core.io import read_json, write_json_once
from .common import block, frame_md5, fresh, need, optional, path, probe, receipt, record, run


def title(ctx, out, *, node="node", python=sys.executable):
    cfg = block(ctx, "brand")
    # Every machine/episode value is resolved before anything is created on disk.
    props = need(cfg, "props", "brand")
    # Refuse kit defaults that would silently carry text/art from another episode.
    required = ("titleEn", "titleVi", "subtitle", "brandLine", "background", "logo")
    if not isinstance(props, dict) or any(
            key not in props or not isinstance(props[key], str) or not props[key] for key in required):
        raise Refused(f"brand.props must explicitly declare {required}")
    if props["titleEn"] != ctx["episode"]["title"]:
        raise Refused("brand titleEn differs from episode title")
    kit = path(ctx, need(cfg, "kit", "brand"))
    workspace = path(ctx, need(cfg, "workspace", "brand"))
    packages = path(ctx, need(cfg, "packages", "brand"))
    browser = path(ctx, need(cfg, "browser", "brand"))
    # Optional values are resolved here too: a marker or missing file refuses before the output exists.
    chime = optional(cfg, "chime")
    chime = path(ctx, chime) if chime is not None else None
    if chime is not None and not chime.is_file():
        raise Refused(f"brand.chime file missing: {chime}")
    target_lufs = optional(cfg, "target_lufs", -20)
    render_timeout = optional(cfg, "render_timeout_seconds", 180)
    tools = kit / "tools"
    out = fresh(out)
    commands = []
    result = {"schema": "jjv/brand-title/v1", "binding": ctx["binding"],
              "commands": commands, "status": "failed",
              "kit_inputs": [record(p) for folder in ("src", "public")
                             for p in sorted((kit / folder).rglob("*")) if p.is_file()],
              "tools": [record(tools / name) for name in ("build_segment_audio.py", "mux_segment.py")]}
    try:
        job = {"kit": str(kit), "workspace": str(workspace),
               "packages": str(packages), "browser": str(browser),
               "props": props, "out": str(out / "title-picture.mp4"), "work": str(out / "render-work")}
        write_json_once(out / "title-job.json", job, mode="utf8")
        run([node, Path(__file__).with_name("render_title.cjs"), out / "title-job.json"], commands, cwd=out,
            timeout=render_timeout)
        picture = probe(out / "title-picture.mp4", commands)
        master = ctx["domain"]["delivery"]["master"]
        if (picture["fps"] != "30" or picture["audio_streams"] != 0 or picture["frames"] % 16
                or (picture["width"], picture["height"]) != (master["width"], master["height"])):
            raise Refused("brand kit requires silent 30 fps master-size picture, frames divisible by 16")
        audio = [python, tools / "build_segment_audio.py", "title", "--frames", picture["frames"],
                 "--out", out / "title.wav"]
        if chime is not None:
            audio += ["--chime", chime, "--target-lufs", target_lufs]
        run(audio, commands, cwd=out)
        run([python, tools / "mux_segment.py", "--picture", out / "title-picture.mp4",
             "--mix", out / "title.wav", "--out", out / "title.mp4"], commands, cwd=out)
        result.update(status="verified", output=record(out / "title.mp4"),
                      render_record=read_json(out / "title-picture.mp4.render-record.json"))
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        receipt(out, result)
    return result


def seam_luma(video, seam, total, commands, *, ffmpeg="ffmpeg", radius=3):
    """Measure full-range luma so TV white (235) cannot evade a >=250 white gate."""
    start, end = max(0, seam - radius), min(total - 1, seam + radius)
    # Convert *range*, not image size; retain all pixels and min/max statistics.
    argv = [ffmpeg, "-v", "info", "-i", video, "-vf",
            f"select='between(n,{start},{end})',scale=in_range=auto:out_range=full,"
            "format=yuv444p,signalstats,metadata=print", "-fps_mode", "passthrough", "-f", "null", "-"]
    stderr = run(argv, commands, stderr=True)
    return _luma_rows(stderr, start, end, seam)


def _luma_rows(text, start, end, seam):
    # Only YMIN/YAVG/YMAX; average alone can classify a mostly-white graphic as pure white.
    mins = [float(x) for x in re.findall(r"lavfi.signalstats.YMIN=([\d.]+)", text)]
    avgs = [float(x) for x in re.findall(r"lavfi.signalstats.YAVG=([\d.]+)", text)]
    maxs = [float(x) for x in re.findall(r"lavfi.signalstats.YMAX=([\d.]+)", text)]
    if not (len(mins) == len(avgs) == len(maxs) == end - start + 1):
        raise Refused("seam luma frame count missing; cannot verify seam")
    rows = [{"frame": start + i, "ymin": lo, "yavg": avg, "ymax": hi}
            for i, (lo, avg, hi) in enumerate(zip(mins, avgs, maxs))]
    white = [r["frame"] for r in rows if r["ymin"] >= 250]
    return {"seam": seam, "range": [start, end], "range_conversion": "full", "frames": rows,
            "pure_white_frames": white, "no_pure_white": not white}


def join(ctx, out, *, intro=None, title_file=None, film=None, python=sys.executable):
    cfg = block(ctx, "brand")
    inputs = [Path(override).resolve() if override else path(ctx, need(cfg, key, "brand")) for override, key in
              ((intro, "intro"), (title_file, "title"), (film, "film"))]
    tool = path(ctx, need(cfg, "kit", "brand")) / "tools" / "join_intro_v001.py"
    commands = []
    described = [probe(p, commands) for p in inputs]
    if any(p["fps"] != "30" or p["audio_streams"] != 1 for p in described):
        raise Refused("configured join kit requires 30 fps and one audio stream on all segments")
    out = fresh(out)
    result = {"schema": "jjv/brand-join/v1", "binding": ctx["binding"], "tool": record(tool),
              "inputs": [record(p) for p in inputs], "commands": commands, "status": "failed"}
    try:
        run([python, tool, "--intro", inputs[0], "--title", inputs[1], "--film", inputs[2],
             "--outdir", out, "--name", "branded-film", "--label", "CANDIDATE"], commands, cwd=out)
        legacy = read_json(out / "branded-film.JOIN-RECEIPT.json")
        output = out / "branded-film.mp4"
        used = [Path(p) for p in legacy["concat_order"]]
        expected = []
        for i, source in enumerate(used):
            expected.extend(frame_md5(source, out / f"segment-{i}.framemd5", commands))
        actual = frame_md5(output, out / "joined.framemd5", commands)
        seam = sum(legacy["segment_frames"][:-1])
        luma = seam_luma(output, seam, len(actual), commands)
        checks = {"legacy_verified": legacy["pass"] is True, "all_frames_equal": actual == expected,
                  "no_pure_white_at_title_film": luma["no_pure_white"],
                  "inputs_unchanged": [record(p) for p in inputs] == result["inputs"]}
        result.update(output=record(output), checks=checks, seam_luma=luma,
                      frame_proof={"expected": len(expected), "actual": len(actual),
                                   "files": [record(p) for p in sorted(out.glob("*.framemd5"))]},
                      legacy_receipt=record(out / "branded-film.JOIN-RECEIPT.json"))
        if not all(checks.values()):
            raise Refused(f"brand join verification failed: {checks}")
        result["status"] = "verified"
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        receipt(out, result)
    return result
