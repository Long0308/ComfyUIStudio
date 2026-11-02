"""Constants and the ComfyUI-style pack loader shared by the pack tests and the simulation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

SECRET_TOKEN = "tok-SECRET-do-not-leak-0123456789"
PACK_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "jj_claude_bridge_pack"


def load_pack() -> Any:
    """Import the pack as a package from its folder, exactly as ComfyUI does."""
    existing = sys.modules.get(PACKAGE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        PACK_DIR / "__init__.py",
        submodule_search_locations=[str(PACK_DIR)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module
