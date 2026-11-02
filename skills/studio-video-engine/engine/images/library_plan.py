"""``jjv images library plan`` (N89-P0): chia queue ảnh thư viện nhân vật thành lane.

Một dòng queue chỉ được phát khi ``dispatch_allowed`` là boolean ``True`` (N52). Các dòng gom theo ``batch_id``
(= file ``<thư mục queue>/<batch_id>.json``, chính là file ``--prompt-batch``) và các batch được chia round-robin cho
lane ``<acct>``, ``<acct>b``, ``<acct>c``... (``--procs-per-account``). Lane phụ là CÙNG một tài khoản ChatGPT: nó mang
``codex_home`` của tài khoản gốc (đọc từ machine.json) và ``run`` truyền ``--codex-account <label>=<home>``;
machine.json KHÔNG BAO GIỜ bị ghi. Tài khoản đang cooling trong pool state bị từ chối (không có gì chạy được trên nó).
Plan là tài liệu ``jjv/images-library-plan/v1``, ghi một lần (write-once).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from ..config.loader import DEFAULT_MACHINE_PATH
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from ..layout.context import ROUTES_RECIPE, load_context, load_recipe
from . import pool
from .library import character_of, check_prompt_id

PLAN_SCHEMA = "jjv/images-library-plan/v1"
VARIANT_LETTERS = "bcdefghijklmnopqrstuvwxyz"
MAX_PROCS = len(VARIANT_LETTERS) + 1
QUEUE_NAME = re.compile(r"^queue-(?P<rev>[A-Za-z0-9][A-Za-z0-9_.-]*)\.json$")


_RATIO = re.compile(r"(?<![\d:.])(\d{1,2})\s*:\s*(\d{1,2})(?![\d:])")
_WORD = re.compile(r"\b(widescreen|landscape)\b", re.IGNORECASE)


def library_canvas() -> dict[str, str]:
    """``{kind: "W:H"}`` từ recipe routes (``library.canvas``); khoá khung nằm trong recipe, không nằm trong prose."""
    canvas = (load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")[0].get("library") or {}).get("canvas") or {}
    return {str(k): str(v).replace(" ", "") for k, v in canvas.items()}


def canvas_problem(text: str, ratio: str) -> str | None:
    """None khi ``text`` nêu đúng ``ratio`` và không nêu tỉ lệ/hướng khác; ngược lại là lý do ngắn."""
    stated = {f"{a}:{b}" for a, b in _RATIO.findall(text)}
    wrong = sorted(stated - {ratio}) + sorted({w.lower() for w in _WORD.findall(text)})
    if wrong:
        return f"states {', '.join(wrong)} (needs {ratio})"
    return None if ratio in stated else f"does not state {ratio}"


def rev_of(queue: Path, explicit: str | None) -> str:
    """``r005c`` từ ``queue-r005c.json`` (hoặc ``--rev``)."""
    if explicit:
        return explicit
    found = QUEUE_NAME.match(Path(queue).name)
    if not found:
        raise Refused(f"cannot read the revision from {Path(queue).name!r} (expected queue-<rev>.json); pass --rev")
    return found.group("rev")


def resolve_pool_state(explicit: str | Path | None, machine: dict[str, Any], pool_out: str | Path | None) -> Path | None:
    """Cùng thứ tự với ``images submit``: --pool-state, machine.images.codex_state_path, rồi <pool_out>/codex-pool-state.json."""
    if explicit:
        return Path(explicit)
    configured = (machine.get("images") or {}).get("codex_state_path")
    if configured:
        return Path(str(configured))
    return Path(pool_out) / "codex-pool-state.json" if pool_out else None


def load_queue_rows(queue: Path, kinds: list[str] | None) -> list[dict[str, Any]]:
    """Các dòng ``dispatch_allowed is True`` (lọc theo ``kinds`` nếu có); prompt_id trùng nhau là từ chối."""
    try:
        rows = read_json(queue)
    except Uncertain as error:
        raise Refused(f"queue {queue} is not readable JSON: {error}") from error
    if not isinstance(rows, list):
        raise Refused(f"queue {Path(queue).name} must be a JSON array")
    allowed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise Refused(f"queue row {index} is not an object")
        if row.get("dispatch_allowed") is not True:
            continue  # false, "true", null, missing: not cleared (N52, fail-closed)
        pid, bid = row.get("prompt_id"), row.get("batch_id")
        if not isinstance(pid, str) or not pid.strip():
            raise Refused(f"queue row {index}: prompt_id missing")
        check_prompt_id(pid)
        if not isinstance(bid, str) or not bid.strip() or bid.startswith("_") or "/" in bid or "\\" in bid or ".." in bid:
            raise Refused(f"queue row {index} ({pid}): batch_id {bid!r} missing or not a plain file stem (the plan needs "
                          "<queue dir>/<batch_id>.json of every allowed row)")
        if pid in seen:
            raise Refused(f"queue row {index}: prompt_id {pid!r} appears twice among the allowed rows: ambiguous")
        seen.add(pid)
        if kinds is not None and row.get("kind") not in kinds:
            continue
        allowed.append(row)
    return allowed


def batches_from(queue: Path, rows: list[dict[str, Any]], canvas: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """``{batch_id: {file, sha256, items}}`` theo tên batch; item giữ thứ tự của FILE batch (file lọc khi run giữ nguyên)."""
    by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_batch.setdefault(row["batch_id"], []).append(row)
    batches: dict[str, dict[str, Any]] = {}
    bad: list[str] = []
    for bid in sorted(by_batch):
        file = Path(queue).parent / f"{bid}.json"
        if not file.is_file():
            raise Refused(f"batch file {file} named by the queue does not exist")
        try:
            data = read_json(file)
        except Uncertain as error:
            raise Refused(f"batch file {file.name} is not readable JSON: {error}") from error
        if not isinstance(data, list) or not data:
            raise Refused(f"batch file {file.name} must be a non-empty JSON array")
        in_file = [r.get("prompt_id") for r in data if isinstance(r, dict)]
        wanted = {r["prompt_id"]: r for r in by_batch[bid]}
        missing = [pid for pid in wanted if pid not in in_file]
        if missing:
            raise Refused(f"queue clears {missing} for batch {bid} but {file.name} has no such item")
        for r in data:
            want = wanted.get(r.get("prompt_id")) if isinstance(r, dict) else None
            ratio = (canvas or {}).get((want or {}).get("kind"))
            if want and ratio:
                why = canvas_problem(str(r.get("prompt_text") or ""), ratio)
                if why:
                    bad.append(f"{want['prompt_id']} ({want['kind']}: {why})")
        items = [{"prompt_id": pid, "char": wanted[pid].get("char") or character_of(pid), "kind": wanted[pid].get("kind"),
                  "prompt_sha256": wanted[pid].get("prompt_sha256")} for pid in in_file if pid in wanted]
        batches[bid] = {"file": file.resolve().as_posix(), "sha256": sha256_file(file), "items": items,
                        "prompt_ids": [i["prompt_id"] for i in items], "skipped_in_file": len(data) - len(items)}
    if bad:
        raise Refused(f"canvas lock (recipe {ROUTES_RECIPE} library.canvas): {len(bad)} prompt(s) with a wrong or missing aspect, "
                      f"nothing planned: {'; '.join(bad)}")
    return batches


def lanes_for(machine: dict[str, Any], labels: list[str], procs: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(accounts, lanes)``: lane gốc + lane phụ ``<label>b``, ``<label>c``... cùng codex_home. Không ghi gì."""
    if not isinstance(procs, int) or not 1 <= procs <= MAX_PROCS:
        raise Refused(f"--procs-per-account must be an integer 1..{MAX_PROCS} (got {procs!r})")
    known = {a.label: a for a in pool.accounts_from(machine, None)}
    if not known:
        raise Refused("machine.images.codex_accounts is empty: the plan needs the codex_home of every account (labels + paths only)")
    if len(set(labels)) != len(labels) or not labels:
        raise Refused(f"--accounts must name each account once (got {labels})")
    accounts, lanes = [], []
    for label in labels:
        account = known.get(label)
        if account is None:
            raise Refused(f"--accounts {label!r} is not a machine.json codex account (known: {sorted(known)})")
        if not account.auth_present:
            raise Refused(f"account {label} has no auth.json in its codex_home: log in first (the engine never logs in for you)")
        accounts.append({"label": label, "codex_home": account.codex_home.as_posix(), "auth_file_present": True})
        for k in range(procs):
            lane_label = label if k == 0 else f"{label}{VARIANT_LETTERS[k - 1]}"
            if k and lane_label in known:
                raise Refused(f"lane label {lane_label!r} collides with a configured account label; use fewer --procs-per-account")
            lanes.append({"label": lane_label, "account": label, "codex_home": account.codex_home.as_posix(),
                          "variant": k > 0, "batches": []})
    return accounts, lanes


def refuse_cooling(state_path: Path | None, lanes: list[dict[str, Any]], now: float, *,
                   configured_labels: set[str] | None = None) -> dict[str, float]:
    """Từ chối khi nhãn nào trong plan (gốc hoặc phụ) đang cooling trong pool state; trả về {} khi sạch."""
    if state_path is None or not Path(state_path).is_file():
        return {}
    state = pool.load_state(Path(state_path))
    accounts = [pool.Account(lane["label"], Path(lane["codex_home"])) for lane in lanes]
    _, cooling = pool.order(accounts, state, now, configured_labels=configured_labels)
    if cooling:
        named = ", ".join(f"{k} until {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(v))}" for k, v in sorted(cooling.items()))
        raise Refused(f"cooling in pool state {state_path}: {named}; drop the account from --accounts or wait (nothing planned)")
    return cooling


def assign_round_robin(lanes: list[dict[str, Any]], batch_ids: list[str]) -> list[dict[str, Any]]:
    """Batch i -> lane i mod n (bản sao mới, lane đầu vào không bị sửa)."""
    fresh = [{**lane, "batches": []} for lane in lanes]
    for index, bid in enumerate(batch_ids):
        fresh[index % len(fresh)]["batches"].append(bid)
    return fresh


def build_plan(*, queue: Path, accounts: list[str], procs: int, out: Path, machine_path: str | Path | None = None,
               episode: str | None = None, library_out: str | None = None, pool_out: str | None = None,
               pool_state: str | None = None, kinds: list[str] | None = None, rev: str | None = None,
               codex_bin: str | None = None, timeout: float | None = None,
               clock: Callable[[], float] = time.time) -> dict[str, Any]:
    queue, out = Path(queue), Path(out)
    if not queue.is_file():
        raise Refused(f"--queue file not found: {queue}")
    if out.exists():
        raise Refused(f"--out {out} exists; a plan is written once (pass a new path)")
    machine_file = Path(machine_path) if machine_path else DEFAULT_MACHINE_PATH
    episode_row: dict[str, Any] = {"episode": None, "episode_id": None, "domain": None}
    if episode:
        ctx = load_context(episode, machine_file)  # chỉ để xác nhận episode + lấy machine đúng như submit sẽ thấy
        machine = ctx.machine
        episode_row = {"episode": ctx.episode_file.resolve().as_posix(), "episode_id": ctx.episode_id, "domain": ctx.domain_id}
    else:
        machine = read_json(machine_file)
        if not isinstance(machine, dict):
            raise Refused(f"{machine_file} is not a machine document")
    revision = rev_of(queue, rev)
    rows = load_queue_rows(queue, kinds)
    if not rows:
        raise Refused(f"queue {queue.name} has no row with dispatch_allowed true" + (f" and kind in {kinds}" if kinds else ""))
    canvas = library_canvas()
    batches = batches_from(queue, rows, canvas)
    account_rows, lanes = lanes_for(machine, accounts, procs)
    state_path = resolve_pool_state(pool_state, machine, pool_out)
    refuse_cooling(state_path, lanes, clock(), configured_labels=pool.cooling_labels(machine, []))
    lanes = assign_round_robin(lanes, list(batches))
    for lane in lanes:
        for bid in lane["batches"]:
            batches[bid]["lane"] = lane["label"]
    plan = {"schema": PLAN_SCHEMA, "created_at": clock(), **episode_row, "machine": machine_file.resolve().as_posix(),
            "queue": {"path": queue.resolve().as_posix(), "sha256": sha256_file(queue), "allowed_rows": len(rows)},
            "rev": revision, "kinds": kinds, "canvas": canvas, "library_out": Path(library_out).resolve().as_posix() if library_out else None,
            "pool_out": Path(pool_out).resolve().as_posix() if pool_out else None,
            "pool_state": state_path.resolve().as_posix() if state_path else None,
            "cooling_checked": bool(state_path and Path(state_path).is_file()),
            "procs_per_account": procs, "accounts": account_rows, "lanes": lanes, "batches": batches,
            "codex_bin": codex_bin, "timeout": timeout}
    write_json_once(out, plan, mode="ascii")
    return {"plan": out.resolve().as_posix(), "rev": revision, "kinds": kinds, "batches": len(batches),
            "prompt_ids": sum(len(b["prompt_ids"]) for b in batches.values()), "accounts": [a["label"] for a in account_rows],
            "lanes": [{"label": lane["label"], "account": lane["account"], "variant": lane["variant"], "batches": lane["batches"]}
                      for lane in lanes],
            "pool_state": plan["pool_state"], "cooling_checked": plan["cooling_checked"],
            "library_out": plan["library_out"], "pool_out": plan["pool_out"], "episode": plan["episode"]}


def load_plan(path: Path) -> dict[str, Any]:
    plan = read_json(Path(path))
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise Refused(f"{path} is not a {PLAN_SCHEMA} document")
    return plan
