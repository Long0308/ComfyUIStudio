"""``jjv images compare|approve --library-out DIR``: review of character-LIBRARY images (no shot, no plan).

Their receipts are ``jjv/library-image-receipt/v1`` files under ``DIR/<batch_id>/tNNN/`` (written by
``images submit --library-out``). One review key = one ``prompt_id`` (or a whole ``--character`` = every prompt_id that
belongs to ``<CHARACTER>`` = ``CHAR_08``), across every batch/lane/account. Review files live in ``DIR/_review/<key>/``:
``compare-<digest>.png|json``, ``checklist.json``. ``--character`` is only a VIEW (sheet + checklist under
``character-<CHAR>``); an approval is ALWAYS filed under the take's own prompt_id
(``_review/<prompt_id>/approvals/approval-vNNN.json``, write-once), so 20 images of a character keep 20 approvals.

Checklist items come from the routes recipe (``compare.library_checklist``): identity, wardrobe, logo, real skin.
An approval binds the user's pick to ONE take sha256 + its receipt sha256 + every reference hash; ``current_approval``
re-checks image, receipt and references every time, so a changed byte makes it stale (no older approval is revived).
There is no ``native`` step: it makes the 864x480 H3 anchor of a SHOT image, a library image is a reference, not an anchor.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import canonical_sha256, read_json, sha256_file, write_atomic, write_json_once, write_once, pretty_json
from ..layout.context import ROUTES_RECIPE, Context, load_recipe
from . import compare as compare_mod
from . import imgutil, receipts
from .codex import LIBRARY_RECEIPT_SCHEMA

CHECKLIST_SCHEMA = "jjv/library-image-checklist/v1"
APPROVAL_SCHEMA = "jjv/library-image-approval/v1"


def checklist_items() -> list[str]:
    return list(load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0]["compare"]["library_checklist"])


PROMPT_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
_WINDOWS_DEVICE_RE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)
CHARACTER_RE = re.compile(r"[A-Za-z0-9]+_[0-9]+")
_CHARACTER_OF_RE = re.compile(r"([A-Za-z0-9]+_[0-9]+)(?:_|$)")


def check_prompt_id(prompt_id: str) -> str:
    """Letters, digits, ``_`` and ``-`` only: it becomes a folder name, so ``..``, ``/`` and backslash never get in."""
    if not isinstance(prompt_id, str) or not PROMPT_ID_RE.fullmatch(prompt_id) or ".." in prompt_id:
        raise Refused(f"prompt_id {prompt_id!r} is not allowed: only letters, digits, '_' and '-' (it names a folder)")
    if _WINDOWS_DEVICE_RE.fullmatch(prompt_id):
        raise Refused(f"prompt_id {prompt_id!r} is a reserved Windows device name and cannot name a folder")
    return prompt_id


def character_of(prompt_id: str) -> str | None:
    """``CHAR_08`` of ``CHAR_08_FACE_1_r005`` (code = ``<LETTERS/DIGITS>_<NUMBER>`` followed by ``_`` or the end)."""
    found = _CHARACTER_OF_RE.match(str(prompt_id))
    return found.group(1) if found else None


def _select(prompt_id: str | None, character: str | None) -> tuple[str, Any]:
    if (prompt_id is None) == (character is None):
        raise Refused("give exactly one of --prompt-id or --character")
    if prompt_id is not None:
        check_prompt_id(prompt_id)
        return prompt_id, lambda pid: pid == prompt_id
    if not isinstance(character, str) or not CHARACTER_RE.fullmatch(character):
        raise Refused(f"--character {character!r} is not one character code (like CHAR_08): a prefix would gather several characters")
    return f"character-{character}", lambda pid: character_of(pid) == character


def check_batch_file(path: Path) -> None:
    """Library submit guard: a batch named ``_*`` would share ``DIR/_review`` (``takes_of`` skips it); every prompt_id is checked."""
    path = Path(path)
    if path.stem.startswith("_"):
        raise Refused(f"batch file name {path.name!r} starts with '_': that namespace is reserved for DIR/_review (rename the file)")
    try:
        data = read_json(path)
    except (ValueError, OSError):
        return  # an unreadable batch is refused by codex.load_batch with its own message
    for row in data if isinstance(data, list) else []:
        if isinstance(row, dict) and "prompt_id" in row:
            check_prompt_id(row["prompt_id"])


def review_dir(library_out: Path, key: str) -> Path:
    return Path(library_out) / "_review" / key


def takes_of(library_out: Path, prompt_id: str | None, character: str | None) -> tuple[str, list[dict[str, Any]]]:
    """``(key, receipts)`` of every library take matching the selector, oldest first; Refused when there is none."""
    key, match = _select(prompt_id, character)
    rows = []
    for path in sorted(Path(library_out).glob("*/*/*.receipt.json")):
        if path.parts[-3].startswith("_"):
            continue
        try:
            row = read_json(path)
        except Exception:  # an unreadable foreign file is not a take
            continue
        if isinstance(row, dict) and row.get("schema") == LIBRARY_RECEIPT_SCHEMA and match(str(row.get("prompt_id"))):
            rows.append({**row, "receipt_path": path.as_posix()})
    if not rows:
        raise Refused(f"no library take for {prompt_id or character!r} under {library_out} (run `images submit --library-out` first)")
    return key, sorted(rows, key=lambda r: (r.get("created_at", 0), r["output"]["sha256"]))


def _verify(row: dict[str, Any]) -> dict[str, Any]:
    """The image still hashes to its receipt and every reference still hashes to what the receipt recorded."""
    path = Path(row["output"]["path"])
    if not path.is_file() or sha256_file(path) != row["output"]["sha256"]:
        raise Refused(f"library take {row['output']['sha256']} no longer matches its receipt ({path}); not usable")
    for ref in row.get("ref_hashes") or []:
        receipts.verify_ref(ref, f"{row.get('prompt_id')} reference {ref.get('role')}")
    return row


def _sheet(takes: list[dict[str, Any]], refs: list[dict[str, Any]], items: list[str], cell_height: int) -> bytes:
    import io

    from PIL import ImageDraw

    top = [compare_mod._cell(imgutil.load_rgb(Path(r["path"])), f"ref {r['role']} {r['sha256'][:8]}", cell_height) for r in refs]
    bottom = [compare_mod._cell(imgutil.load_rgb(Path(t["output"]["path"])),
                                f"{t.get('account_label')} {t['output']['sha256'][:8]}", cell_height) for t in takes]
    rows = [compare_mod._row(top or [compare_mod._cell(imgutil.pil().new("RGB", (64, 64), (255, 255, 255)), "(no refs)", cell_height)]),
            compare_mod._row(bottom)]
    footer = imgutil.pil().new("RGB", (max(r.width for r in rows), compare_mod.CAPTION * 2 + 4), (255, 255, 255))
    ImageDraw.Draw(footer).text((compare_mod.MARGIN, 4), "checklist: " + " | ".join(f"[ ] {i}" for i in items), fill=(10, 37, 64))
    rows.append(footer)
    sheet = imgutil.pil().new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), (247, 250, 253))
    y = 0
    for row in rows:
        sheet.paste(row, (0, y))
        y += row.height
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


def _merge_checklist(path: Path, key: str, shas: list[str], items: list[str]) -> dict[str, Any]:
    document = read_json(path) if path.is_file() else {"schema": CHECKLIST_SCHEMA, "key": key, "items": items, "candidates": {}}
    for sha in shas:
        entry = document["candidates"].setdefault(sha, {})
        for item in items:
            entry.setdefault(item, {"status": "unreviewed", "note": ""})
    document["items"] = items
    write_atomic(path, pretty_json(document, mode="ascii"))
    return document


def compare(ctx: Context, library_out: Path, *, prompt_id: str | None = None, character: str | None = None) -> dict[str, Any]:
    key, rows = takes_of(library_out, prompt_id, character)
    rows = [_verify(r) for r in rows]
    refs: dict[str, dict[str, Any]] = {}
    for row in rows:
        for ref in row.get("ref_hashes") or []:
            refs.setdefault(ref["sha256"], ref)
    spec = load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0]["compare"]
    items = list(spec["library_checklist"])
    folder = review_dir(library_out, key)
    shas = [r["output"]["sha256"] for r in rows]
    digest = canonical_sha256({"refs": sorted(refs), "takes": sorted(shas)}, mode="ascii")[:12]
    sheet = folder / f"compare-{digest}.png"
    write_once(sheet, _sheet(rows, list(refs.values()), items, spec["cell_height"]))
    checklist = folder / "checklist.json"
    _merge_checklist(checklist, key, shas, items)
    takes = [{"sha256": r["output"]["sha256"], "prompt_id": r.get("prompt_id"), "batch_id": r.get("batch_id"),
              "account_label": r.get("account_label"), "receipt": r["receipt_path"]} for r in rows]
    record = {"schema": "jjv/library-image-compare/v1", "key": key, "created_at": time.time(),
              "sheet": {"path": sheet.resolve().as_posix(), "sha256": sha256_file(sheet)}, "refs": list(refs.values()),
              "takes": takes, "checklist": checklist.as_posix(), "checklist_items": items}
    record_path = folder / f"compare-{digest}.json"
    if not record_path.exists():
        write_json_once(record_path, record, mode="ascii", stamp=True)
    return {"key": key, "sheet": sheet.as_posix(), "sheet_sha256": record["sheet"]["sha256"], "checklist": checklist.as_posix(),
            "candidates": shas, "takes": takes, "checklist_items": items, "record": record_path.as_posix()}


def _checklists_pass(library_out: Path, recorded: Path, sha: str) -> bool:
    """The recorded review is required; every other review containing this sha must also pass."""
    if not recorded.is_file():
        return False
    recorded = recorded.resolve()
    paths = {p.resolve() for p in (Path(library_out) / "_review").rglob("checklist.json")}
    paths.add(recorded)
    required = checklist_items()
    for path in sorted(paths):
        document = read_json(path)
        if not isinstance(document, dict) or not isinstance(document.get("candidates"), dict):
            return False
        candidates = document["candidates"]
        if sha not in candidates and path != recorded:
            continue
        checks = candidates.get(sha)
        items = document.get("items", [])
        if not isinstance(checks, dict) or not isinstance(items, list) or any(not isinstance(i, str) for i in items):
            return False
        if any(not isinstance(checks.get(i), dict) or checks[i].get("status") != "pass" for i in required + items):
            return False
        if any(not isinstance(check, dict) or check.get("status") != "pass" for check in checks.values()):
            return False
    return True


def current_approval(library_out: Path, prompt_id: str) -> dict[str, Any] | None:
    """The newest approval must match its receipt and pass every current review of its take.
    A stale newest approval never revives an older one."""
    folder = review_dir(library_out, check_prompt_id(prompt_id)) / "approvals"
    for path in sorted(folder.glob("approval-v[0-9][0-9][0-9].json"), reverse=True) if folder.is_dir() else []:
        row = read_json(path)
        try:
            receipt = Path(row["receipt"]["path"])
            if not receipt.is_file() or sha256_file(receipt) != row["receipt"]["sha256"]:
                return None
            _verify({**read_json(receipt), "receipt_path": receipt.as_posix()})
            if not _checklists_pass(library_out, Path(row["checklist_path"]), row["candidate_sha256"]):
                return None
        except (Refused, Uncertain, KeyError, OSError):
            return None
        return {**row, "path": path.as_posix()}
    return None


def current_approvals(library_out: Path, character: str) -> dict[str, dict[str, Any]]:
    """``{prompt_id: approval}`` for every prompt_id of one character that has a live approval."""
    _, rows = takes_of(library_out, None, character)
    found = {}
    for pid in sorted({str(r.get("prompt_id")) for r in rows}):
        approval = current_approval(library_out, pid)
        if approval is not None:
            found[pid] = approval
    return found


def approve(ctx: Context, library_out: Path, sha: str, *, prompt_id: str | None = None, character: str | None = None,
            reviewer: str, scope: str, checklist: Path | None = None) -> dict[str, Any]:
    if not reviewer.strip() or not scope.strip():
        raise Refused("--reviewer and --scope are required (an approval names who approved what, and for which use)")
    sha = sha.lower()
    if len(sha) < 8 or any(c not in "0123456789abcdef" for c in sha):
        raise Refused(f"--sha needs at least 8 hex digits of the take sha256, got {sha!r}")
    key, rows = takes_of(library_out, prompt_id, character)
    found = [r for r in rows if r["output"]["sha256"].startswith(sha)]
    if len(found) != 1:
        raise Refused(f"{prompt_id or character}: {len(found)} library takes match sha {sha} (only takes of this review key can be approved)")
    receipt = _verify(found[0])
    full = receipt["output"]["sha256"]
    pid = check_prompt_id(str(receipt.get("prompt_id")))
    owner = character_of(pid)
    for code in set(re.findall(rf"\b{re.escape(pid.split('_')[0])}_[0-9]+\b", scope)):
        if code != owner:
            raise Refused(f"--scope names {code} but take {full[:12]} is of {owner}: an approval cannot cover another character")
    path = Path(checklist) if checklist else review_dir(library_out, key) / "checklist.json"
    if not path.is_file():
        raise Refused(f"no checklist at {path}: run `jjv images compare --library-out ... ` and fill it in")
    checks = (read_json(path).get("candidates") or {}).get(full)
    if not isinstance(checks, dict):
        raise Refused(f"the checklist has no entry for take {full}; re-run `images compare --library-out` first")
    wanted = checklist_items()
    bad = {i: (checks.get(i) or {}).get("status", "missing") for i in wanted if (checks.get(i) or {}).get("status") != "pass"}
    if bad:
        raise Refused(f"take {full[:12]} is not approved: checklist items not 'pass': {bad}")
    previous = current_approval(library_out, pid)
    folder = review_dir(library_out, pid) / "approvals"
    count = len(list(folder.glob("approval-v*.json"))) if folder.is_dir() else 0
    file = folder / f"approval-v{count + 1:03d}.json"
    body = {"schema": APPROVAL_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id, "key": pid,
            "prompt_id": pid, "character": owner, "selected_by": key, "batch_id": receipt.get("batch_id"), "account_label": receipt.get("account_label"),
            "candidate_sha256": full, "receipt": {"path": Path(receipt["receipt_path"]).resolve().as_posix(),
                                                  "sha256": sha256_file(Path(receipt["receipt_path"]))},
            "prompt_sha256": receipt.get("prompt_sha256"), "ref_hashes": receipt.get("ref_hashes"),
            "reviewer": reviewer.strip(), "scope": scope.strip(), "checks": {k: checks[k] for k in wanted},
            "checklist_sha256": sha256_file(path), "checklist_path": path.resolve().as_posix(), "created_at": time.time(),
            "supersedes": previous["path"] if previous else None, "status": "accepted_library_image",
            "note": "covers this still as a character reference; shots, motion and continuity need their own reviews"}
    write_json_once(file, body, mode="ascii", stamp=True)
    return {"approval": file.as_posix(), "candidate_sha256": full, "key": pid, "supersedes": body["supersedes"]}
