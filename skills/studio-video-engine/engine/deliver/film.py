"""Lanczos delivery downscale, with exact frame and copied-audio proofs."""
from pathlib import Path

from ..core.errors import Refused
from .common import audio_md5, fresh, probe, receipt, record, run


def film_2k(ctx, master, out, *, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    from ..policy import final_gate
    final_gate.require_final_master(ctx["domain"], master, verb="deliver film-2k")  # no-op without domain final_gate
    policy = ctx["domain"].get("delivery", {})
    spec = policy.get("film_2k", {})
    if (spec.get("width"), spec.get("height"), spec.get("method")) != (2560, 1440, "lanczos"):
        raise Refused("domain does not declare 2560x1440 lanczos film_2k delivery")
    master = Path(master).resolve()
    commands = []
    source = probe(master, commands, ffprobe)
    expected = policy["master"]
    if ((source["width"], source["height"]) != (expected["width"], expected["height"])
            or source["width"] <= 2560 or source["height"] <= 1440
            or source["fps"] != str(expected["fps"]) or source["audio_streams"] != 1):
        raise Refused(f"source must be the declared master with one audio stream: {source}")
    out = fresh(out)
    output = out / "film-2k.mp4"
    result = {"schema": "jjv/deliver-film-2k/v1", "binding": ctx["binding"],
              "input": record(master), "source": source, "commands": commands, "status": "failed"}
    try:
        run([ffmpeg, "-n", "-v", "error", "-i", master, "-map", "0:v:0", "-map", "0:a:0",
             "-vf", "scale=2560:1440:flags=lanczos", "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
             "-c:a", "copy", "-movflags", "+faststart", output], commands)
        actual = probe(output, commands, ffprobe)
        before, after = audio_md5(master, commands, ffmpeg), audio_md5(output, commands, ffmpeg)
        checks = {"dimensions": (actual["width"], actual["height"]) == (2560, 1440),
                  "frames_equal": actual["frames"] == source["frames"],
                  "fps_equal": actual["fps"] == source["fps"], "audio_stream_copy": before == after,
                  "source_unchanged": record(master) == result["input"]}
        result.update(output={**record(output), **actual}, checks=checks,
                      audio_md5={"master": before, "film_2k": after})
        if not all(checks.values()):
            raise Refused(f"2K verification failed: {checks}")
        result["status"] = "verified"
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        receipt(out, result)
    return result
