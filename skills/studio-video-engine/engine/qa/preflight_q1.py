"""Preflight Q1: the existing word-timing gate (``timing.gate.check_document``) on the timing the config was built from.

The detector, thresholds and the built-in negative control are the ones of ``jjv qa words``; nothing is
re-implemented here.  Extra preflight rule: the timing file must be the one the config declares
(``word_timing.sha256``), otherwise the config was built from another timing and a PASS proves nothing.
UNTESTABLE (no word follows a pause) is UNCERTAIN, never PASS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file
from .gates import FAIL, PASS, UNCERTAIN
from .preflight_segments import resolve


def _declared_block(config: dict) -> dict:
    block = config.get("word_timing")
    return block if isinstance(block, dict) else {}


def timing_path_of(config: dict, explicit: Path | None, root: Path) -> tuple[Path | None, str]:
    if explicit is not None:
        return Path(explicit), "--timing"
    path = resolve(_declared_block(config).get("path"), root)
    return (path, "config.word_timing.path") if path else (None, "none")


def run(config: dict, root: Path, timing: Path | None, source: str, recipe: Any, fps: float, allow: tuple = ()) -> dict:
    if timing is None:
        return {"gate": "Q1", "status": UNCERTAIN, "failures": ["no word timing: pass --timing (the config declares none)"]}
    try:
        from ..timing import gate  # noqa: PLC0415 - the detector imports numpy; a missing one is Uncertain
    except ImportError as error:
        raise Uncertain(f"Q1 needs numpy: {error}") from error
    if not Path(timing).is_file():
        raise Uncertain(f"word timing not found: {timing}")
    document = read_json(Path(timing))
    if not isinstance(document, dict):
        raise Refused(f"{Path(timing).name}: word timing must be a JSON object")
    failures: list[str] = []
    declared, actual = _declared_block(config).get("sha256"), sha256_file(Path(timing))
    binding = {"declared_sha256": declared, "actual_sha256": actual, "match": declared in (None, actual)}
    if declared not in (None, actual):
        failures.append(f"the timing {Path(timing).name} ({actual[:12]}) is not the one the config was built from "
                        f"({str(declared)[:12]}): rebuild the config or pass the right timing")
    result, _bound = gate.check_document(document, root, recipe.block("q1"), fps, allow)
    summary, control = result["summary"], result["negative_control"]
    failures += [f"word {w} lights before its audible onset" for w in summary["early_words"]]
    failures += [f"word {w} lights too late" for w in summary["late_words"]]
    if result["verdict"] == "FAIL" and not (summary["early"] or summary["late"]):
        failures.append("the negative control (a word shifted early) was not detected: the gate proves nothing here")
    status = FAIL if failures or result["verdict"] == "FAIL" else PASS
    if result["verdict"] == "UNTESTABLE":
        failures.append("Q1 has nothing to test: no word follows a pause in this timing")
        status = FAIL if status == FAIL else UNCERTAIN
    return {"gate": "Q1", "status": status, "failures": failures, "verdict": result["verdict"],
            "timing": {"name": Path(timing).name, "sha256": actual, "source": source}, "binding": binding,
            "summary": summary, "negative_control": {k: control.get(k) for k in ("status", "detected", "controls")},
            "recipe": {"id": recipe.recipe_id, "sha256": recipe.sha256}}
