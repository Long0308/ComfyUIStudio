"""`jjv images library view`: gom ảnh thư viện theo nhân vật thành BẢN COPY (port build_by_character.py).

Quy tắc giữ nguyên từ script gốc:
- Chỉ ĐỌC thư viện nguồn; copy (không hardlink/symlink); idempotent (đích đã đúng sha256 -> bỏ qua,
  đích khác sha -> báo lỗi, KHÔNG ghi đè).
- Mỗi PNG đi kèm `<stem>.prompt.txt` = byte gốc prompt.txt của take (sha256 == receipt.prompt_sha256).
- Take có PNG nhưng chưa có receipt = pending (không copy, không tính lỗi).
- Rev theo KHÓA (nhân vật, loại, số prompt NN): rev mới nhất có khóa đó thắng, khóa chỉ có ở rev cũ giữ
  nguyên là hiện hành; bản copy của rev cũ cùng khóa trong CHAR_XX/<KIND> được DI CHUYỂN sang CHAR_XX/<KIND>_<rev>_rejected/ (không xoá). File lạ thì báo lỗi, không đụng.
- INDEX.json / INDEX.md / PROMPTS.md deterministic (không timestamp).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from ..core.errors import Refused
from .library_revs import (BATCH_RE, batch_rank, owner_idx, owns, check_char, classify, contained, KINDS, PNG_RE, TAKE_RE, has_kind, key_of, png_sha12s,
                           posix, receipt_key, rev_of, resolve_revs, sha256_file, split_paths)
from .library_view_prep import (COPY_NAME_RE, image_destination, load_queue, process_item)
from .library_view_docs import build_prompts_md, write_index


def scan_source(src: Path, kind: str, rev: str):
    """(items, pending, orphan_receipts, chars) chỉ cho loại `kind`. pending = (rev, batch, take, png, lý do)."""
    items: list[dict[str, Any]] = []
    pending: list[tuple[str, str, str, str, str]] = []
    orphans: list[str] = []
    chars: set[str] = set()
    for bd in sorted(src.iterdir()):
        bm = BATCH_RE.match(bd.name) if bd.is_dir() else None
        if not bm or bm.group(3) != kind:
            continue
        chars.add(bm.group(2))
        for td in sorted(bd.iterdir()):
            if not (td.is_dir() and TAKE_RE.match(td.name)):
                continue
            for png in sorted(td.glob("*.png")):
                if not PNG_RE.match(png.name):
                    pending.append((rev, bd.name, td.name, png.name, "tên PNG không phải sha12"))
                    continue
                item = {"rev": rev, "batch": bd.name, "batch_no": int(bm.group(1)), "char": bm.group(2),
                        "kind": kind, "take": td.name, "png": png, "receipt": td / (png.stem + ".receipt.json")}
                if not item["receipt"].exists():
                    pending.append((rev, bd.name, td.name, png.name, "chưa có receipt"))
                    continue
                items.append(item)
            for rp in sorted(td.glob("*.receipt.json")):
                if not (td / (rp.name[: -len(".receipt.json")] + ".png")).exists():
                    orphans.append(posix(rp))
    return items, pending, orphans, sorted(chars)


def retire_superseded(out: Path, older_items: list[dict[str, Any]], current_files: set[Path],
                      errors: list[str], echo: Callable[[str], None]) -> None:
    """Move only the exact superseded copy; identical hashes may belong to other keys."""
    for item in older_items:
        pid = json.loads(item["receipt"].read_text(encoding="utf-8"))["prompt_id"]
        try:
            png = image_destination(item, out, pid)
            dst = image_destination(item, out, pid, rejected=True)
        except ValueError:
            continue  # process_item reports invalid IDs without copying them.
        if png in current_files or not png.is_file():
            continue
        if sha256_file(png)[:12] != item["png"].stem:
            errors.append(f"{posix(png)}: sha256 mismatch; refusing retirement")
            continue
        side, dst_side = png.with_suffix(".prompt.txt"), dst.with_suffix(".prompt.txt")
        if dst.exists() or (side.exists() and dst_side.exists()):
            errors.append(f"{posix(png)}: rejected destination already exists; refusing overwrite")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        png.replace(dst)
        if side.exists():
            side.replace(dst_side)
        echo(f"moved          {posix(dst.relative_to(out))}")


def check_unknown(out: Path, kind: str, known: set[str], errors: list[str]) -> None:
    """File trong CHAR_XX/<KIND> không thuộc rev nào đã biết -> lỗi; prompt.txt mồ côi -> lỗi."""
    for char_dir in sorted(out.glob("CHAR_*")):
        act = char_dir / kind
        if not act.is_dir():
            continue
        for png in sorted(act.glob("*.png")):
            m = COPY_NAME_RE.match(png.name)
            if m and m.group(1) not in known:
                errors.append(f"{posix(png)}: không khớp {kind} rev nào đã biết — không di chuyển")
        for side in sorted(act.glob("*.prompt.txt")):
            if not (act / (side.name[: -len(".prompt.txt")] + ".png")).exists():
                errors.append(f"{posix(side)}: prompt.txt mồ côi (không có PNG cùng tên)")


def find_prompt_id(src: Path, kind: str, s12: str) -> str:
    for rp in sorted(src.glob(f"batch-*-{kind}/t*/{s12}.receipt.json")):
        try:
            return str(json.loads(rp.read_text(encoding="utf-8")).get("prompt_id") or "")
        except Exception:  # noqa: BLE001
            return ""
    return ""


def collect_superseded(out: Path, kind: str, old_lib: Path) -> list[dict[str, Any]]:
    d_name, rev = f"{kind}_{rev_of(old_lib)}_rejected", rev_of(old_lib)
    res: list[dict[str, Any]] = []
    for char_dir in sorted(out.glob("CHAR_*")):
        d = char_dir / d_name
        for png in sorted(d.glob("*.png")) if d.is_dir() else []:
            m = COPY_NAME_RE.match(png.name)
            res.append({"char": char_dir.name, "kind": kind, "rev": rev, "status": "superseded",
                        "file": posix(png.relative_to(out)),
                        "prompt_id": find_prompt_id(old_lib, kind, m.group(1)) if m else "",
                        "sha256": sha256_file(png)})
    return res


def view(libraries: list[Path], queues: list[Path], out: Path, *, episode: Optional[Path] = None,
         machine: Optional[Path] = None, engine_dir: Optional[Path] = None,
         echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Dựng bản copy by-character. libraries: cũ -> mới. Trả {"exit", "errors", "pending", "counts", ...}."""
    libs, errors = [Path(x) for x in libraries], []
    out = Path(out)
    for lib in libs:
        if not lib.is_dir():
            errors.append(f"thiếu nguồn {posix(lib)}")
        if out == lib or lib in out.parents:
            errors.append("đích nằm trong nguồn")
    for q in queues:
        if not Path(q).is_file():
            errors.append(f"thiếu queue {posix(Path(q))}")
    if not queues:
        errors.append("thiếu --queue")
    if errors:
        return {"exit": 1, "errors": errors, "pending": [], "counts": {}, "superseded": []}
    revs, cls = resolve_revs(libs), classify(libs)
    queue: list[dict[str, Any]] = []
    qmaps: dict[str, dict[str, dict[str, Any]]] = {}
    cands: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    items, older_items, pending, orphans, src_chars = [], [], [], [], set()
    for kind in KINDS:
        last = revs[kind]["current"]
        for idx, lib in enumerate(libs):
            if not has_kind(lib, kind):
                continue
            rows = load_queue(kind, lib, [Path(q) for q in queues], errors)
            qmaps.setdefault(rev_of(lib), {}).update({r["prompt_id"]: r for r in rows})
            for r in rows:
                cands.setdefault(key_of(r["prompt_id"]) or ("", "", r["prompt_id"]), []).append((idx, r))
            it, pe, orp, ch = scan_source(lib, kind, rev_of(lib))
            src_chars |= set(ch)
            if lib == last:
                pending, orphans = pending + pe, orphans + orp
            lib_best: dict[tuple[str, str, str], int] = {}  # hạng batch cao nhất của từng khóa TRONG thư viện này
            for item in it:
                kk = receipt_key(item["receipt"])
                if kk:
                    lib_best[kk] = max(lib_best.get(kk, 0), batch_rank(item["batch"]))
            for item in it:
                k = receipt_key(item["receipt"])
                if owns(cls[kind], k, idx, item["batch"]) if k else (lib == last):
                    items.append(item)
                elif k:
                    # Cung thu vien nhung batch hau to thap hon (batch-02 vs batch-02f): cung prompt_id, brief khac,
                    # queue cua rev khong the khop ca hai => khong kiem queue cho ban bi thay (chi con la ban luu o *_rejected).
                    item["same_rev_superseded"] = batch_rank(item["batch"]) < lib_best[k]
                    older_items.append(item)
    for key, lst in sorted(cands.items()):
        own = cls[key[1]]["owner"].get(key) if key[0] else None
        queue.append((next((r for i, r in lst if i == own), None) or max(lst, key=lambda t: t[0])[1]))
    used = {k: [rev_of(libs[i]) for i in sorted(set(cls[k]["owner"].values()))] for k in KINDS}
    for k in KINDS:
        revs[k]["used"] = used[k]
    ctx = {"episode": episode, "machine": machine, "engine_dir": engine_dir, "revs": revs}
    ctx["libraries"] = {rev_of(lib): lib for lib in libs}
    # A revision with two images for one key has no unique current image.
    seen_keys: set[tuple[str, str, str]] = set()
    for item in items:
        key = receipt_key(item["receipt"])
        if key and key in seen_keys:
            raise Refused(f"multiple current images for key {key}; select one take in the source revision")
        if key:
            seen_keys.add(key)
    by_char: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_pid: dict[str, dict[str, Any]] = {}
    for item in items:
        res = process_item(item, out, qmaps.get(item["rev"], {}), errors, echo)
        if not res:
            continue
        if res["pid"] in by_pid:
            errors.append(f"prompt_id {res['pid']} có hơn một ảnh — giữ ảnh đầu, bỏ {res['entry']['file']}")
            continue
        by_pid[res["pid"]] = res
        by_char.setdefault((res["char"], res["kind"]), []).append(res["entry"])
    errors += [f"receipt mồ côi (không có PNG): {o}" for o in orphans]
    superseded: list[dict[str, Any]] = []
    if out.is_dir():
        current_files = {out / res["entry"]["file"] for res in by_pid.values()}
        retire_superseded(out, older_items, current_files, errors, echo)
        for kind in KINDS:
            known = set().union(*(png_sha12s(lib, kind) for lib in libs))
            check_unknown(out, kind, known, errors)
    # Also preserve superseded sources when building into an empty output tree.
    for item in older_items:
        process_item(item, out, qmaps.get(item["rev"], {}), errors, echo, rejected=True)
    for kind in KINDS:  # cả thư viện hiện hành: take rút trong chính nó (batch hậu tố) cũng phải vào INDEX
        for lib in libs:
            if has_kind(lib, kind):
                superseded += collect_superseded(out, kind, lib)
    queue_chars = sorted({q["char"] for q in queue})
    chars = sorted(src_chars | set(queue_chars))
    docs = {}
    for c in queue_chars:
        qs = sorted((q for q in queue if q["char"] == c), key=lambda q: (KINDS.index(q["kind"]), q["prompt_id"]))
        docs[c] = (qs, build_prompts_md(c, qs, by_pid, ctx))
    table = write_index(out, by_char, chars, pending, errors, superseded, ctx)
    for c in queue_chars:
        path, data = contained(out / check_char(c) / "PROMPTS.md", out, "PROMPTS.md"), docs[c][1].encode("utf-8")
        old = path.read_bytes() if path.is_file() else None
        if old == data:
            act = "unchanged"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            act = "written" if old is None else "rewritten"
        n_img = sum(1 for q in docs[c][0] if q["prompt_id"] in by_pid)
        echo(f"{act:14s} {posix(path.relative_to(out.resolve()))}  ({n_img}/{len(docs[c][0])} prompt_id có ảnh)")
    counts = {c: {k: len(by_char.get((c, k), [])) for k in KINDS} for c in chars}
    echo(f"\nTổng ảnh đã có: {sum(len(v) for v in by_char.values())}; đã rút: {len(superseded)}; "
         f"pending: {len(pending)}; lỗi: {len(errors)}")
    echo("\n" + "\n".join(table))
    for e in errors:
        echo(f"LỖI: {e}")
    return {"exit": 1 if errors else 0, "errors": errors, "pending": pending, "counts": counts,
            "superseded": superseded}


def register(subparsers: Any) -> None:
    """Gắn `view` vào nhóm `library` (Fable/root nối): subparsers = library.add_subparsers(...)."""
    p = subparsers.add_parser("view", help="group the library by character (copies + PROMPTS.md + INDEX)")
    p.add_argument("--library", action="append", required=True, metavar="DIR[,DIR2]",
                   help="libraries oldest -> newest; newest revision per character/kind/prompt number wins")
    p.add_argument("--queue", action="append", required=True, metavar="FILE[,FILE2]")
    p.add_argument("--out", required=True)
    p.add_argument("--episode", default=None)
    p.add_argument("--machine", default=None)
    p.add_argument("--engine-dir", default=None)
    p.set_defaults(library_func=run_view)


def run_view(args: Any) -> int:
    opt = lambda v: Path(v) if v else None  # noqa: E731
    r = view(split_paths(args.library), split_paths(args.queue), Path(args.out), episode=opt(args.episode),
             machine=opt(args.machine), engine_dir=opt(args.engine_dir))
    if int(r["exit"]) != 0:
        print(json.dumps({"ok": False, "error": "; ".join(r["errors"]) or "library view failed",
                          "errors": r["errors"]}, indent=2))
    return int(r["exit"])
