"""Regression for admitting one queued job behind a running ComfyUI prompt."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from engine.core.errors import Refused


def test_submit_allows_one_running_prompt_but_no_pending_prompt() -> None:
    queue_path = Path(__file__).resolve().parents[1] / "engine" / "comfy" / "queue.py"
    spec = importlib.util.spec_from_file_location("engine.comfy._staged_queue", queue_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    running = {"queue_running": [[1, "first", {}, {}, []]], "queue_pending": []}
    module.require_idle(running)
    with pytest.raises(Refused, match="busy"):
        module.require_idle(running, strict_idle=True)

    waiting = {"queue_running": running["queue_running"],
               "queue_pending": [[2, "second", {}, {}, []]]}
    with pytest.raises(Refused, match="busy"):
        module.require_idle(waiting)
