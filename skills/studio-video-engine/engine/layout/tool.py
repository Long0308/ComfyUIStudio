"""Run the shared comfyui-blender CLI as a subprocess (``python -I``) and pin it by sha256."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from ..core.winflags import no_window

SCRIPTS_DIR = SKILL_ROOT.parent / "comfyui-blender" / "scripts"
SCENE_LAYOUT = SCRIPTS_DIR / "scene_layout.py"
SCHEMA = SCRIPTS_DIR.parent / "assets" / "scene-layout.schema.json"
BASE_TEMPLATE = SCRIPTS_DIR / "bpy_layout_template.py"
PASSES_TEMPLATE = SCRIPTS_DIR / "bpy_layout_passes_template.py"


def tool_pins() -> dict[str, str]:
    """sha256 of every file of the shared tool the layout stage depends on (recorded in receipts)."""
    files = {"scene_layout.py": SCENE_LAYOUT, "scene-layout.schema.json": SCHEMA,
             "bpy_layout_template.py": BASE_TEMPLATE, "bpy_layout_passes_template.py": PASSES_TEMPLATE}
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise Refused(f"shared comfyui-blender tool is incomplete, missing {missing} under {SCRIPTS_DIR}")
    return {name: sha256_file(path) for name, path in files.items()}


def scene_layout(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    """``scene_layout.py <args>``: stdlib only, no Blender, no GPU."""
    try:
        return subprocess.run([sys.executable, "-I", str(SCENE_LAYOUT), *args], capture_output=True, text=True,
                              timeout=timeout, check=False, creationflags=no_window())
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run scene_layout.py: {error!r}") from error


def scene_layout_json(*args: str) -> tuple[int, Any, str]:
    """``(exit code, parsed stdout JSON or None, stderr)`` for a verb that takes ``--json``."""
    done = scene_layout(*args, "--json")
    try:
        parsed = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        parsed = None
    return done.returncode, parsed, done.stderr.strip()
