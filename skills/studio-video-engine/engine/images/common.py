"""Shared steps of every submit route: verified shot inputs, the composed prompt, take folders, result registration.

Publish-before-receipt (M4-f1): a refused publish must leave ``--out``, the episode tree and the ComfyUI tree
byte-identical. So the image and its receipt are never written under their final names before the publish has
succeeded. ``publish_candidate`` only needs the image bytes on disk, so the image is staged under a temp name, the
publish runs against that, and only then are the image and the receipt linked into place. ``scratch`` removes the
temp files and any folder it created when anything raises.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import sha256_bytes, sha256_file, write_json_once, write_once
from ..layout.context import Context
from . import receipts
from . import workflow_publish

PLACEMENT_HEADER = "PLACEMENT (same lines for every shot of a transition pair):"


class Scratch:
    """Temp files and folders made for one publish attempt; ``unwind`` removes them all."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.made_dirs = _missing_dirs(self.folder)
        self.temps: list[Path] = []

    def temp(self, name: str) -> Path:
        """A fresh temp path beside the final file (not created yet)."""
        path = self.folder / f".{name}.{uuid.uuid4().hex}.tmp"
        self.temps.append(path)
        return path

    def drop_temps(self) -> None:
        for path in self.temps:
            path.unlink(missing_ok=True)
        self.temps.clear()

    def unwind(self) -> None:
        """Refusal path: drop the temps, then the folders this attempt created (only if still empty)."""
        self.drop_temps()
        for folder in reversed(self.made_dirs):
            try:
                folder.rmdir()
            except OSError:
                pass  # not empty: something else lives there now, so it stays


def _missing_dirs(folder: Path) -> list[Path]:
    """Ancestors of ``folder`` (inclusive) that do not exist yet, outermost first."""
    missing: list[Path] = []
    current = Path(folder)
    while not current.exists() and current != current.parent:
        missing.append(current)
        current = current.parent
    return list(reversed(missing))


@contextmanager
def scratch(folder: Path) -> Iterator[Scratch]:
    """Run a publish attempt; on any exception the temps and the folders it made are removed, then re-raised."""
    work = Scratch(folder)
    try:
        yield work
    except BaseException:
        work.unwind()
        raise
    finally:
        work.drop_temps()


def shot_inputs(out: Path, shot: str) -> dict[str, Any]:
    """The planned shot with every guide/placement/cast file re-hashed: a changed file is refused."""
    plan = receipts.load_plan(out)
    row = receipts.plan_shot(plan, shot)
    guide = receipts.verify_ref(row["guide"], f"{shot} guide")
    placement = receipts.verify_ref(row["placement"], f"{shot} placement text")
    refs = [receipts.verify_ref(r, f"{shot} reference {r['role']}") for r in row["refs"]]
    return {"plan": plan, "plan_sha256": sha256_file(Path(out) / receipts.PLAN_FILE), "row": row,
            "guide": guide, "placement": placement, "refs": refs,
            "placement_text": Path(placement["path"]).read_text(encoding="utf-8")}


def compose_prompt(prompt_file: Path, placement_text: str) -> tuple[str, dict[str, str]]:
    """The author's prompt plus the placement lines; returns ``(text, {file, sha256 of the file read})``."""
    prompt_file = Path(prompt_file)
    if not prompt_file.is_file():
        raise Refused(f"--prompt-file not found: {prompt_file}")
    body = prompt_file.read_text(encoding="utf-8").strip()
    if not body:
        raise Refused(f"--prompt-file {prompt_file.name} is empty")
    text = f"{body}\n\n{PLACEMENT_HEADER}\n{placement_text.strip()}\n"
    return text, {"file": prompt_file.resolve().as_posix(), "sha256": sha256_file(prompt_file)}


def write_prompt(folder: Path, text: str, name: str = "prompt.txt") -> dict[str, str]:
    """Save the exact composed prompt (write-once); its sha256 is what the receipt records as ``prompt_sha256``."""
    data = text.encode("utf-8")
    write_once(Path(folder) / name, data)
    return {"file": (Path(folder) / name).resolve().as_posix(), "sha256": sha256_bytes(data)}


def next_take(folder: Path, prefix: str = "t") -> str:
    folder = Path(folder)
    taken = [int(p.name[len(prefix):]) for p in folder.glob(f"{prefix}[0-9][0-9][0-9]")] if folder.is_dir() else []
    return f"{prefix}{max(taken, default=0) + 1:03d}"


def link_new_file_owned(source: Path, target: Path, expected_sha256: str, label: str) -> bool:
    """Temp copy -> sha256 verify -> ``os.link``; True only when THIS ``os.link`` created ``target``.

    Same steps as ``staging.link_new_file``, but it reports ownership from the link itself, so a concurrent writer
    that put an identical file at ``target`` first gives False (the file is kept and the caller must not roll it
    back). A different hash at ``target`` is Refused.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        require_hash(temporary, expected_sha256, f"temporary {label}")
        try:
            os.link(temporary, target)
        except FileExistsError:
            require_hash(target, expected_sha256, f"existing {label}")
            return False
    finally:
        temporary.unlink(missing_ok=True)
    require_hash(target, expected_sha256, f"staged {label}")
    return True


def link_final_then_receipt(staged: Path, final: Path, sha: str, label: str,
                            receipt_path: Path, receipt: dict[str, Any]) -> None:
    """Link a published image to its final name, then write its receipt.

    If the receipt write raises (Refused, OSError or anything else), the final image is unlinked, but only when
    THIS call's ``os.link`` created it (``link_new_file_owned``): a file that already sat at ``final``, or that a
    concurrent writer placed there, is never removed. If that unlink itself fails, the failure is attached to the
    original exception as a note and the original exception is re-raised unchanged.
    """
    owned = link_new_file_owned(staged, final, sha, label)
    try:
        write_json_once(receipt_path, receipt, mode="ascii", stamp=True)
    except BaseException as failure:
        if owned:
            try:
                final.unlink(missing_ok=True)
            except Exception as cleanup:
                failure.add_note(f"rollback could not remove {final}: {cleanup!r}")
        raise


def register(ctx: Context, out: Path, shot: str, source: Path, inputs: dict[str, Any], body: dict[str, Any],
             *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Receipt for a produced image: the route's own fields plus the plan-bound inputs.

    The receipt comes from ``receipts.build_candidate`` (the single definition). Order: refusal checks first, then
    the publish (against a temp copy of the image), and only after it succeeds the image is linked to its final
    name and the receipt is written. The source is read once; that exact payload is written to the temp candidate,
    and the temp's sha256 is both checked against ``expected_sha256`` and recorded. A failed receipt write after the
    link removes the final image again (see ``link_final_then_receipt``).
    """
    bound = {"guide": inputs["guide"], "placement": inputs["placement"],
             "ref_hashes": body.pop("ref_hashes", inputs["refs"])}
    source = Path(source)
    if not source.is_file():
        raise Refused(f"candidate image not found: {source}")
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise Refused(f"cannot read candidate image {source}: {error}") from error
    folder = receipts.candidate_dir(out, shot)
    with scratch(folder) as work:
        staged = work.temp("candidate.png")
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(payload)
        sha = sha256_file(staged)
        if expected_sha256 is not None and sha != expected_sha256:
            work.temps.remove(staged)
            raise Refused(
                f"candidate bytes changed after verification: verified sha256 {expected_sha256}, "
                f"staged sha256 {sha}; staged candidate retained at {staged}",
                evidence={"expected_sha256": expected_sha256, "actual_sha256": sha, "staged_path": str(staged)},
            )
        info = receipts.png_info(staged)
        receipt_path = folder / f"{sha[:12]}.receipt.json"
        final = folder / f"{sha[:12]}.png"
        if receipt_path.exists():
            raise Refused(f"candidate {sha} already has a receipt ({receipt_path}); "
                          "the same bytes are never registered twice")
        if final.exists():
            require_hash(final, sha, "existing candidate image")

        receipt = receipts.build_candidate(episode_id=ctx.episode_id, domain=ctx.domain_id, shot=shot,
                                           plan_sha256=inputs["plan_sha256"], created_at=time.time(),
                                           fields={**body, **bound}, output_path=final, sha256=sha, info=info)
        publish_view = {**receipt, "output": {**receipt["output"], "path": staged.as_posix()},
                        "receipt_path": receipt_path.as_posix()}
        review = workflow_publish.publish_candidate(ctx, shot, publish_view)
        # Publish has succeeded: only now do the image and the receipt get their final names.
        link_final_then_receipt(staged, final, sha, "candidate image", receipt_path, receipt)
    return {**receipt, "receipt_path": receipt_path.as_posix(), "review_workflow": review}
