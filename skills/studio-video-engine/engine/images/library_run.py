"""``jjv images library run|lane|status`` (N89-P0): chạy plan thư viện, mỗi lane một tiến trình con, resume-safe.

``run`` đọc plan, bỏ prompt_id đã có take hợp lệ trong ``library_out`` (``library_status.done_takes``, hash đủ bytes),
ghi file batch ĐÃ LỌC + bản sao mọi ``queue-*.json`` vào ``<plan>.runs/<stamp>/batches/`` (cổng queue N52 giữ nguyên vì
queue nằm cạnh batch) rồi spawn ``jjv images library lane`` cho từng lane. Lane chạy tuần tự từng batch bằng ĐÚNG đường
CLI ``images submit --provider codex-exec --prompt-batch B --library-out L --account <label> [--codex-account
<label>=<home>]`` (argparse thật + ``run_images``: không nhân bản logic submit); batch lỗi (quota/auth/cooling/timeout/
refused) => dừng lane, ghi lý do, lane khác chạy tiếp. ``status`` chỉ đọc file. machine.json không bao giờ bị ghi.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable

from ..config.loader import SKILL_ROOT
from ..core.errors import EngineError, Failed, Refused, Uncertain, exit_code_for
from ..core.winflags import no_window
from ..core.io import read_json, sha256_bytes, sha256_file, write_json_once, write_once
from . import codex_queue, library_plan, library_review, library_revs, library_view, pool
from .library_run_homes import (N87_MARKER_SUFFIX, _home_labels, clear_n87_markers, engine_marker, home_conflicts,  # noqa: F401
                                n87_marker_path, require_n87_homes, shared_home_locks, write_n87_markers)
from .library_run_support import _carry_ownership, _copy_queues, _write_filtered_batch, referenced_queues  # noqa: F401
from .library_status import (append_event, done_takes, lane_active, lane_lock_path, latest_run_dir, lock_held, refresh_status,
                             runs_dir, status_path, wanted_of, write_launch_record)

RUN_SCHEMA = "jjv/images-library-run/v1"
JJV = SKILL_ROOT / "bin" / "jjv.py"
BELOW_NORMAL, DETACHED, NEW_GROUP = 0x4000, 0x8, 0x200  # Windows creation flags


def resolve_context(plan: dict[str, Any], *, episode: str | None = None, machine: str | None = None,
                    library_out: str | None = None, pool_out: str | None = None, pool_state: str | None = None,
                    codex_bin: str | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Giá trị của ``run`` thắng giá trị trong plan; ``missing`` liệt kê thứ một run thật còn thiếu."""
    machine_path = Path(machine or plan["machine"])
    ctx: dict[str, Any] = {"episode": episode or plan.get("episode"), "machine": machine_path.as_posix(),
                           "library_out": library_out or plan.get("library_out"), "pool_out": pool_out or plan.get("pool_out"),
                           "codex_bin": codex_bin or plan.get("codex_bin"),
                           "timeout": timeout if timeout is not None else plan.get("timeout")}
    state = pool_state or (None if pool_out else plan.get("pool_state"))
    if not state and ctx["pool_out"]:
        machine_doc = read_json(machine_path)
        found = library_plan.resolve_pool_state(None, machine_doc if isinstance(machine_doc, dict) else {}, ctx["pool_out"])
        state = found.as_posix() if found else None
    ctx["pool_state"] = Path(state).as_posix() if state else None
    ctx["missing"] = [key for key in ("episode", "library_out", "pool_out") if not ctx[key]]
    return ctx


def submit_argv(ctx: dict[str, Any], lane: dict[str, Any], batch_file: str) -> list[str]:
    """argv của ``jjv images submit`` cho một batch của lane (lane phụ mang ``--codex-account``)."""
    shown = {k: (v if v else f"<{k}>") for k, v in ctx.items()}
    argv = ["submit", "--episode", str(shown["episode"]), "--out", str(shown["pool_out"]), "--machine", str(ctx["machine"]),
            "--provider", "codex-exec", "--prompt-batch", str(batch_file), "--library-out", str(shown["library_out"]),
            "--account", lane["label"]]
    if lane.get("variant"):
        argv += ["--codex-account", f"{lane['label']}={lane['codex_home']}"]
    if ctx.get("pool_state"):
        argv += ["--pool-state", str(ctx["pool_state"])]
    if ctx.get("codex_bin"):
        argv += ["--codex-bin", str(ctx["codex_bin"])]
    if ctx.get("timeout") is not None:
        argv += ["--timeout", str(ctx["timeout"])]
    return argv


def lane_work(plan: dict[str, Any], ctx: dict[str, Any], *, verify_bytes: bool) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Mỗi lane: batch -> prompt_ids còn thiếu (resume). ``library_out`` chưa biết => chưa có gì là xong."""
    done = done_takes(ctx.get("library_out"), wanted_of(plan), verify_bytes=verify_bytes)
    work: dict[str, list[dict[str, Any]]] = {}
    for lane in plan["lanes"]:
        rows = []
        for bid in lane["batches"]:
            batch = plan["batches"][bid]
            rows.append({"batch_id": bid, "source": batch["file"], "source_sha256": batch["sha256"], "prompt_ids": batch["prompt_ids"],
                         "done": [p for p in batch["prompt_ids"] if p in done],
                         "remaining": [p for p in batch["prompt_ids"] if p not in done]})
        work[lane["label"]] = rows
    return work, done


def dry_run(plan_path: Path, plan: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    work, done = lane_work(plan, ctx, verify_bytes=True)
    lanes = []
    for lane in plan["lanes"]:
        rows = [{"batch_id": r["batch_id"], "total": len(r["prompt_ids"]), "done": len(r["done"]), "remaining": len(r["remaining"]),
                 "state": "complete" if not r["remaining"] else "pending",
                 "argv": submit_argv(ctx, lane, f"<run-dir>/batches/{r['batch_id']}.json")} for r in work[lane["label"]]]
        lanes.append({"label": lane["label"], "account": lane["account"], "variant": lane["variant"], "codex_home": lane["codex_home"],
                      "batches": rows})
    wanted = len(wanted_of(plan))
    return {"dry_run": True, "plan": Path(plan_path).resolve().as_posix(), "rev": plan.get("rev"), "context": ctx,
            "ready": not ctx["missing"], "lanes": lanes,
            "totals": {"wanted": wanted, "done": len(done), "remaining": wanted - len(done)},
            "shared_home_locks": shared_home_locks(plan, ctx.get("pool_state"))}


def _new_run_dir(plan_path: Path, clock: Callable[[], float]) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
    base = runs_dir(plan_path)
    for suffix in ("", *(f"-{n}" for n in range(2, 100))):
        folder = base / f"{stamp}{suffix}"
        if not folder.exists():
            folder.mkdir(parents=True)
            return folder
    raise Refused(f"cannot create a fresh run folder under {base}")


def spawn_lane(plan_path: Path, run_dir: Path, label: str, *, detach: bool) -> subprocess.Popen:
    argv = [sys.executable, "-I", str(JJV), "images", "library", "lane", "--plan", str(plan_path), "--run-dir", str(run_dir),
            "--lane", label]
    flags = (BELOW_NORMAL | (DETACHED | NEW_GROUP if detach else no_window())) if os.name == "nt" else 0  # DETACHED đã không có console
    extra = {"start_new_session": True} if (detach and os.name != "nt") else {}
    log = run_dir / "logs" / f"lane-{label}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as stream:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, cwd=str(SKILL_ROOT),
                                creationflags=flags, **extra)
    write_launch_record(run_dir, label, proc.pid)  # lane chết trước LANE_START vẫn thấy "dead", không phải "pending" (N97)
    return proc


def view_config(view_out: str | None, libraries: list[str] | None, queues: list[str] | None,
                review_out: str | None) -> dict[str, Any] | None:
    """Cấu hình auto-refresh từ cờ ``run`` (None = không bật). Thiếu đầu vào => Refused ngay, trước khi spawn lane."""
    if not (view_out or review_out):
        return None
    libs = [Path(x).as_posix() for x in library_revs.split_paths(libraries)]
    qs = [Path(x).as_posix() for x in library_revs.split_paths(queues)]
    if not libs:
        raise Refused("--view-out/--review-out need --view-libraries DIR[,DIR...] (oldest -> newest)")
    if view_out and not qs:
        raise Refused("--view-out needs --view-queues Q[,Q...]")
    return {"out": Path(view_out).as_posix() if view_out else None, "libraries": libs, "queues": qs,
            "review_out": Path(review_out).as_posix() if review_out else None}


def refresh_lock_path(cfg: dict[str, Any]) -> Path:
    target = Path(cfg["out"] or cfg["review_out"])
    return target.with_name(target.name + ".refresh.lock")


def _record_refresh(run_dir: Path, entry: dict[str, Any]) -> None:
    """Ghi vết vào run.json (khoá refresh đang giữ nên không hai lane ghi cùng lúc) bằng temp + replace."""
    path = Path(run_dir) / "run.json"
    run = read_json(path)
    if not isinstance(run, dict):
        return
    log = run.setdefault("view_refresh", {"count": 0, "errors": 0, "last": None})
    log["count"] += 1
    log["errors"] += 0 if entry["ok"] else 1
    log["last"] = entry
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=True, indent=1), encoding="ascii")
    os.replace(tmp, path)


def refresh_views(run_dir: Path, run: dict[str, Any], label: str, *, why: str, lock_timeout: float = 300.0) -> dict[str, Any] | None:
    """Chạy ``library view`` + ``library review`` (gọi hàm, không shell) dưới khoá file. Mọi lỗi chỉ được ghi, không bao giờ ném."""
    cfg = run.get("view")
    if not cfg:
        return None
    entry: dict[str, Any] = {"at": time.time(), "lane": label, "why": why, "ok": True, "errors": []}
    try:
        with pool.locked(refresh_lock_path(cfg), timeout_seconds=lock_timeout, what="library view refresh"):
            libs = [Path(x) for x in cfg["libraries"]]
            if cfg.get("out"):
                try:
                    result = library_view.view(libs, [Path(x) for x in cfg["queues"]], Path(cfg["out"]), echo=lambda _t: None)
                    if int(result.get("exit", 1)) != 0:
                        entry["errors"] += [f"view: {e}" for e in (result.get("errors") or ["exit != 0"])[:20]]
                except BaseException as error:  # noqa: BLE001 - refresh không được dừng việc sinh ảnh
                    entry["errors"].append(f"view: {type(error).__name__}: {str(error)[:300]}")
            if cfg.get("review_out"):
                try:
                    library_review.review(libs, Path(cfg["review_out"]))
                except BaseException as error:  # noqa: BLE001
                    entry["errors"].append(f"review: {type(error).__name__}: {str(error)[:300]}")
            entry["ok"] = not entry["errors"]
            entry["at"] = time.time()
            try:
                _record_refresh(run_dir, entry)
            except BaseException as error:  # noqa: BLE001
                entry["errors"].append(f"record: {type(error).__name__}: {str(error)[:200]}")
    except BaseException as error:  # noqa: BLE001 - kể cả hết hạn chờ khoá
        entry["ok"] = False
        entry["errors"].append(f"lock/refresh: {type(error).__name__}: {str(error)[:300]}")
    try:
        append_event(run_dir, label, {"event": "VIEW_REFRESH", "why": why, "ok": entry["ok"], "errors": entry["errors"][:5]})
    except OSError:
        pass
    return entry


def start_run(plan_path: Path, plan: dict[str, Any], ctx: dict[str, Any], *, detach: bool,
              clock: Callable[[], float] = time.time, view: dict[str, Any] | None = None) -> dict[str, Any]:
    if ctx["missing"]:
        raise Refused(f"the plan has no {ctx['missing']}: pass --episode/--library-out/--pool-out to `library run` or re-plan with them")
    queue = Path(plan["queue"]["path"])
    if not queue.is_file() or sha256_file(queue) != plan["queue"]["sha256"]:
        raise Refused(f"queue {queue} changed or vanished since the plan: re-plan")
    previous = latest_run_dir(plan_path)
    if previous is not None:
        active = [lane["label"] for lane in plan["lanes"] if lane_active(previous, lane["label"])]
        if active:
            raise Refused(f"lanes {active} of run {previous} are still active; wait for them (see `images library status`)")
    require_n87_homes(plan, ctx.get("pool_state"))  # fail closed: holder cũ/không đọc được => không mở lane (spec §2)
    work, _ = lane_work(plan, ctx, verify_bytes=True)
    run_dir = _new_run_dir(plan_path, clock)
    batches_dir = run_dir / "batches"
    batches_dir.mkdir()
    copies = _copy_queues(queue.parent, batches_dir, referenced_queues(plan), plan.get("rev"))
    _carry_ownership(ctx, copies)
    lanes_doc: dict[str, Any] = {}
    for lane in plan["lanes"]:
        rows = []
        for row in work[lane["label"]]:
            if not row["remaining"]:
                rows.append({**row, "file": None, "state": "complete"})
            else:
                rows.append({**row, "file": _write_filtered_batch(batches_dir, row).as_posix(), "state": "pending"})
        lanes_doc[lane["label"]] = {**lane, "batches": rows}
    run = {"schema": RUN_SCHEMA, "created_at": clock(), "plan": {"path": Path(plan_path).resolve().as_posix(), "sha256": sha256_file(plan_path)},
           "context": ctx, "queues": copies, "lanes": lanes_doc, "detach": detach, "parent_pid": os.getpid(),
           "shared_home_locks": shared_home_locks(plan, ctx.get("pool_state"))}
    if view:
        run["view"] = view
    write_json_once(run_dir / "run.json", run, mode="ascii")
    procs: dict[str, subprocess.Popen] = {}
    for label, lane in lanes_doc.items():
        if all(b["state"] == "complete" for b in lane["batches"]):
            append_event(run_dir, label, {"event": "LANE_DONE", "note": "nothing to do: every take exists"})
            continue
        procs[label] = spawn_lane(plan_path, run_dir, label, detach=detach)
    status = refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
    base = {"run_dir": run_dir.as_posix(), "status": status_path(plan_path).as_posix(), "rev": plan.get("rev"),
            "pids": {label: proc.pid for label, proc in procs.items()}, "shared_home_locks": run["shared_home_locks"]}
    if detach:
        return {**base, "detached": True, "lanes": [{"label": l["label"], "state": l["state"]} for l in status["lanes"]]}
    for proc in procs.values():
        proc.wait()
    if view:
        refresh_views(run_dir, run, "run", why="end")
    status = refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
    lanes = [{"label": l["label"], "account": l["account"], "state": l["state"], "reason": l["reason"], "images": l["images"]}
             for l in status["lanes"]]
    unfinished = [l for l in lanes if l["state"] != "done"]
    if unfinished:
        raise Failed(f"{len(unfinished)} lane(s) did not finish: " + "; ".join(f"{l['label']}: {l['state']} ({l['reason']})" for l in unfinished)
                     + f"; totals {status['totals']}; re-run the same plan to resume", evidence={**base, "lanes": lanes, "totals": status["totals"]})
    return {**base, "detached": False, "lanes": lanes, "totals": status["totals"]}


# --- lane (tiến trình con) ------------------------------------------------------------------------------------

def classify_failure(error: BaseException) -> str:
    """quota | auth | cooling | timeout | refused | uncertain | error, từ loại lỗi + failovers của submit."""
    if isinstance(error, Refused):
        return "refused"
    text = str(error).lower()
    outcomes = {f.get("outcome") for f in ((getattr(error, "evidence", None) or {}).get("failovers") or [])}
    if "quota" in outcomes:
        return "quota"
    if outcomes & {"auth", "no_auth_file"}:
        return "auth"
    if "every codex account is cooling" in text or "cooling_after_lock" in outcomes:
        return "cooling"
    if "exceeded" in text and "s on account" in text:
        return "timeout"
    return "uncertain" if isinstance(error, Uncertain) else "error"


def run_submit(argv: list[str]) -> dict[str, Any]:
    """ĐÚNG đường CLI ``images submit``: parser thật của ``images`` + ``run_images`` (kết quả JSON được chép lại ra stdout)."""
    from . import cli as images_cli  # import muộn: cli -> library_cli -> module này

    parser = argparse.ArgumentParser(prog="jjv")
    images_cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    args = parser.parse_args(["images", *argv])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        images_cli.run_images(args)
    print(buffer.getvalue(), end="")
    return json.loads(buffer.getvalue())


def run_lane(plan_path: Path, run_dir: Path, label: str) -> dict[str, Any]:
    plan = library_plan.load_plan(plan_path)
    run = read_json(Path(run_dir) / "run.json")
    if not isinstance(run, dict) or run.get("schema") != RUN_SCHEMA:
        raise Refused(f"{run_dir}/run.json is not a {RUN_SCHEMA} document")
    lane = (run.get("lanes") or {}).get(label)
    if lane is None:
        raise Refused(f"lane {label!r} is not in {run_dir}/run.json")
    ctx = run["context"]
    made = 0
    require_n87_homes(plan, ctx.get("pool_state"))
    with pool.locked(lane_lock_path(run_dir, label), timeout_seconds=0.0, what=f"library lane {label}"):
        markers = write_n87_markers(plan_path, plan, ctx.get("pool_state"), label)
        try:
            return _run_lane_body(plan_path, plan, run, run_dir, label, lane, ctx, made)
        finally:
            clear_n87_markers(markers)


def _run_lane_body(plan_path: Path, plan: dict[str, Any], run: dict[str, Any], run_dir: Path, label: str, lane: dict[str, Any],
                   ctx: dict[str, Any], made: int) -> dict[str, Any]:
    if True:  # giữ nguyên thân cũ (diff tối thiểu)
        append_event(run_dir, label, {"event": "LANE_START", "pid": os.getpid()})
        refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
        for batch in lane["batches"]:
            if batch["state"] == "complete":
                continue
            append_event(run_dir, label, {"event": "START", "batch_id": batch["batch_id"], "items": len(batch["remaining"])})
            refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
            try:
                result = run_submit(submit_argv(ctx, lane, batch["file"]))
            except BaseException as error:  # noqa: BLE001 - mọi lỗi dừng lane và được ghi lại, không bao giờ im lặng
                images = len(((getattr(error, "evidence", None) or {}).get("completed_takes")) or [])
                made += images
                reason = classify_failure(error)
                append_event(run_dir, label, {"event": "EXIT", "batch_id": batch["batch_id"], "ok": False, "images": images,
                                              "reason": reason, "exit_code": exit_code_for(error) if isinstance(error, EngineError) else 2,
                                              "error": f"{type(error).__name__}: {str(error)[:600]}"})
                append_event(run_dir, label, {"event": "LANE_STOP", "reason": reason, "batch_id": batch["batch_id"]})
                refresh_views(run_dir, run, label, why=f"batch {batch['batch_id']} stopped")
                refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
                return {"lane": label, "state": "stopped", "reason": reason, "images": made, "batch_id": batch["batch_id"]}
            images = len(result.get("takes") or [])
            made += images
            append_event(run_dir, label, {"event": "EXIT", "batch_id": batch["batch_id"], "ok": True, "images": images, "exit_code": 0})
            refresh_views(run_dir, run, label, why=f"batch {batch['batch_id']}")
            refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
        append_event(run_dir, label, {"event": "LANE_DONE"})
        refresh_status(plan_path, plan, run_dir, run, ctx["library_out"])
    return {"lane": label, "state": "done", "images": made}


# --- status ---------------------------------------------------------------------------------------------------

def status(plan_path: Path, run_dir: str | None = None) -> dict[str, Any]:
    """Chỉ đọc file (không mạng): run mới nhất của plan (hoặc ``--run-dir``), rồi ghi lại ``<plan>.status.json``."""
    plan = library_plan.load_plan(plan_path)
    folder = Path(run_dir) if run_dir else latest_run_dir(plan_path)
    run = None
    if folder is not None:
        if not (folder / "run.json").is_file():
            raise Refused(f"{folder} has no run.json")
        run = read_json(folder / "run.json")
    library_out = (run or {}).get("context", {}).get("library_out") or plan.get("library_out")
    return refresh_status(plan_path, plan, folder, run, library_out)
