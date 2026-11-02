"""``jjv images library register``: đưa MỘT ảnh ngoài luồng sinh (user đã duyệt) vào thư viện nhân vật bằng đúng đường của engine.

Không sửa tay INDEX: ảnh được ghi thành một take hợp lệ của thư viện nguồn (``batch-NN-CHAR_XX-<KIND>/t001/<sha12>.png`` + ``prompt.txt``
+ receipt ``jjv/library-image-receipt/v1`` route ``user-approved-external``), brief vào queue ``queue-<rev>.json`` cạnh batch file, rồi
chạy ĐÚNG ``library.compare`` + ``library.approve`` (checklist toàn ``pass``, người duyệt = ``--approved-by``) và ``library view`` để
INDEX/bản copy theo nhân vật được dựng lại.  Luật: file nguồn JPG ⇒ PNG decode đúng điểm ảnh, byte ổn định; file duyệt
(``--approval-source``) là JSON có cấu trúc (``items[]``/``decisions[]``) với một dòng có sha256 = file nguồn, status đã duyệt
và domain = domain đăng ký; ảnh nằm dưới root của domain khác bị từ chối. Ghi một lần, cùng byte đăng ký lại = không làm gì.
Mọi từ chối xảy ra trước khi ghi bất cứ thứ gì.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import pretty_json, read_json, sha256_file, write_atomic, write_json_once, write_once
from ..layout.context import SKILL_ROOT, Context, load_context
from . import library, library_view
from .codex import LIBRARY_RECEIPT_SCHEMA
from .library_revs import BATCH_RE, CHAR_ID_RE, KINDS, PNG_SIG, keyed_images, rev_of, split_paths

ROUTE = "user-approved-external"
FIRST_NUMBER = 90  # NN của khóa CHAR_XX_<KIND>_NN: dải 90+ dành cho ảnh ngoài luồng, không đụng 01..89 của luồng sinh
LABEL_RE = re.compile(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*")
REV_SUFFIX = "r001x"  # PROMPT_RE của library view bắt buộc hậu tố _r<số><chữ>
DOMAINS_DIR = SKILL_ROOT / "domains"  # mỗi domain JSON có thể khai ``library_roots`` / ``staging_roots`` (danh sách đường dẫn)
DOMAIN_ROOT_KEYS = ("library_roots", "staging_roots")
APPROVAL_LISTS = ("items", "decisions")  # hình dạng bản ghi duyệt có cấu trúc (APPROVALS-*.json dùng items[])
APPROVED_STATUSES = frozenset({"approved", "user_approved"})


def _png_of(source: Path) -> bytes:
    """PNG của ``source``: file đã là PNG giữ nguyên byte; ảnh khác decode rồi ghi PNG không metadata (cùng ảnh ⇒ cùng byte)."""
    raw = Path(source).read_bytes()
    if raw.startswith(PNG_SIG):
        return raw
    from . import imgutil

    try:
        image = imgutil.load_rgb(Path(source))
    except Exception as error:  # noqa: BLE001 - mọi lỗi giải mã là một lý do từ chối
        raise Refused(f"{source} is not a readable image ({error})") from error
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _size(png: bytes) -> tuple[int, int]:
    from . import imgutil

    with imgutil.pil().open(io.BytesIO(png)) as image:
        return image.size


def _foreign_roots(domain: str) -> list[Path]:
    """Root thư viện/staging khai trong domain JSON KHÁC domain đang đăng ký (đọc từ config, không hardcode tên domain)."""
    roots: list[Path] = []
    for path in sorted(Path(DOMAINS_DIR).glob("*.json")):
        row = read_json(path)
        if not isinstance(row, dict) or row.get("domain_id", path.stem) == domain:
            continue
        for key in DOMAIN_ROOT_KEYS:
            value = row.get(key)
            if isinstance(value, list):
                roots += [Path(v).resolve() for v in value if isinstance(v, str) and v.strip()]
    return roots


def _check_source_root(domain: str, source: Path) -> None:
    resolved = Path(source).resolve()
    for root in _foreign_roots(domain):
        if resolved.is_relative_to(root):
            raise Refused(f"SOURCE_DOMAIN_MISMATCH: {resolved.as_posix()} lies under {root.as_posix()}, a library/staging root "
                          f"of another domain; this image cannot enter the {domain!r} library")


def _check_approval_record(approval: Path, source_sha: str, domain: str) -> None:
    """Bản ghi duyệt phải là JSON có cấu trúc: một dòng có sha256 = sha nguồn, status đã duyệt, domain = domain đăng ký."""
    try:
        document = read_json(approval)
    except Uncertain as error:
        raise Refused(f"APPROVAL_NOT_STRUCTURED: {approval} is not JSON ({error}); plain text is not an approval record") from error
    rows = [r for key in APPROVAL_LISTS if isinstance(document, dict) and isinstance(document.get(key), list)
            for r in document[key] if isinstance(r, dict)]
    if not rows:
        raise Refused(f"APPROVAL_NOT_STRUCTURED: {approval} has no {' or '.join(APPROVAL_LISTS)}[] list of rows with sha256")
    matching = [r for r in rows if r.get("sha256") == source_sha]
    if not matching:
        raise Refused(f"APPROVAL_SHA_NOT_FOUND: no row in {approval} has sha256 {source_sha}; add the approval row first, nothing is written")
    reasons: list[str] = []
    for row in matching:
        if row.get("status") not in APPROVED_STATUSES:
            reasons.append(f"APPROVAL_NOT_APPROVED: row status is {row.get('status')!r}, need one of {sorted(APPROVED_STATUSES)}")
            continue
        row_domain = row.get("domain", document.get("domain") if isinstance(document, dict) else None)
        if row_domain is None:
            reasons.append(f"APPROVAL_DOMAIN_MISSING: the approval row for {source_sha[:12]} names no domain")
        elif row_domain != domain:
            reasons.append(f"SOURCE_DOMAIN_MISMATCH: the approval row names domain {row_domain!r}, this register is for {domain!r}")
        else:
            return
    raise Refused(reasons[0] + "; nothing is written")


def _check_inputs(domain: str, character: str, kind: str, label: str, approved_by: str, source: Path, approval: Path) -> str:
    if not isinstance(character, str) or not CHAR_ID_RE.fullmatch(character):
        raise Refused(f"--character {character!r} is not one character code like CHAR_02")
    if kind not in KINDS:
        raise Refused(f"--kind must be one of {list(KINDS)}, got {kind!r}")
    if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
        raise Refused(f"--label {label!r}: letters, digits and single '_' only (it names a prompt_id and a file)")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise Refused("--approved-by is required (who approved this image)")
    if not Path(source).is_file():
        raise Refused(f"--file not found: {source}")
    if not Path(approval).is_file():
        raise Refused(f"APPROVAL_SOURCE_MISSING: {approval} does not exist; an external image needs a recorded user approval")
    source_sha = sha256_file(Path(source))
    _check_source_root(domain, Path(source))
    _check_approval_record(Path(approval), source_sha, domain)
    return source_sha


def _existing(source_library: Path, character: str, kind: str, png_sha: str) -> dict[str, Any] | None:
    for path in sorted(Path(source_library).glob(f"batch-*-{character}-{kind}/t*/*.receipt.json")):
        row = read_json(path)
        if isinstance(row, dict) and (row.get("output") or {}).get("sha256") == png_sha:
            return {**row, "receipt_path": path.as_posix()}
    return None


def _next_number(libs: list[Path], kind: str, character: str) -> int:
    used = {int(key[2]) for lib in libs for _, key, _ in keyed_images(lib, kind) if key[0] == character}
    number = FIRST_NUMBER
    while number in used:
        number += 1
    if number > 99:
        raise Refused(f"{character} {kind}: no free external number between {FIRST_NUMBER} and 99")
    return number


def _merge_queue(queue_dir: Path, rev: str, row: dict[str, Any], brief: dict[str, str]) -> Path:
    """``queue-<rev>.json`` (trạng thái dẫn xuất, ghi lại nguyên tử) + batch file brief cạnh nó (ghi một lần)."""
    path = Path(queue_dir) / f"queue-{rev}.json"
    rows = [r for r in (read_json(path) if path.is_file() else []) if r.get("prompt_id") != row["prompt_id"]]
    write_atomic(path, pretty_json(sorted([*rows, row], key=lambda r: r["prompt_id"]), mode="ascii"))
    write_json_once(Path(queue_dir) / f"{row['batch_id']}.json", [brief], mode="ascii")
    return path


def _approve(ctx: Context, source_library: Path, pid: str, sha: str, character: str, kind: str, label: str, approved_by: str,
             approval: Path) -> str:
    """Đúng đường review của thư viện: compare ⇒ checklist ``pass`` (ghi chú trỏ file duyệt) ⇒ approve (write-once)."""
    compared = library.compare(ctx, source_library, prompt_id=pid)
    path = Path(compared["checklist"])
    document = read_json(path)
    note = f"user-approved external image; approval source {approval.name} sha256 {sha256_file(approval)[:12]}"
    for item in compared["checklist_items"]:
        document["candidates"][sha][item] = {"status": "pass", "note": note}
    write_atomic(path, pretty_json(document, mode="ascii"))
    scope = f"{character} {kind} reference ({label}); approval source {approval.name}"
    return library.approve(ctx, source_library, sha, prompt_id=pid, reviewer=approved_by, scope=scope)["approval"]


def register(ctx: Context, *, character: str, kind: str, file: Path, label: str, approved_by: str, approval_source: Path,
             library_out: Path, source_library: Path, queue_dir: Path, view_libraries: list[Path] | None = None,
             view_queues: list[Path] | None = None) -> dict[str, Any]:
    source, approval = Path(file), Path(approval_source)
    source_sha = _check_inputs(ctx.domain_id, character, kind, label, approved_by, source, approval)
    png = _png_of(source)
    png_sha = hashlib.sha256(png).hexdigest()
    found = _existing(source_library, character, kind, png_sha)
    if found is not None:
        return {"status": "unchanged", "prompt_id": found["prompt_id"], "sha256": png_sha, "receipt": found["receipt_path"]}
    libs = [Path(p) for p in view_libraries or []]
    number = _next_number([*libs, Path(source_library)], kind, character)
    pid = f"{character}_{kind}_{number:02d}_{label.upper()}_{REV_SUFFIX}"
    batch = f"batch-{number:02d}-{character}-{kind}"
    if not BATCH_RE.fullmatch(batch):
        raise Refused(f"internal: {batch} is not a library batch name")
    take = Path(source_library) / batch / "t001"
    width, height = _size(png)
    text = (f"External image registered by user approval.\ncharacter: {character}\nkind: {kind}\nlabel: {label}\n"
            f"source: {source.resolve().as_posix()}\nsource_sha256: {source_sha}\npng_sha256: {png_sha}\n"
            f"approval_source: {approval.resolve().as_posix()}\napproved_by: {approved_by.strip()}\n")
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ref = {"role": "external_source", "path": source.resolve().as_posix(), "sha256": source_sha}
    image = take / f"{png_sha[:12]}.png"
    receipt_path = take / f"{png_sha[:12]}.receipt.json"
    receipt = {"schema": LIBRARY_RECEIPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id, "status": "registered_external",
               "route": ROUTE, "provider": ROUTE, "prompt_id": pid, "batch_id": batch, "account_label": ROUTE, "created_at": 0,
               "prompt": {"file": (take / "prompt.txt").resolve().as_posix(), "sha256": text_sha}, "prompt_sha256": text_sha,
               "prompt_text_sha256": text_sha, "ref_hashes": [ref],
               "output": {"path": image.resolve().as_posix(), "sha256": png_sha, "width": width, "height": height, "bytes": len(png)},
               "source": {"path": ref["path"], "sha256": source_sha, "converted": source_sha != png_sha},
               "approval_source": {"path": approval.resolve().as_posix(), "sha256": sha256_file(approval)},
               "approved_by": approved_by.strip(), "label": label,
               "tool_evidence": "registered by `jjv images library register`; provenance = the recorded user approval, bytes are hash-bound"}
    write_once(image, png)
    write_once(take / "prompt.txt", text.encode("utf-8"))
    write_json_once(receipt_path, receipt, mode="ascii")
    row = {"prompt_id": pid, "char": character, "kind": kind, "batch_id": batch, "prompt_sha256": text_sha, "account": ROUTE,
           "ref_images": [ref]}
    queue = _merge_queue(Path(queue_dir), rev_of(Path(source_library)), row, {"prompt_id": pid, "prompt_text": text})
    approval_path = _approve(ctx, Path(source_library), pid, png_sha, character, kind, label, approved_by, approval)
    result: dict[str, Any] = {"status": "registered", "prompt_id": pid, "sha256": png_sha, "image": image.as_posix(),
                              "receipt": receipt_path.as_posix(), "queue": queue.as_posix(), "approval": approval_path}
    if view_libraries is not None:
        shown = library_view.view([*libs, Path(source_library)], [*(Path(q) for q in view_queues or []), queue], Path(library_out),
                                  echo=lambda _: None)
        if int(shown["exit"]) != 0:
            raise Refused("library view failed after registering: " + "; ".join(shown["errors"]))
        result["view"] = {"exit": shown["exit"], "counts": shown["counts"].get(character)}
    return result


# ---- CLI -----------------------------------------------------------------------------------------------
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--machine", default=None)
    parser.add_argument("--character", required=True, help="CHAR_XX")
    parser.add_argument("--kind", required=True, choices=list(KINDS))
    parser.add_argument("--file", required=True, help="the image to register (PNG, or JPG converted to an exact PNG)")
    parser.add_argument("--label", required=True, help="SLUG naming the take, e.g. OFFICE_EXPLAINING")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approval-source", required=True, help="structured approval JSON: items[] or decisions[] row with sha256 = the file's sha, status approved, domain = this domain")
    parser.add_argument("--library-out", required=True, metavar="DIR", help="the by-character library root that `library view` rebuilds")
    parser.add_argument("--source-library", required=True, metavar="DIR", help="library-<rev> folder that receives the take (created if absent)")
    parser.add_argument("--queue-dir", required=True, metavar="DIR", help="folder of queue-<rev>.json + brief batch files for that library")
    parser.add_argument("--view-library", action="append", default=None, metavar="DIR[,DIR2]",
                        help="existing source libraries oldest -> newest for the view rebuild (the new library is appended)")
    parser.add_argument("--view-queue", action="append", default=None, metavar="FILE[,FILE2]", help="existing queues for the view rebuild")


def run_register(args: argparse.Namespace) -> int:
    ctx = load_context(args.episode, args.machine)
    libs = split_paths(args.view_library) if args.view_library else None
    result = register(ctx, character=args.character, kind=args.kind, file=Path(args.file), label=args.label, approved_by=args.approved_by,
                      approval_source=Path(args.approval_source), library_out=Path(args.library_out), source_library=Path(args.source_library),
                      queue_dir=Path(args.queue_dir), view_libraries=libs, view_queues=split_paths(args.view_queue) if args.view_queue else None)
    print(json.dumps({"ok": True, "verb": "library register", **result}, indent=2))
    return 0
