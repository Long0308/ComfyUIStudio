"""Copy một take vào bản by-character + đọc queue (phần dưới của `library view`)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from .library import check_prompt_id
from .library_revs import TAKE_RE, check_batch, check_char, contained, posix, rev_of, sha256_file

# NN_<short>__<sha12>.png (tên file trong bản copy theo nhân vật)
COPY_NAME_RE = re.compile(r"^\d{2}_.+__([0-9a-f]{12})\.png$")
# CHAR_08_FACE_01_NEUTRAL_FOCUS_r005_r005b -> char=CHAR_08 kind=FACE short=01_NEUTRAL_FOCUS
PROMPT_RE = re.compile(r"^(CHAR_\d+)_(FACE|ACTION)_(\d{2}_[A-Za-z0-9_]+?)(?:_r\d+[a-z]*)+$")


def image_destination(item: dict[str, Any], out: Path, pid: str, *, rejected: bool = False) -> Path:
    """Exact copy path, including prompt label and hash, rather than a global hash match."""
    match = PROMPT_RE.fullmatch(pid)
    if match is None:
        raise ValueError(f"invalid prompt_id: {pid!r}")
    folder = f"{item['kind']}_{item['rev']}_rejected" if rejected else item["kind"]
    return out / item["char"] / folder / f"{item['batch_no']:02d}_{match.group(3)}__{item['png'].stem}.png"


def place(src: Path, sha: str, dest: Path, rel: str, what: str, errors: list[str]) -> Optional[str]:
    """Đặt src vào dest đúng sha256: 'copied' | 'skip-same-sha' | None (lỗi đã ghi)."""
    if dest.exists():
        if sha256_file(dest) != sha:
            errors.append(f"{rel}: đích {posix(dest)} ({what}) đã tồn tại khác sha256 — không ghi đè")
            return None
        return "skip-same-sha"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    shutil.copy2(src, tmp)
    if sha256_file(tmp) != sha:
        errors.append(f"{rel}: copy {what} lỗi, sha256 đích lệch — giữ nguyên {posix(tmp)} để điều tra")
        return None
    tmp.replace(dest)
    return "copied"


def check_against_queue(res: dict[str, Any], q: Optional[dict[str, Any]], errors: list[str]) -> None:
    """Receipt có ảnh phải khớp queue của đúng rev: brief sha và bộ ảnh tham chiếu (path + sha256)."""
    if q is None:
        errors.append(f"{res['pid']}: có ảnh nhưng KHÔNG có trong queue-{res['rev']}")
        return
    rec = res["rec"]
    if rec.get("prompt_text_sha256") != q["prompt_sha256"]:
        errors.append(f"{res['pid']}: receipt.prompt_text_sha256 lệch queue.prompt_sha256")
    rk = sorted((r["path"], r["sha256"]) for r in rec.get("ref_hashes") or [])
    qk = sorted((r["path"], r["sha256"]) for r in q["ref_images"])
    if rk != qk:
        errors.append(f"{res['pid']}: receipt.ref_hashes lệch queue.ref_images")


def process_item(item: dict[str, Any], out: Path, qmap: dict[str, Any], errors: list[str],
                 echo: Callable[[str], None], *, rejected: bool = False) -> Optional[dict[str, Any]]:
    """Kiểm receipt + sha, copy PNG và prompt.txt sang `out`. Trả kết quả hoặc None nếu lỗi."""
    rev, rel = item["rev"], f"{item['batch']}/{item['take']}/{item['png'].name}"
    try:
        rec = json.loads(item["receipt"].read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - báo lỗi cụ thể, không nuốt
        errors.append(f"{rel}: receipt không đọc được ({e})")
        return None
    pid = rec.get("prompt_id") if isinstance(rec, dict) else None
    m = PROMPT_RE.match(pid or "")
    if not m:
        errors.append(f"{rel}: prompt_id không parse được: {pid!r}")
        return None
    if m.group(1) != item["char"] or m.group(2) != item["kind"]:
        errors.append(f"{rel}: prompt_id {pid} lệch với thư mục batch {item['batch']}")
        return None
    if rec.get("batch_id") not in (None, item["batch"]):
        errors.append(f"{rel}: batch_id {rec.get('batch_id')} lệch với thư mục")
        return None
    sha = sha256_file(item["png"])
    if sha[:12] != item["png"].stem:
        errors.append(f"{rel}: sha256 thực {sha[:12]} không khớp tên file")
        return None
    prompt_src = item["receipt"].parent / "prompt.txt"
    if not prompt_src.is_file():
        errors.append(f"{rel}: thiếu prompt.txt trong take {posix(prompt_src.parent)}")
        return None
    pbytes = prompt_src.read_bytes()
    psha = hashlib.sha256(pbytes).hexdigest()
    if psha != rec.get("prompt_sha256"):
        errors.append(f"{rel}: prompt.txt sha {psha[:12]} khác receipt.prompt_sha256 "
                      f"{str(rec.get('prompt_sha256'))[:12]} — không copy")
        return None
    try:
        ptext = pbytes.decode("utf-8")
    except UnicodeDecodeError as e:
        errors.append(f"{rel}: prompt.txt không phải UTF-8 ({e})")
        return None
    take_no = int(TAKE_RE.match(item["take"]).group(1))
    dest = image_destination(item, out, pid, rejected=rejected)
    act = place(item["png"], sha, dest, rel, "PNG", errors)
    if act is None:
        return None
    pdest = dest.with_name(dest.stem + ".prompt.txt")
    pact = place(prompt_src, psha, pdest, rel, "prompt.txt", errors)
    if pact is None:
        return None
    echo(f"{act:14s} {posix(dest.relative_to(out))}  (take {take_no:03d}, {pid}, {rev})")
    echo(f"{pact:14s} {posix(pdest.relative_to(out))}  (prompt.txt sha {psha[:12]})")
    res = {"char": item["char"], "kind": item["kind"], "rev": rev, "pid": pid, "take": item["take"],
           "rec": rec, "prompt_src": prompt_src, "prompt_text": ptext,
           "entry": {"file": posix(dest.relative_to(out)), "prompt_id": pid, "rev": rev, "sha256": sha,
                     "prompt_file": posix(pdest.relative_to(out)), "prompt_sha256": psha,
                     "source_png": posix(item["png"]), "receipt": posix(item["receipt"])}}
    if not item.get("same_rev_superseded"):
        check_against_queue(res, qmap.get(pid), errors)
    return res


def load_queue(kind: str, lib: Path, queues: list[Path], errors: list[str]) -> list[dict[str, Any]]:
    """Queue của loại `kind` ứng với rev của `lib` (queue-<rev>.json; không có thì mọi queue).

    Brief từng prompt lấy từ `<batch_id>.json` cạnh file queue; kiểm sha brief == queue.prompt_sha256."""
    rev = rev_of(lib)
    cands = [q for q in queues if q.stem == f"queue-{rev}"] or queues
    out: dict[str, dict[str, Any]] = {}
    for qpath in cands:
        raw = json.loads(qpath.read_text(encoding="utf-8"))
        briefs: dict[str, dict[str, str]] = {}
        for x in sorted(raw, key=lambda e: e["prompt_id"]):
            if x.get("kind") != kind:
                continue
            check_prompt_id(x["prompt_id"])
            check_char(x.get("char"))
            bid = check_batch(x["batch_id"])
            if bid not in briefs:
                bf = contained(qpath.parent / f"{bid}.json", qpath.parent, "batch file")
                briefs[bid] = {}
                if bf.is_file():
                    for p in json.loads(bf.read_text(encoding="utf-8")):
                        briefs[bid][p["prompt_id"]] = p["prompt_text"]
                else:
                    errors.append(f"queue {rev} {bid}: thiếu batch file {posix(bf)}")
            text = briefs[bid].get(x["prompt_id"])
            if text is None:
                errors.append(f"queue {x['prompt_id']}: không có trong batch {bid}.json")
                text = ""
            elif hashlib.sha256(text.encode("utf-8")).hexdigest() != x["prompt_sha256"]:
                errors.append(f"queue {x['prompt_id']}: sha256 brief lệch queue.prompt_sha256")
            out[x["prompt_id"]] = {**x, "brief_text": text, "rev": rev, "_batch_dir": qpath.parent}
    if not out:
        errors.append(f"queue {[posix(q) for q in cands]} không có mục kind {kind}")
    return [out[k] for k in sorted(out)]
