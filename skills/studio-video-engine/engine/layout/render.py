"""``jjv layout render``: headless Blender guide + control passes for one shot, with a receipt.

Beauty (Workbench) opens a GPU context, so it is taken only under the machine-wide GPU lock and after a free-VRAM
check (a refusal sends nothing to Blender). depth/mask are CPU ray casts and need neither. The script that runs is
``scene_layout.py emit-bpy`` output (validated, so an invalid brief is refused) plus the passes template appended.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from ..comfy.lock import existence_lock
from ..core.errors import Failed, Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from . import tool

PASSES = ("beauty", "depth", "mask")
PLACEHOLDER = '"__PASS_CONFIG_JSON_PLACEHOLDER__"'
Runner = Callable[..., "subprocess.CompletedProcess[str]"]
VramProbe = Callable[[], "int | None"]


def parse_passes(text: str) -> list[str]:
    wanted = [p.strip() for p in text.split(",") if p.strip()]
    bad = [p for p in wanted if p not in PASSES]
    if bad or not wanted:
        raise Refused(f"--passes takes a comma list of {PASSES}; got {text!r}")
    return list(dict.fromkeys(wanted))


def find_blender(explicit: str | None, machine: dict[str, Any] | None = None) -> str:
    """Explicit path, ``machine.tools.blender_exe``, ``$BLENDER`` or PATH; no machine-specific default."""
    configured = ((machine or {}).get("tools") or {}).get("blender_exe")
    for candidate in (explicit, configured, os.environ.get("BLENDER"), shutil.which("blender")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise Refused("Blender not found (pass --blender, set BLENDER or machine.tools.blender_exe); nothing was run")


def nvidia_free_mib() -> int | None:
    """Free VRAM of the first GPU in MiB, or None when it cannot be read (then the GPU path is refused)."""
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=30, check=False)
        return int(done.stdout.strip().splitlines()[0]) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def next_take(root: Path) -> str:
    taken = [int(p.name[1:]) for p in Path(root).glob("r[0-9][0-9][0-9]") if p.is_dir()] if Path(root).is_dir() else []
    return f"r{max(taken, default=0) + 1:03d}"


def compose_script(brief: Path, passes: list[str], out_dir: Path, basename: str, far_m: float) -> str:
    """Emitted blockout script + passes code (validated first: an invalid brief is never emitted)."""
    with tempfile.TemporaryDirectory(prefix="jjv-emit-") as scratch:  # never write next to the (read-only) brief
        emitted = Path(scratch) / "emit.py"
        done = tool.scene_layout("emit-bpy", str(brief), str(emitted))
        if done.returncode != 0:
            raise Refused(f"scene_layout emit-bpy refused the brief: {(done.stderr or done.stdout).strip()[:400]}")
        base_text = emitted.read_text(encoding="utf-8")
    template = tool.PASSES_TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise Refused(f"passes template placeholder missing in {tool.PASSES_TEMPLATE}")
    config = {"passes": [p for p in passes if p != "beauty"], "out_dir": str(out_dir), "basename": basename, "far_m": far_m}
    return base_text.rstrip("\n") + "\n\n" + template.replace(PLACEHOLDER, repr(json.dumps(config)))


def render_shot(brief: Path, shot: str, out_root: Path, passes: list[str], *, blender: str, machine: dict[str, Any],
                take: str | None = None, width: int | None = None, height: int | None = None,
                allow_draft: bool = False, runner: Runner = subprocess.run, vram_free: VramProbe = nvidia_free_mib,
                recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    from .context import ROUTES_RECIPE, load_recipe

    brief, out_root = Path(brief), Path(out_root)
    policy = (recipe or load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0])["layout"]["render"]
    document = read_json(brief)
    if document.get("status") == "draft" and not allow_draft:
        raise Refused(f"brief {brief.name} has status 'draft': fill it in (or pass --allow-draft); nothing was run")
    code, parsed, _ = tool.scene_layout_json("validate", str(brief))
    if code != 0:
        errors = [f"{f['code']}: {f['message']}" for f in (parsed or {}).get("findings", []) if f.get("level") == "error"]
        raise Refused(f"brief {brief.name} is invalid: {errors[:5]}")
    pins = tool.tool_pins()
    take = take or next_take(out_root / "render" / shot)
    out_dir = out_root / "render" / shot / take
    if out_dir.exists():
        raise Refused(f"render take {out_dir} already exists; use a new --take (renders are never overwritten)")
    basename = (document.get("output") or {}).get("basename") or document["brief_id"]
    script = compose_script(brief, passes, out_dir, basename, far_m=500.0)
    gpu = "beauty" in passes
    probe: dict[str, Any] = {"gpu_used": gpu, "min_free_vram_mib": policy["min_free_vram_mib"], "free_vram_mib": None}
    argv = [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", "<script>", "--",
            "--out-dir", str(out_dir)]
    if width and height:
        argv += ["--width", str(width), "--height", str(height)]
    if not gpu:
        argv.append("--no-render")
    lock = Path(machine["gpu_lock_path"]) if gpu else None
    started = time.monotonic()
    out_dir.mkdir(parents=True)
    script_path = out_dir / "scene-and-passes.bpy.py"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    argv[argv.index("<script>")] = str(script_path)
    try:
        completed = _run_blender(argv, lock, probe, policy, runner, vram_free)
    except Refused:
        shutil.rmtree(out_dir, ignore_errors=True)  # nothing ran: leave no half take behind
        raise
    elapsed = round(time.monotonic() - started, 3)
    return _receipt(out_root, shot, take, brief, out_dir, basename, passes, pins, probe, completed, elapsed, script_path)


def _run_blender(argv: list[str], lock: Path | None, probe: dict, policy: dict, runner: Runner,
                 vram_free: VramProbe) -> "subprocess.CompletedProcess[str]":
    def run() -> "subprocess.CompletedProcess[str]":
        try:
            return runner(argv, capture_output=True, text=True, timeout=policy["timeout_seconds"], check=False)
        except subprocess.TimeoutExpired as error:
            raise Uncertain(f"Blender exceeded {policy['timeout_seconds']} s and was stopped; the take folder is kept "
                            "for inspection", evidence={"argv": argv[:3]}) from error
        except OSError as error:
            raise Uncertain(f"cannot start Blender: {error!r}") from error

    if lock is None:
        return run()
    with existence_lock(lock, timeout_seconds=policy["lock_timeout_seconds"]) as handle:
        free = vram_free()
        probe.update(free_vram_mib=free, lock=str(lock), lock_token_pid=handle.pid)
        if free is None:
            raise Refused("free VRAM could not be read (nvidia-smi); the beauty pass opens a GPU context, so it is "
                          "refused. Use --passes depth,mask for the CPU-only passes")
        if free < policy["min_free_vram_mib"]:
            raise Refused(f"only {free} MiB VRAM free, beauty needs {policy['min_free_vram_mib']} MiB; another GPU job "
                          "is running. Use --passes depth,mask or wait")
        return run()


def _receipt(out_root: Path, shot: str, take: str, brief: Path, out_dir: Path, basename: str, passes: list[str],
             pins: dict, probe: dict, completed: "subprocess.CompletedProcess[str]", elapsed: float,
             script_path: Path) -> dict[str, Any]:
    files = sorted(p for p in out_dir.iterdir() if p.is_file() and p.name != "render-receipt.json")
    listing = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files]
    tail = (completed.stdout or "")[-600:]
    status = "rendered" if completed.returncode == 0 else ("assertion_failed" if completed.returncode == 3 else "failed")
    beauty = out_dir / f"{basename}-guide.png"
    receipt = {"schema": "jjv/layout-render/v1", "shot": shot, "take": take, "status": status,
               "exit_code": completed.returncode, "passes": passes, "brief": {"path": brief.as_posix(),
               "sha256": sha256_file(brief)}, "tool": pins, "gpu": probe, "elapsed_seconds": elapsed,
               "beauty": {"name": beauty.name, "sha256": sha256_file(beauty)} if beauty.is_file() else None,
               "files": listing, "script": script_path.name, "stdout_tail": tail,
               "stderr_tail": (completed.stderr or "")[-400:], "note": "guide geometry only; not an accepted frame"}
    write_json_once(out_dir / "render-receipt.json", receipt, mode="ascii", stamp=True)
    if completed.returncode != 0:
        cls = Failed if completed.returncode == 3 else Uncertain
        raise cls(f"Blender exit {completed.returncode}: {(completed.stderr or completed.stdout)[-300:]}",
                  evidence={"receipt": str(out_dir / "render-receipt.json")})
    receipt["receipt"] = str(out_dir / "render-receipt.json")
    return receipt


def latest_beauty(layout_dir: Path, shot: str) -> tuple[Path, str] | None:
    """The newest successful render's beauty guide of ``shot``: ``(png, sha256)`` from its receipt, or None."""
    for folder in sorted((Path(layout_dir) / "render" / shot).glob("r[0-9][0-9][0-9]"), reverse=True):
        receipt = folder / "render-receipt.json"
        if receipt.is_file():
            row = read_json(receipt)
            if row.get("status") == "rendered" and row.get("beauty"):
                png = folder / row["beauty"]["name"]
                if png.is_file() and sha256_file(png) == row["beauty"]["sha256"]:
                    return png, row["beauty"]["sha256"]
    return None
