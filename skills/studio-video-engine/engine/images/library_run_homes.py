"""N87/N97: khoá codex_home dùng chung giữa các lane (tách khỏi ``library_run`` để mỗi file < 400 dòng, không đổi hành vi)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import pool
from .lease import read_holder
from .library_status import lock_held


def shared_home_locks(plan: dict[str, Any], pool_state: str | None) -> dict[str, list[str]]:
    """Nhãn nào (machine.json + plan) đang giữ khoá nhãn trên một codex_home mà plan dùng: THÔNG TIN, không chặn.

    Việc chặn (holder không mang dấu N87) nằm ở ``home_conflicts`` / ``require_n87_homes``."""
    if not pool_state:
        return {}
    machine = read_json(Path(plan["machine"]))
    homes = {Path(lane["codex_home"]).resolve().as_posix() for lane in plan["lanes"]}
    labels: dict[str, set[str]] = {}
    for account in pool.accounts_from(machine if isinstance(machine, dict) else {}, None):
        labels.setdefault(account.codex_home.resolve().as_posix(), set()).add(account.label)
    for lane in plan["lanes"]:
        labels.setdefault(Path(lane["codex_home"]).resolve().as_posix(), set()).add(lane["label"])
    held = {}
    for home in sorted(homes):
        busy = [label for label in sorted(labels.get(home, ())) if lock_held(pool.label_lock_path(Path(pool_state), label))]
        if busy:
            held[home] = busy
    return held


N87_MARKER_SUFFIX = ".n87.json"


def _home_labels(plan: dict[str, Any]) -> dict[str, set[str]]:
    """codex_home (đã resolve) -> mọi nhãn (machine.json + plan) trỏ vào home đó, giới hạn ở home mà plan dùng."""
    machine = read_json(Path(plan["machine"]))
    labels: dict[str, set[str]] = {}
    for account in pool.accounts_from(machine if isinstance(machine, dict) else {}, None):
        labels.setdefault(account.codex_home.resolve().as_posix(), set()).add(account.label)
    for lane in plan["lanes"]:
        labels.setdefault(Path(lane["codex_home"]).resolve().as_posix(), set()).add(lane["label"])
    homes = {Path(lane["codex_home"]).resolve().as_posix() for lane in plan["lanes"]}
    return {home: labels[home] for home in sorted(homes)}


def n87_marker_path(lock: Path, pid: int | None = None) -> Path:
    """Marker cạnh khoá nhãn. ``pid`` cho trước => marker RIÊNG của tiến trình đó (lane anh em không ghi đè nhau, N97);
    ``pid=None`` là tên cũ (engine trước N97), vẫn được chấp nhận khi xác thực."""
    lock = Path(lock)
    return lock.with_name(lock.name + (f".n87.{int(pid)}.json" if pid is not None else N87_MARKER_SUFFIX))


def engine_marker(plan_path: Path | None, plan: dict[str, Any], label: str, home: str) -> dict[str, Any]:
    """Dấu của tiến trình này: có N87 (nhặt ảnh theo phiên của chính run) hay không, bản engine, pid, plan."""
    from . import codex_run  # import muộn: tránh vòng import lúc nạp module

    version = sha256_file(Path(codex_run.__file__))[:12]
    return {"n87": callable(getattr(codex_run, "own_session", None)), "engine_version": version, "pid": os.getpid(),
            "plan": Path(plan_path).resolve().as_posix() if plan_path else None, "plan_rev": plan.get("rev"),
            "label": label, "codex_home": home}


def write_n87_markers(plan_path: Path, plan: dict[str, Any], pool_state: str | None, label: str) -> list[Path]:
    """Lane ghi dấu N87 cạnh khoá nhãn của MỌI nhãn cùng codex_home (failover có thể lấy khoá nhãn khác).

    Tên marker mang pid của lane ghi => marker của lane anh em không bị ghi đè; xác thực so pid với .holder (N97)."""
    if not pool_state:
        return []
    lane = next(l for l in plan["lanes"] if l["label"] == label)
    home = Path(lane["codex_home"]).resolve().as_posix()
    written = []
    for name in sorted(_home_labels(plan).get(home, {label})):
        target = n87_marker_path(pool.label_lock_path(Path(pool_state), name), os.getpid())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(engine_marker(plan_path, plan, name, home), ensure_ascii=True), encoding="ascii")
        written.append(target)
    return written


def clear_n87_markers(paths: list[Path]) -> None:
    for path in paths:
        try:
            data = json.loads(Path(path).read_text(encoding="ascii"))
            if isinstance(data, dict) and data.get("pid") == os.getpid():
                Path(path).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def home_conflicts(plan: dict[str, Any], pool_state: str | None) -> list[dict[str, Any]]:
    """Home mà một tiến trình KHÁC đang giữ khoá nhãn nhưng khoá không mang dấu N87 hợp lệ (fail closed, spec §2).

    Khoá OS nhả khi tiến trình chết => khoá "mồ côi" không bao giờ bị tính là đang giữ (lock_held=False)."""
    if not pool_state:
        return []
    out = []
    for home, names in _home_labels(plan).items():
        for name in sorted(names):
            lock = pool.label_lock_path(Path(pool_state), name)
            if not lock_held(lock):
                continue
            holder = read_holder(lock)
            pid = holder.get("pid") if holder else None
            marker = None
            for candidate in ((n87_marker_path(lock, pid),) if pid is not None else ()) + (n87_marker_path(lock),):
                try:
                    found = json.loads(candidate.read_text(encoding="ascii"))
                except (OSError, ValueError):
                    continue
                marker = found if marker is None else marker
                if isinstance(found, dict) and found.get("pid") == pid:
                    marker = found  # ưu tiên marker đúng pid của holder
                    break
            if (isinstance(marker, dict) and marker.get("n87") is True and pid is not None and marker.get("pid") == pid
                    and marker.get("codex_home") == home):
                continue
            reason = ("holder unknown (no .holder record)" if pid is None else
                      "lock has no N87 marker (old engine?)" if marker is None else
                      "N87 marker is not valid for this holder")
            out.append({"codex_home": home, "label": name, "holder_pid": pid, "reason": reason, "lock": lock.as_posix()})
    return out


def require_n87_homes(plan: dict[str, Any], pool_state: str | None) -> None:
    conflicts = home_conflicts(plan, pool_state)
    if conflicts:
        text = "; ".join(f"codex_home {c['codex_home']} label {c['label']} held by pid {c['holder_pid']}: {c['reason']}" for c in conflicts)
        raise Refused(f"refusing to share a CODEX_HOME with a holder that is not a verified N87 engine (spec 2): {text}; "
                      "wait for it to exit or use a separate codex_home")
