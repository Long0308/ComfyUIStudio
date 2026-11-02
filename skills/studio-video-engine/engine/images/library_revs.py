"""Shared library revision metadata and canonical image-key ownership.

Libraries are ordered oldest to newest. Each (character, kind, prompt number)
is owned by the newest library containing an image receipt for that key.
Revision suffix chains and descriptive prompt labels do not change the key.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any, Optional

from ..core.errors import Refused

KINDS = ("FACE", "ACTION")
# Hậu tố một chữ thường (batch-02f) = bản làm lại của batch-02: THẮNG batch không hậu tố cùng khóa prompt.
BATCH_RE = re.compile(r"^batch-(\d+)(?:[a-z])?-(CHAR_\d+)-(FACE|ACTION)$")
_SUFFIX_RE = re.compile(r"^batch-\d+([a-z])?-")
TAKE_RE = re.compile(r"^t(\d+)$")
PNG_RE = re.compile(r"^([0-9a-f]{12})\.png$")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHAR_ID_RE = re.compile(r"^CHAR_\d{2}$")
KEY_RE = re.compile(r"^(CHAR_\d+)_(FACE|ACTION)_(\d{2})(?:_|$)")
BATCH_ID_RE = re.compile(r"^batch-\d{2}[a-z]?-CHAR_\d{2}-(FACE|ACTION)$")


def batch_rank(name: str) -> int:
    """0 cho batch-NN, 1..26 cho hậu tố a..z: cùng thư viện, hậu tố lớn hơn = bản mới hơn."""
    m = _SUFFIX_RE.match(name)
    return ord(m.group(1)) - 96 if m and m.group(1) else 0


def check_char(value: Any) -> str:
    """Id nhân vật thành tên thư mục: chỉ ``CHAR_NN``."""
    if not isinstance(value, str) or not CHAR_ID_RE.fullmatch(value):
        raise Refused(f"character id {value!r} is not allowed: expected CHAR_NN (it names a folder)")
    return value


def check_batch(value: Any) -> str:
    """Batch id thành tên file: chỉ ``batch-NN-CHAR_NN-(FACE|ACTION)``."""
    if not isinstance(value, str) or not BATCH_ID_RE.fullmatch(value):
        raise Refused(f"batch_id {value!r} is not allowed: expected batch-NN[a-z]-CHAR_NN-(FACE|ACTION)")
    return value


def contained(path: Path, root: Path, what: str = "path") -> Path:
    """Refuse nếu `path` (đã resolve) nằm ngoài `root` (đã resolve); trả path đã resolve."""
    rp, rr = Path(path).resolve(), Path(root).resolve()
    if rp != rr and rr not in rp.parents:
        raise Refused(f"{what} {str(path)!r} escapes {str(root)!r}")
    return rp


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def rev_of(lib: Path) -> str:
    """`library-r005c` -> `r005c`; tên khác giữ nguyên."""
    m = re.match(r"^library-(.+)$", lib.name)
    return m.group(1) if m else lib.name


def has_kind(lib: Path, kind: str) -> bool:
    if not lib.is_dir():
        return False
    for bd in lib.iterdir():
        m = BATCH_RE.match(bd.name) if bd.is_dir() else None
        if m and m.group(3) == kind:
            return True
    return False


def resolve_revs(libs: list[Path], kinds: tuple[str, ...] = KINDS) -> dict[str, dict[str, Any]]:
    """{kind: {"current": Path|None, "older": [Path,...]}} theo thứ tự `libs` (cũ -> mới).

    Mức LOẠI chỉ để đặt tên (rev mới nhất của loại, danh sách rev cũ); chọn ảnh hiện hành dùng `classify`."""
    out: dict[str, dict[str, Any]] = {}
    for kind in kinds:
        have = [lib for lib in libs if has_kind(lib, kind)]
        out[kind] = {"current": have[-1] if have else None, "older": have[:-1]}
    return out


def key_of(pid: Any) -> Optional[tuple[str, str, str]]:
    """prompt_id -> (char, kind, NN); sai dạng -> None. Hậu tố rev (_r005b...) không ảnh hưởng khóa."""
    m = KEY_RE.match(pid) if isinstance(pid, str) else None
    return (m.group(1), m.group(2), m.group(3)) if m else None


def receipt_key(receipt: Path) -> Optional[tuple[str, str, str]]:
    """Khóa của một receipt (đọc prompt_id); không đọc được -> None."""
    try:
        rec = json.loads(receipt.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return key_of(rec.get("prompt_id") if isinstance(rec, dict) else None)


def keyed_images(lib: Path, kind: str) -> list[tuple[str, tuple[str, str, str], int]]:
    """[(sha12, key)] của PNG có receipt đọc được trong batch loại `kind` của `lib`."""
    out: list[tuple[str, tuple[str, str, str], int]] = []
    if not lib.is_dir():
        return out
    for bd in sorted(lib.iterdir()):
        bm = BATCH_RE.match(bd.name) if bd.is_dir() else None
        if not bm or bm.group(3) != kind:
            continue
        for td in sorted(bd.iterdir()):
            for png in sorted(td.glob("*.png")) if td.is_dir() and TAKE_RE.match(td.name) else []:
                key = receipt_key(td / (png.stem + ".receipt.json"))
                if PNG_RE.match(png.name) and key:
                    out.append((png.stem, key, batch_rank(bd.name)))
    return out


def classify(libs: list[Path], kinds: tuple[str, ...] = KINDS) -> dict[str, dict[str, Any]]:
    """Theo khóa: {kind: {"owner": {key: idx lib thắng}, "current_sha": set, "superseded_sha": {idx: set}}}."""
    out: dict[str, dict[str, Any]] = {}
    for kind in kinds:
        entries = [(i, s12, key, r) for i, lib in enumerate(libs) for s12, key, r in keyed_images(lib, kind)]
        rank: dict[tuple[str, str, str], tuple[int, int]] = {}
        for i, _, key, r in entries:
            rank[key] = max(rank.get(key, (-1, 0)), (i, r))
        owner = {k: v[0] for k, v in rank.items()}
        cur: set[str] = {s for i, s, k, r in entries if rank[k] == (i, r)}
        sup: dict[int, set[str]] = {}
        for i, s, k, r in entries:
            if rank[k] != (i, r):
                sup.setdefault(i, set()).add(s)
        out[kind] = {"owner": owner, "owner_rank": rank, "current_sha": cur, "superseded_sha": sup}
    return out


def owns(cls_kind: dict[str, Any], key: tuple[str, str, str], idx: int, batch: str) -> bool:
    """Take của batch `batch` trong thư viện thứ `idx` có là ảnh hiện hành của `key` không."""
    return cls_kind["owner_rank"].get(key) == (idx, batch_rank(batch))


def owner_idx(cls_kind: dict[str, Any], key: tuple[str, str, str]) -> Optional[int]:
    return cls_kind["owner"].get(key)


def png_sha12s(src: Path, kind: str) -> set[str]:
    """Mọi PNG sha12 trong batch loại `kind` của thư viện (không cần receipt)."""
    out: set[str] = set()
    if not src.is_dir():
        return out
    for bd in src.iterdir():
        bm = BATCH_RE.match(bd.name) if bd.is_dir() else None
        if not bm or bm.group(3) != kind:
            continue
        for td in bd.iterdir():
            if td.is_dir() and TAKE_RE.match(td.name):
                for png in td.glob("*.png"):
                    pm = PNG_RE.match(png.name)
                    if pm:
                        out.add(pm.group(1))
    return out


def png_size(p: Path) -> Optional[tuple[int, int]]:
    with p.open("rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != PNG_SIG:
        return None
    return struct.unpack(">II", head[16:24])


def parse_ratio(text: str) -> tuple[int, int]:
    """'3:4' -> (3, 4)."""
    a, b = text.split(":")
    return int(a), int(b)


def matches_canvas(size: Optional[tuple[int, int]], ratio: tuple[int, int]) -> bool:
    return bool(size) and size[0] * ratio[1] == size[1] * ratio[0]


def split_paths(values: Optional[list[str]]) -> list[Path]:
    """Nhận danh sách lặp lại hoặc chuỗi phân tách bằng dấu phẩy (DIR[,DIR2])."""
    res: list[Path] = []
    for v in values or []:
        res += [Path(x) for x in str(v).split(",") if x]
    return res
