"""Small delivery context and media helpers. No render-service calls."""
from __future__ import annotations

import json
import subprocess
import time
from fractions import Fraction
from pathlib import Path

from ..config.loader import REPO_ROOT, SKILL_ROOT, find_episode_file
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from .guard import contained_write


def load_context(episode, *, delivery_config=None, repo_root=REPO_ROOT, skill_root=SKILL_ROOT):
    """Read delivery inputs only; restoration/voice recipes are not delivery dependencies.

    Without ``delivery_config`` only the canonical sidecar is accepted; a non-canonical one must be named explicitly.
    """
    ep_file = find_episode_file(str(episode), Path(repo_root)).resolve()
    ep = read_json(ep_file)
    domain = read_json(Path(skill_root) / "domains" / f"{ep['domain']}.json")
    config_file = Path(delivery_config).resolve() if delivery_config else ep_file.parent / "delivery.json"
    cfg = read_json(config_file)
    if (cfg.get("schema") != "jjv/delivery-config/v1" or cfg.get("episode_id") != ep["episode_id"]
            or cfg.get("domain") != ep["domain"] or domain.get("domain_id") != ep["domain"]):
        raise Refused("delivery config schema, episode or domain mismatch")
    if delivery_config is None and cfg.get("canonical") is not True:
        raise Refused(f"delivery config {config_file} is not canonical; pass --delivery-config explicitly to use it")
    return {"episode": ep, "domain": domain, "base": config_file.parent, "repo_root": Path(repo_root).resolve(),
            "config": cfg, "episode_root": ep_file.parent.parent,
            "binding": {"episode_sha256": sha256_file(ep_file),
                        "delivery_config_sha256": sha256_file(config_file),
                        "domain_sha256": sha256_file(Path(skill_root) / "domains" / f"{ep['domain']}.json")}}


def path(ctx, value):
    """Read-side path from a sidecar value (resolved; never used for a write target)."""
    return (ctx["base"] / value).resolve()


def write_path(ctx, value, root, label):
    """Write-side path from a sidecar value: lexically joined, contained in ``root``, no reparse points."""
    if not isinstance(value, str) or not value:
        raise Refused(f"{label} must be a non-empty path string")
    return contained_write(Path(ctx["base"]) / value, root, label)


def unresolved_name(value):
    """Name of an unresolved sidecar value (``{"missing": "MISSING_..."}``), else None."""
    if isinstance(value, dict) and set(value) == {"missing"} and isinstance(value["missing"], str):
        return value["missing"]
    return None


def optional(cfg, key, default=None):
    """An optional value of a block: absent or empty gives ``default``; an unresolved marker refuses by name."""
    value = cfg.get(key)
    if value is None or value == "":
        return default
    name = unresolved_name(value)
    if name:
        raise Refused(name)
    return value


def block(ctx, name):
    """The named sidecar block; refuses clearly instead of KeyError when absent or unresolved."""
    value = ctx["config"].get(name)
    if value is None:
        raise Refused(f"delivery.json has no {name} block; add it with `jjv deliver init` or by hand")
    if unresolved_name(value):
        raise Refused(unresolved_name(value))
    if not isinstance(value, dict):
        raise Refused(f"delivery.json {name} block must be an object")
    return value


def need(cfg, key, label):
    """A required value of a block: refuses with the MISSING_* name, a clear message, or never a literal."""
    if not isinstance(cfg, dict) or key not in cfg:
        raise Refused(f"delivery.json {label}.{key} is missing")
    value = cfg[key]
    if unresolved_name(value):
        raise Refused(unresolved_name(value))
    if value in (None, "", []):
        raise Refused(f"delivery.json {label}.{key} is empty")
    return value


def fresh(directory):
    directory = Path(directory).resolve()
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise Refused(f"output directory already exists: {directory}; choose a new version") from exc
    return directory


def record(file):
    file = Path(file)
    return {"path": str(file.resolve()), "sha256": sha256_file(file)}


def run(argv, commands, *, cwd=None, timeout=3600, stderr=False):
    start = time.monotonic()
    try:
        result = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        commands.append({"argv": [str(x) for x in argv], "exit_code": None,
                         "seconds": round(time.monotonic() - start, 3), "timed_out": True})
        raise Refused(f"command timed out after {timeout}s: {argv[0]}") from exc
    commands.append({"argv": [str(x) for x in argv], "exit_code": result.returncode,
                     "seconds": round(time.monotonic() - start, 3),
                     "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]})
    if result.returncode:
        raise Refused(f"command exited {result.returncode}: {argv[0]}: {result.stderr[-1500:]}")
    return result.stderr if stderr else result.stdout


def probe(file, commands, ffprobe="ffprobe"):
    data = json.loads(run([ffprobe, "-v", "error", "-count_frames", "-show_streams",
                           "-of", "json", file], commands))
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    return {"width": video["width"], "height": video["height"],
            "frames": int(video["nb_read_frames"]), "fps": str(Fraction(video["avg_frame_rate"])),
            "audio_streams": len(audio)}


def audio_md5(file, commands, ffmpeg="ffmpeg", *, decoded=False):
    codec = "pcm_s16le" if decoded else "copy"
    return run([ffmpeg, "-v", "error", "-i", file, "-map", "0:a:0", "-c:a", codec,
                "-f", "md5", "-"], commands).strip()


def frame_md5(file, output, commands, ffmpeg="ffmpeg"):
    run([ffmpeg, "-n", "-v", "error", "-i", file, "-map", "0:v:0",
         "-fps_mode", "passthrough", "-f", "framemd5", output], commands)
    return [line.split(",")[-1].strip() for line in Path(output).read_text().splitlines()
            if line and not line.startswith("#")]


def receipt(out, value):
    write_json_once(Path(out) / "receipt.json", value, mode="utf8", stamp=True)
