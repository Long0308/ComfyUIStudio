"""``jjv bridge library-stage``: stage each character's CURRENT library images for the step UI (domain-neutral, config-driven).

``<state>/config.json`` key ``characters`` maps a domain id to::

    {"library_root": "<abs folder holding CHAR_xx/FACE|ACTION/*.png>", "bible": "<abs characters bible .json>",
     "stage_subdir": "characters", "ui_data": "<abs folder for the JSON>", "kinds": ["FACE", "ACTION"],
     "qa_ledger": "<optional abs .json: {sha256: verdict} or {\"verdicts\": {sha256: verdict}}>"}

Only the PNGs directly inside ``<library_root>/<CHAR>/<KIND>/`` are current takes (``*_rejected`` folders are never read).
Files are COPIED write-once to ``<ComfyUI input>/<stage_subdir>/<CHAR>/<sha12>_<name>.png``.  ``qa`` is the ledger's verdict
for that sha256 or ``null``: a verdict is never invented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.settings import settings_from_machine
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_atomic, write_once
from .wardrobe import safe_name

SCHEMA = "jjv/character-refs/v1"


def _block(config: dict[str, Any] | None, domain_id: str) -> dict[str, Any]:
    block = (config or {}).get(domain_id)
    if not isinstance(block, dict):
        raise Refused(f"config.json has no characters block for domain {domain_id!r}")
    for key in ("library_root", "ui_data"):
        if not isinstance(block.get(key), str):
            raise Refused(f"config.json characters[{domain_id!r}] needs {key!r} (absolute path)")
    return block


def _names(block: dict[str, Any]) -> dict[str, str]:
    if not isinstance(block.get("bible"), str):
        return {}
    bible = read_json(Path(block["bible"]))
    rows = bible.get("characters") if isinstance(bible, dict) else None
    return {str(r["id"]): r.get("name") for r in rows or [] if isinstance(r, dict) and "id" in r}


def _verdicts(block: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(block.get("qa_ledger"), str) or not Path(block["qa_ledger"]).is_file():
        return {}
    ledger = read_json(Path(block["qa_ledger"]))
    inner = ledger.get("verdicts") if isinstance(ledger, dict) else None
    return inner if isinstance(inner, dict) else (ledger if isinstance(ledger, dict) else {})


def stage(config: dict[str, Any] | None, domain_id: str, machine_path: Path) -> dict[str, Any]:
    block = _block(config, domain_id)
    root = Path(block["library_root"])
    if not root.is_dir():
        raise Refused(f"library_root not found: {root}")
    input_dir = settings_from_machine(read_json(machine_path)).input_dir
    subdir, kinds = str(block.get("stage_subdir") or "characters"), [str(k) for k in block.get("kinds") or ["FACE", "ACTION"]]
    names, verdicts = _names(block), _verdicts(block)
    characters: dict[str, Any] = {}
    counts: dict[str, dict[str, int]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("CHAR_")):
        entry: dict[str, Any] = {"name": names.get(folder.name)}
        for kind in kinds:
            rows = []
            for png in sorted((folder / kind).glob("*.png")) if (folder / kind).is_dir() else []:
                digest = sha256_file(png)
                relpath = f"{subdir}/{folder.name}/{digest[:12]}_{safe_name(png.name)}"
                target = input_dir / relpath
                target.parent.mkdir(parents=True, exist_ok=True)
                if write_once(target, png.read_bytes()) != digest:
                    raise Refused(f"copy of {png.name} did not reproduce {digest}")
                rows.append({"name": png.stem, "file": relpath, "sha256": digest, "qa": verdicts.get(digest)})
            entry[kind.lower()] = rows
        characters[folder.name] = entry
        counts[folder.name] = {k.lower(): len(entry[k.lower()]) for k in kinds}
    doc = {"schema": SCHEMA, "domain": domain_id, "characters": characters}
    out = Path(block["ui_data"]) / f"{domain_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out, doc, mode="ascii")
    return {"presets": out.as_posix(), "input_dir": input_dir.as_posix(), "counts": counts, **doc}
