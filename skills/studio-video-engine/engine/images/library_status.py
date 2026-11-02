"""Tiếp tục (resume) và tiến độ cho ``jjv images library run|status`` (N89-P0).

Ba việc, không mạng, không gọi codex, không đọc token: (1) prompt_id nào đã có take HỢP LỆ trong ``--library-out``
(receipt ``jjv/library-image-receipt/v1`` + PNG đúng bytes + đúng prompt sha của queue), (2) nhật ký sự kiện từng lane
(``<run>/lanes/<label>.jsonl``: LANE_START, START, EXIT, LANE_STOP|LANE_DONE) và khoá OS của lane (lane còn sống = khoá
đang bị giữ), (3) ``<plan>.status.json`` gộp theo lane và theo nhân vật/kind, ETA = giây/ảnh đo được.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

from ..core.errors import Refused
from ..core.filelock import run_lock
from ..core.io import read_json, sha256_file, write_json_atomic
from . import pool
from .codex import LIBRARY_RECEIPT_SCHEMA
from .lease import read_holder
from .library_revs import png_size

STATUS_SCHEMA = "jjv/images-library-status/v1"
TERMINAL = {"LANE_DONE": "done", "LANE_STOP": "stopped"}


def status_path(plan_path: Path) -> Path:
    plan_path = Path(plan_path)
    return plan_path.with_name(f"{plan_path.stem}.status.json")


def runs_dir(plan_path: Path) -> Path:
    plan_path = Path(plan_path)
    return plan_path.with_name(f"{plan_path.stem}.runs")


def latest_run_dir(plan_path: Path) -> Path | None:
    folder = runs_dir(plan_path)
    runs = sorted(p for p in folder.iterdir() if p.is_dir() and (p / "run.json").is_file()) if folder.is_dir() else []
    return runs[-1] if runs else None


def lock_held(path: Path) -> bool:
    """Probe 0 giây trên khoá OS (không ghi holder): True khi tiến trình khác đang giữ."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with run_lock(path, timeout_seconds=0):
            return False
    except Refused:
        return True


# --- take đã có ---------------------------------------------------------------------------------------------

def receipts_in(library_out: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Mọi receipt thư viện dưới ``DIR/<batch>/<take>/`` (bỏ ``_review``); file lạ hoặc hỏng bị bỏ qua."""
    for path in sorted(Path(library_out).glob("*/*/*.receipt.json")):
        if path.parts[-3].startswith("_"):
            continue
        try:
            row = read_json(path)
        except Exception:  # noqa: BLE001 - một file lạ không phải take
            continue
        if isinstance(row, dict) and row.get("schema") == LIBRARY_RECEIPT_SCHEMA and isinstance(row.get("prompt_id"), str):
            yield path, row


def take_valid(row: dict[str, Any], wanted_sha: str | None, *, verify_bytes: bool) -> bool:
    """PNG còn đó và đúng receipt (hash đủ khi ``verify_bytes``, nếu không thì kích thước), prompt sha khớp queue khi cả hai biết."""
    output = row.get("output") or {}
    png, sha = Path(str(output.get("path") or "")), output.get("sha256")
    if not png.is_file() or not isinstance(sha, str):
        return False
    if verify_bytes:
        if sha256_file(png) != sha:
            return False
    elif isinstance(output.get("bytes"), int) and png.stat().st_size != output["bytes"]:
        return False
    recorded = row.get("prompt_text_sha256")
    return not (wanted_sha and recorded and str(recorded).lower() != str(wanted_sha).lower())


def done_takes(library_out: Path | str | None, wanted: dict[str, str | None], *, verify_bytes: bool) -> dict[str, dict[str, Any]]:
    """``{prompt_id: {receipt, png, sha256}}`` cho các id trong ``wanted`` (id -> prompt sha của queue) đã có take hợp lệ."""
    if not library_out or not Path(library_out).is_dir():
        return {}
    found: dict[str, dict[str, Any]] = {}
    for path, row in receipts_in(Path(library_out)):
        pid = row["prompt_id"]
        if pid in wanted and pid not in found and take_valid(row, wanted.get(pid), verify_bytes=verify_bytes):
            found[pid] = {"receipt": path.as_posix(), "png": row["output"]["path"], "sha256": row["output"]["sha256"]}
    return found


def canvas_flags(plan: dict[str, Any], done: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Take đã xong mà header PNG lệch khung của kind (``plan["canvas"]`` = ``{kind: "W:H"}``); PNG không đọc được cũng bị cờ."""
    canvas = plan.get("canvas") or {}
    flags = []
    for batch in plan["batches"].values():
        for item in batch["items"]:
            ratio, take = canvas.get(item.get("kind")), done.get(item["prompt_id"])
            if not ratio or not take:
                continue
            w, h = (int(x) for x in ratio.split(":"))
            try:
                size = png_size(Path(take["png"]))
            except OSError:
                size = None
            if not size or size[0] * h != size[1] * w:
                flags.append({"prompt_id": item["prompt_id"], "kind": item["kind"], "size": list(size) if size else None, "expected": ratio})
    return flags


def wanted_of(plan: dict[str, Any]) -> dict[str, str | None]:
    return {item["prompt_id"]: item.get("prompt_sha256") for batch in plan["batches"].values() for item in batch["items"]}


# --- sự kiện lane --------------------------------------------------------------------------------------------

def lane_dir(run_dir: Path) -> Path:
    return Path(run_dir) / "lanes"


def events_path(run_dir: Path, label: str) -> Path:
    return lane_dir(run_dir) / f"{label}.jsonl"


def lane_lock_path(run_dir: Path, label: str) -> Path:
    return lane_dir(run_dir) / f"{label}.lock"


def append_event(run_dir: Path, label: str, event: dict[str, Any]) -> dict[str, Any]:
    """Một dòng JSON mỗi sự kiện, chỉ lane đó ghi (append)."""
    row = {"at": time.time(), **event}
    path = events_path(run_dir, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=True) + "\n")
    return row


def lane_events(run_dir: Path, label: str) -> list[dict[str, Any]]:
    path = events_path(run_dir, label)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text("utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # dòng cuối đang ghi dở
    return rows


def lane_state(events: list[dict[str, Any]], active: bool, *, launched: bool = False) -> tuple[str, str | None]:
    if not events:
        if active:
            return "running", None
        if launched:
            return "dead", "process ended before LANE_START"
        return "pending", None
    last = events[-1]
    if last.get("event") in TERMINAL:
        return TERMINAL[last["event"]], last.get("reason")
    return ("running", None) if active else ("dead", "process ended without LANE_DONE/LANE_STOP")


def launch_record_path(run_dir: Path, label: str) -> Path:
    return lane_dir(run_dir) / f"{label}.launched.json"


def write_launch_record(run_dir: Path, label: str, pid: int) -> Path:
    """Dấu "đã spawn" do tiến trình CHA ghi (lease.py gỡ .holder khi lane thoát, nên .holder không chứng minh được việc đã chạy)."""
    path = launch_record_path(run_dir, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": int(pid), "at": time.time()}), encoding="ascii")
    return path


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION; WAIT_TIMEOUT (0x102) = still running.
        # Not exit code == 259: a process that exited with code 259 would read as alive (CR-N95N97).
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000 | 0x1000, False, int(pid))
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def lane_launched(run_dir: Path, label: str) -> bool:
    """True khi lane đã được spawn và tiến trình con đã chết mà chưa có sự kiện nào (dead, không phải pending).

    Nguồn: .holder (chết đột ngột còn sót) HOẶC dấu launch của cha có pid con không còn sống. Con còn sống mà chưa lấy khoá
    (đang khởi động) => chưa phải launched-and-dead."""
    if read_holder(lane_lock_path(run_dir, label)) is not None:
        return True
    try:
        data = json.loads(launch_record_path(run_dir, label).read_text(encoding="ascii"))
    except (OSError, ValueError):
        return False
    pid = data.get("pid") if isinstance(data, dict) else None
    return isinstance(pid, int) and not pid_alive(pid)


def batch_rows(batches: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Một dòng mỗi batch của lane: complete (bỏ qua vì đã đủ take) | pending | running | ok | failed."""
    starts = {e.get("batch_id"): e for e in events if e.get("event") == "START"}
    exits = {e.get("batch_id"): e for e in events if e.get("event") == "EXIT"}
    rows = []
    for batch in batches:
        bid = batch["batch_id"]
        start, exit_ = starts.get(bid), exits.get(bid)
        if batch.get("state") == "complete":
            state = "complete"
        elif start is None:
            state = "pending"
        elif exit_ is None:
            state = "running"
        else:
            state = "ok" if exit_.get("ok") else "failed"
        rows.append({"batch_id": bid, "state": state, "items": len(batch.get("remaining") or batch.get("prompt_ids") or []),
                     "images": int((exit_ or {}).get("images") or 0), "reason": (exit_ or {}).get("reason"),
                     "started_at": (start or {}).get("at"), "ended_at": (exit_ or {}).get("at")})
    return rows


def measure(events: list[dict[str, Any]]) -> tuple[float, int]:
    """``(giây có ảnh, số ảnh)`` của lane: chỉ batch đã EXIT với >= 1 ảnh."""
    starts = {e.get("batch_id"): e["at"] for e in events if e.get("event") == "START"}
    seconds, images = 0.0, 0
    for event in events:
        if event.get("event") == "EXIT" and int(event.get("images") or 0) > 0 and event.get("batch_id") in starts:
            seconds += float(event["at"]) - float(starts[event["batch_id"]])
            images += int(event["images"])
    return seconds, images


# --- status gộp ----------------------------------------------------------------------------------------------

def build_status(plan_path: Path, plan: dict[str, Any], run_dir: Path | None, run: dict[str, Any] | None,
                 library_out: Path | str | None, *, verify_bytes: bool = False) -> dict[str, Any]:
    wanted = wanted_of(plan)
    done = done_takes(library_out, wanted, verify_bytes=verify_bytes)
    characters: dict[str, dict[str, dict[str, int]]] = {}
    for batch in plan["batches"].values():
        for item in batch["items"]:
            cell = characters.setdefault(item.get("char") or "UNKNOWN", {}).setdefault(item.get("kind") or "UNKNOWN",
                                                                                         {"wanted": 0, "done": 0})
            cell["wanted"] += 1
            cell["done"] += int(item["prompt_id"] in done)
    lanes, seconds, images, active = [], 0.0, 0, 0
    for lane in plan["lanes"]:
        label = lane["label"]
        events = lane_events(run_dir, label) if run_dir else []
        alive = lane_active(run_dir, label) if run_dir else False
        launched = lane_launched(run_dir, label) if run_dir else False
        state, reason = lane_state(events, alive, launched=launched)
        planned = ((run or {}).get("lanes") or {}).get(label, {}).get("batches") or [{"batch_id": b} for b in lane["batches"]]
        rows = batch_rows(planned, events)
        lane_seconds, lane_images = measure(events)
        seconds, images, active = seconds + lane_seconds, images + lane_images, active + int(state == "running")
        lanes.append({"label": label, "account": lane["account"], "variant": lane["variant"], "state": state, "reason": reason,
                      "images": sum(r["images"] for r in rows), "batches": rows,
                      "seconds_per_image": (lane_seconds / lane_images) if lane_images else None})
    total_wanted, total_done = len(wanted), len(done)
    remaining = total_wanted - total_done
    spi = (seconds / images) if images else None
    return {"schema": STATUS_SCHEMA, "updated_at": time.time(), "plan": Path(plan_path).resolve().as_posix(), "rev": plan.get("rev"),
            "run_dir": Path(run_dir).resolve().as_posix() if run_dir else None, "library_out": str(library_out) if library_out else None,
            "lanes": lanes, "lanes_active": active, "characters": characters, "canvas_flags": canvas_flags(plan, done),
            "totals": {"wanted": total_wanted, "done": total_done, "remaining": remaining},
            "measured": {"seconds_per_image": spi, "images_timed": images},
            "eta_seconds": (remaining * spi / active) if (spi and active and remaining) else None}


def lane_active(run_dir: Path, label: str) -> bool:
    return lock_held(lane_lock_path(run_dir, label))


def refresh_status(plan_path: Path, plan: dict[str, Any], run_dir: Path | None, run: dict[str, Any] | None,
                   library_out: Path | str | None, *, verify_bytes: bool = False) -> dict[str, Any]:
    """Tính lại từ file và ghi ``<plan>.status.json`` (atomic, dưới khoá ngắn: nhiều lane cùng ghi không mất nhau)."""
    status = build_status(plan_path, plan, run_dir, run, library_out, verify_bytes=verify_bytes)
    target = status_path(plan_path)
    with pool.locked(target.with_suffix(".lock"), timeout_seconds=10.0, what="library status lock"):
        write_json_atomic(target, status, mode="ascii")
    return status
