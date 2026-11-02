"""M9a item e: every receipt / run report the engine writes (in the packages M9a owns) carries ``engine_tree_sha256``.

An AST scan, not a behaviour test of each writer: a JSON written through ``write_json_once`` / ``write_json_atomic`` must pass
``stamp=True`` (or its function stamps the dict with ``provenance.stamp`` so the printed report equals the file).  The
only exceptions are listed here WITH the reason: artefacts whose bytes must not depend on the engine version.

STAMP-2: a JSON written through the RAW writers (``write_atomic`` / ``write_once`` with a ``pretty_json(...)`` payload,
inline or bound to a local name in the same function) is held to the same rule; ``boundaries.current.json`` was such a
receipt and went unstamped because the first scan only looked at ``write_json_*``.  Still invisible (documented, not
guessed away): a payload built by ``json.dumps`` or passed in as a parameter (``write_version(folder, prefix, payload)``),
and a writer reached through an alias the scan does not know.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from engine.core import provenance
from engine.core.io import write_json_atomic, write_json_once

SKILL = Path(__file__).resolve().parents[1]
PACKAGES = ("audio", "qa", "editorial", "config", "plan", "voice", "timing", "deliver", "publish", "run")
WRITERS = ("write_json_once", "write_json_atomic")
NOT_RECEIPTS = {  # (file, first-argument source) -> why it is an artefact and not a receipt
    ("engine/audio/cli.py", "out / music.PLAN_FILE"): "plan document: deterministic, its sha is bound by later steps",
    ("engine/audio/cli.py", "out / sfx.PLAN_FILE"): "plan document: deterministic, its sha is bound by later steps",
    ("engine/audio/musicpick_cli.py", "out / music.PLAN_FILE"): "plan document: deterministic, its sha is bound by later steps",
    ("engine/audio/guiwrite.py", "gui_path"): "editable review GUI input (artefact)",
    ("engine/audio/guiwrite.py", "review_path"): "editable review document (artefact)",
    # 2026-10-28 (boundaries.current receipt change): presets_swap.py and boundaries_write.py no longer call
    # write_json_* for boundaries.json / versions/boundaries-vNNN.json; both go through
    # editorial/boundaries_current.write_version + publish (raw write_once / write_atomic), so their four exemptions
    # were removed as stale.  The artefact decision (boundaries tables are not stamped) is unchanged.
    ("engine/voice/cli.py", "out / receipts.PLAN_FILE"): "voice plan document: deterministic, its sha is bound by finalize (plan_sha256) and voice bindings",
    ("engine/voice/voice_bindings.py", "path"): "voice-bindings.json: derived input document read by timing, h3 and mix; deterministic from plan + finalize, not evidence of a run",
    ("engine/timing/run.py", "out / TIMING_FILE"): "timing.json: word-timing document read by renderers; deterministic from dialogue + recipe, its sha is bound by qa and the receipt",
    ("engine/deliver/brand.py", "out / 'title-job.json'"): "render input for render_title.cjs (job spec, not evidence of a run)",
    ("engine/run/ledger.py", "path"): "per-stage reuse ledger: mutable state (the latest successful run wins); the stamped run.json is the record",
    ("engine/run/ledger.py", "entry_path(ledger_dir, stage_id)"): "same ledger entry, status flipped to complete on reuse (mutable state)",
    ("engine/run/explain.py", "target / DESCRIPTOR"): "plan-inputs descriptor of an explain snapshot: input of `jjv plan explain`, not evidence of a run",
}


def _trees() -> list[tuple[Path, ast.Module]]:
    trees = []
    for package in PACKAGES:
        for path in sorted((SKILL / "engine" / package).rglob("*.py")):
            trees.append((path, ast.parse(path.read_text("utf-8"))))
    return trees


def _unstamped() -> list[str]:
    found = []
    for path, tree in _trees():
        for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            stamps = any(isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", None)) == "stamp"
                         for c in ast.walk(func))
            for call in [n for n in ast.walk(func) if isinstance(n, ast.Call)]:
                if getattr(call.func, "attr", getattr(call.func, "id", None)) not in WRITERS:
                    continue
                flagged = any(k.arg == "stamp" and getattr(k.value, "value", None) is True for k in call.keywords)
                relative = path.relative_to(SKILL).as_posix()
                if not (flagged or stamps or (relative, ast.unparse(call.args[0])) in NOT_RECEIPTS):
                    found.append(f"{relative}:{call.lineno} {ast.unparse(call.args[0])}")
    return sorted(set(found))


def _passed_not_called() -> list[str]:
    """A writer passed as a value (``_once(..., write_json_once, ...)``) is invisible to the call scan: refuse it."""
    found = []
    for path, tree in _trees():
        called = {id(c.func) for c in ast.walk(tree) if isinstance(c, ast.Call)}
        for node in ast.walk(tree):
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if name in WRITERS and id(node) not in called:
                found.append(f"{path.relative_to(SKILL).as_posix()}:{node.lineno} {name} passed as a value")
    return sorted(set(found))


RAW_WRITERS = ("write_atomic", "write_once")
RAW_NOT_RECEIPTS = {  # (file, first-argument source) -> why a raw pretty_json write is an artefact and not a receipt
    ("engine/audio/library.py", "path"): "music-bed REGISTRY.json: edited library document (revision + backup), not evidence of a run",
    ("engine/config/cli.py", "delivery"): "DELIVERY-CONTRACT.json rendered from episode.json: config document read by later stages",
    ("engine/config/cli.py", "episode_file"): "episode.json: the episode config document itself",
    ("engine/editorial/boundaries_current.py", "out / 'boundaries.json'"): "boundaries.json: the table its stamped receipt binds by sha256",
    ("engine/editorial/boundaries_suggest_cli.py", "target"): "boundaries-suggested.json: write-once input document for `boundaries write --suggested`",
    ("engine/editorial/episode_text_cli.py", "target"): "episode text document read by renderers (write-once artefact)",
    ("engine/editorial/icons.py", "version_file"): "icons registry version (write-once artefact; carries its own content sha256)",
    ("engine/editorial/icons.py", "current"): "icons.json: current icons registry, byte-identical to its version file",
}


def _is_pretty_json(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "pretty_json"


def _calls_stamp(node: ast.AST) -> bool:
    return any(isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", None)) == "stamp"
               for c in ast.walk(node))


def _raw_unstamped(relative: str, tree: ast.Module) -> list[tuple[str, int, str]]:
    """``(file, line, first argument)`` of every raw JSON write in ``tree`` that does not stamp and is not exempt."""
    found = []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        bound = {t.id: node.value for node in ast.walk(func) if isinstance(node, ast.Assign)
                 for t in node.targets if isinstance(t, ast.Name)}
        for call in [n for n in ast.walk(func) if isinstance(n, ast.Call)]:
            if getattr(call.func, "attr", getattr(call.func, "id", None)) not in RAW_WRITERS or len(call.args) < 2:
                continue
            payload = call.args[1]
            payload = bound.get(payload.id, payload) if isinstance(payload, ast.Name) else payload
            if not _is_pretty_json(payload) or _calls_stamp(func):
                continue
            found.append((relative, call.lineno, ast.unparse(call.args[0])))
    return found


def _raw_sites() -> list[tuple[str, int, str]]:
    return [site for path, tree in _trees() for site in _raw_unstamped(path.relative_to(SKILL).as_posix(), tree)]


def test_every_raw_json_write_is_stamped_or_a_listed_artefact() -> None:
    assert sorted(f"{f}:{line} {arg}" for f, line, arg in _raw_sites() if (f, arg) not in RAW_NOT_RECEIPTS) == []


def test_the_raw_exception_list_has_no_stale_entry() -> None:
    assert set(RAW_NOT_RECEIPTS) <= {(f, arg) for f, _, arg in _raw_sites()}


def test_the_raw_scan_catches_the_pre_stamp2_receipt_write() -> None:
    """The exact shape that left boundaries.current.json unstamped (pre-STAMP-2 boundaries_current.publish)."""
    before = ast.parse(
        "def publish(out, document, *, version, version_path, writer):\n"
        "    payload = pretty_json(document, mode='utf8')\n"
        "    digest = write_atomic(out / 'boundaries.json', payload)\n"
        "    receipt = {'schema': RECEIPT_SCHEMA, 'version': version, 'sha256': digest}\n"
        "    write_atomic(out / RECEIPT_NAME, pretty_json(receipt, mode='utf8'))\n")
    flagged = {arg for _, _, arg in _raw_unstamped("engine/editorial/boundaries_current.py", before)}
    assert flagged == {"out / 'boundaries.json'", "out / RECEIPT_NAME"}
    exempt = {("engine/editorial/boundaries_current.py", arg) in RAW_NOT_RECEIPTS for arg in flagged}
    assert exempt == {True, False}   # the table is an artefact; the receipt line is what the gate reports


def test_every_receipt_writer_stamps_the_engine_tree() -> None:
    assert _unstamped() == []


def test_writers_are_called_directly_so_the_scan_sees_them() -> None:
    assert _passed_not_called() == []


def test_the_exception_list_has_no_stale_entry() -> None:
    used = set()
    for path, tree in _trees():
        for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
            if getattr(call.func, "attr", getattr(call.func, "id", None)) in WRITERS and call.args:
                used.add((path.relative_to(SKILL).as_posix(), ast.unparse(call.args[0])))
    assert set(NOT_RECEIPTS) <= used


def test_stamp_true_writes_the_header_and_the_default_does_not(tmp_path: Path) -> None:
    write_json_once(tmp_path / "a.json", {"x": 1}, mode="ascii", stamp=True)
    write_json_atomic(tmp_path / "b.json", {"x": 1}, mode="ascii")
    assert json.loads((tmp_path / "a.json").read_text())["engine_tree_sha256"] == provenance.engine_tree_sha256()["engine_tree_sha256"]
    assert "engine_tree_sha256" not in json.loads((tmp_path / "b.json").read_text())
