"""Fixture thư viện ảnh nhỏ (2 rev) cho test `library view|review`."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_bytes(w: int, h: int, salt: str = "") -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"k\x00" + salt.encode()) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def add_take(lib: Path, batch: str, take: str, pid: str, size: tuple[int, int], *, receipt: bool = True) -> str:
    """Tạo 1 take (PNG + prompt.txt [+ receipt]); trả sha12."""
    td = lib / batch / take
    td.mkdir(parents=True, exist_ok=True)
    png = png_bytes(*size, salt=pid + str(size))
    sha = hashlib.sha256(png).hexdigest()
    (td / f"{sha[:12]}.png").write_bytes(png)
    prompt = f"prompt of {pid}\r\nline2\n".encode()
    (td / "prompt.txt").write_bytes(prompt)
    if receipt:
        brief_sha = hashlib.sha256(f"brief {pid}".encode()).hexdigest()
        rec = {"prompt_id": pid, "batch_id": batch, "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
               "prompt_text_sha256": brief_sha, "account_label": "acct1",
               "ref_hashes": [{"role": "identity", "path": "ref.png", "sha256": "ab" * 32}]}
        (td / f"{sha[:12]}.receipt.json").write_text(json.dumps(rec), encoding="utf-8")
    return sha[:12]


def write_queue(bdir: Path, rev: str, entries: list[tuple[str, str, str, str]]) -> Path:
    """entries = (prompt_id, char, kind, batch_id). Ghi batch JSON + queue-<rev>.json trong bdir."""
    bdir.mkdir(parents=True, exist_ok=True)
    batches: dict[str, list[dict[str, Any]]] = {}
    queue = []
    for pid, char, kind, bid in entries:
        text = f"brief {pid}"
        batches.setdefault(bid, []).append({"prompt_id": pid, "prompt_text": text})
        queue.append({"prompt_id": pid, "char": char, "kind": kind, "batch_id": bid,
                      "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(), "account": "acct1",
                      "ref_images": [{"role": "identity", "path": "ref.png", "sha256": "ab" * 32}]})
    for bid, rows in batches.items():
        (bdir / f"{bid}.json").write_text(json.dumps(rows), encoding="utf-8")
    q = bdir / f"queue-{rev}.json"
    q.write_text(json.dumps(queue), encoding="utf-8")
    return q


FACE1 = "CHAR_01_FACE_01_NEUTRAL_r001"
ACT1 = "CHAR_01_ACTION_01_WAVE_r001"
ACT2 = "CHAR_01_ACTION_02_POINT_r001"
ACT3 = "CHAR_01_ACTION_03_SIT_r001"


def build(root: Path) -> dict[str, Any]:
    """lib r001: FACE01 + ACTION01 (16:9). lib r002: ACTION01 + ACTION02 (3:4) + 1 PNG chưa receipt (16:9);
    ACTION03 chỉ có trong queue."""
    r1, r2 = root / "library-r001", root / "library-r002"
    s = {"face": add_take(r1, "batch-01-CHAR_01-FACE", "t001", FACE1, (30, 40)),
         "act_old": add_take(r1, "batch-02-CHAR_01-ACTION", "t001", ACT1, (32, 18)),
         "act1": add_take(r2, "batch-02-CHAR_01-ACTION", "t001", ACT1, (30, 40)),
         "act2": add_take(r2, "batch-02-CHAR_01-ACTION", "t002", ACT2, (60, 80)),
         "pend": add_take(r2, "batch-02-CHAR_01-ACTION", "t003", ACT3, (32, 18), receipt=False)}
    q1 = write_queue(root / "b1", "r001", [(FACE1, "CHAR_01", "FACE", "batch-01-CHAR_01-FACE"),
                                           (ACT1, "CHAR_01", "ACTION", "batch-02-CHAR_01-ACTION")])
    q2 = write_queue(root / "b2", "r002", [(a, "CHAR_01", "ACTION", "batch-02-CHAR_01-ACTION")
                                           for a in (ACT1, ACT2, ACT3)])
    return {"r1": r1, "r2": r2, "q1": q1, "q2": q2, "sha": s, "root": root}


def build_partial(root: Path, *, replacement: str = "CHAR_01_FACE_01_NEUTRAL_r001_r002") -> dict[str, Any]:
    """Four r1 keys; r2 replaces FACE_01 using a chained revision suffix."""
    r1, r2 = root / "library-r001", root / "library-r002"
    face_batch, action_batch = "batch-01-CHAR_01-FACE", "batch-02-CHAR_01-ACTION"
    pids = [FACE1, "CHAR_01_FACE_02_SMILE_r001", ACT1, ACT2]
    rows = [(pid, "CHAR_01", kind, batch) for pid, kind, batch in
            [(pids[0], "FACE", face_batch), (pids[1], "FACE", face_batch),
             (pids[2], "ACTION", action_batch), (pids[3], "ACTION", action_batch)]]
    shas = [add_take(r1, batch, f"t{i % 2 + 1:03d}", pid, (30, 40))
            for i, (pid, _, _, batch) in enumerate(rows)]
    new_sha = add_take(r2, face_batch, "t001", replacement, (30, 40))
    q1 = write_queue(root / "b1", "r001", rows)
    q2 = write_queue(root / "b2", "r002", [(replacement, "CHAR_01", "FACE", face_batch)])
    return {"r1": r1, "r2": r2, "q1": q1, "q2": q2, "pids": pids,
            "replacement": replacement, "shas": shas, "new_sha": new_sha}
