"""Reuse the comfyui-blender scene API with an injectable, pinned tool path."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ..core.errors import Refused
from ..core.io import sha256_file
from ..core.winflags import no_window
from ..layout.tool import SCENE_LAYOUT


def pins(tool: Path | None) -> dict:
    path = Path(tool or SCENE_LAYOUT)
    names = ['scene_layout.py', 'scene_continuity.py', 'scene_placement.py', 'scene_common.py', 'scene_set.py', 'scene_track.py']
    files = [path.parent / n for n in names] + [path.parent.parent / 'assets/scene-layout.schema.json']
    if any(not p.is_file() for p in files):
        raise Refused('shared scene API incomplete; supply --scene-tool <scene_layout.py>')
    return {p.name: sha256_file(p) for p in files}


def call(tool: Path | None, *args: str) -> dict:
    path = Path(tool or SCENE_LAYOUT)
    try:
        done = subprocess.run([sys.executable, '-I', '-B', str(path), *args, '--json'],
                              capture_output=True, text=True, encoding='utf-8', timeout=60, check=False, creationflags=no_window())
        doc = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise Refused(f'scene API unavailable: {error}') from error
    mismatch = (args[0] == 'continuity' and done.returncode == 1 and isinstance(doc, dict)
                and doc.get('classification') == 'MISMATCH' and not doc.get('errors'))
    if not isinstance(doc, dict) or (done.returncode and not mismatch):
        raise Refused(f'scene API refused {args[0]}: {doc}')
    return doc
