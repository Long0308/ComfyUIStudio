"""``jjv images submit --provider codex-exec``: the GPT OAuth route through the Codex CLI, with an account pool.

The engine spawns ``codex exec`` non-interactively (prompt on stdin, the guide and cast refs attached with ``-i``)
under ``CODEX_HOME=<account home>``; Codex's built-in image_gen tool writes ``<home>/generated_images/<session>/
exec-<id>.png`` and the engine adopts that exact file. The engine never reads, copies, hashes or prints a token
(see ``pool.py``), never calls the router's /v1/images, runs ONE job at a time PER ACCOUNT LABEL (a lock per label:
two lanes on two labels run in parallel, the same label queues) and never retries the same request on more accounts
than the pool holds. ``--account LABEL`` pins a lane to one pool account (no failover to the others). The shared pool
state file is only touched through ``pool.update_state`` (short lock, re-read, change, write), so concurrent lanes
never lose each other's record. A timeout is Uncertain (the image may exist): no failover, no retry.
A quota/usage-limit or auth failure cools that account (the time the message gives, else the recipe default) and
the request moves to the next account; when every account failed the result is Uncertain.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, Mapping

from ..core.errors import EngineError, Refused, Uncertain
from ..core.io import sha256_bytes, write_json_once
from ..layout.context import Context, domain_policy, load_recipe, require_provider
from . import pool
from .codex_queue import (  # noqa: F401  (re-exported: callers and tests import these from codex)
    IMAGE_LINE, IMAGE_SUFFIXES, MAX_N, MAX_N_WHY, _check_brief_numbers, _check_ref_path, _queue_problem, _queue_rows,
    _refuse_blocked, batch_roots, load_batch, provenance_problem)
from .codex_run import (  # noqa: F401  (re-exported)
    UNIT, Runner, cooling_seconds, default_runner, failure_kind, find_codex, own_session, snapshot, thread_id)
from .common import compose_prompt, next_take, register, shot_inputs, write_prompt

RECIPE_NAME, RECIPE_SCHEMA = "codex-exec-v001", "jjv/images-codex-exec-recipe/v1"
LOCK_EXTRA_SECONDS = 120.0  # a queued lane waits timeout + this for the label lock (a job may legitimately run `timeout`)
LIBRARY_RECEIPT_SCHEMA = "jjv/library-image-receipt/v1"


def _is_identity_role(role: str) -> bool:
    """True when the ``identity`` token is in the role (``identity``, ``face_identity``) and not negated (``no_identity_...``)."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", role.lower()) if t]
    return any(t == "identity" and (i == 0 or tokens[i - 1] not in {"no", "not", "without"}) for i, t in enumerate(tokens))


def _ref_line(index: int, role: str, by_role: bool, name: str | None = None) -> str:
    """Plan cast refs (``by_role`` False) are identity references. Refs of a --prompt-batch item name their own role
    in the batch file: only ``identity*`` keeps the identity sentence, any other role is used for what it names."""
    tag = f" [{name}]" if name else ""
    if not by_role or _is_identity_role(role):
        return f"Image {index}: {role} identity reference (keep this exact character){tag}"
    what = re.sub(r"(?:\s*\breference)+$", "", role.replace("_", " ").strip(), flags=re.I).strip()
    if not what:
        return f"Image {index}: unlabelled reference (no role stated: do NOT take the person's face or identity from it){tag}"
    return f"Image {index}: {what} reference (use it ONLY for: {what}; do NOT take the person's face or identity from it){tag}"


def _roles(inputs: dict[str, Any]) -> str:
    """Numbered exactly like the ``-i`` list. Library mode has no guide, so Image 1 is the first ref."""
    if inputs.get("guide") is None:
        return "\n".join(_ref_line(i, r["role"], True, Path(r["path"]).name) for i, r in enumerate(inputs["refs"], 1))
    lines = [f"Image 1: {inputs['guide']['role']} (layout/spatial guide ONLY: do not copy its graybox look)"]
    by_role = "_meta" in inputs
    lines += [_ref_line(i, r["role"], by_role) for i, r in enumerate(inputs["refs"], 2)]
    return "\n".join(lines)


MAX_TAKE_CLAIMS = 50  # a lane retries the next number at most this many times when another lane took its number


def claim_take(base: Path, take: str | None) -> Path:
    """Create and return the take folder atomically (``mkdir`` without ``exist_ok`` is the claim).

    ``--take NAME``: that exact folder, Refused if it exists. No name: the next free number; when a parallel lane
    created it between numbering and ``mkdir`` (FileExistsError), try the following number, bounded."""
    if take is not None:
        folder = Path(base) / take
        try:
            folder.mkdir(parents=True)
        except FileExistsError:
            raise Refused(f"take folder {folder} exists; a take is never reused (pass a new --take)") from None
        return folder
    for _ in range(MAX_TAKE_CLAIMS):
        folder = Path(base) / next_take(Path(base))
        try:
            folder.mkdir(parents=True)
        except FileExistsError:
            continue
        return folder
    raise Refused(f"could not claim a free take number under {base} after {MAX_TAKE_CLAIMS} tries (parallel lanes?)")


def submit(ctx: Context, out: Path, shot: str, prompt_file: Path, accounts: list[pool.Account], *, codex_cmd: list[str],
           state_path: Path, take: str | None = None, timeout: float | None = None, dry_run: bool = False,
           runner: Runner = default_runner, base_env: Mapping[str, str] | None = None, clock: Callable[[], float] = time.time,
           recipe: dict[str, Any] | None = None, account: str | None = None,
           item: dict[str, Any] | None = None, dry_index: int = 0, library_out: Path | None = None) -> dict[str, Any]:
    """``item`` (N23, one entry of a --prompt-batch file): its prompt_text replaces the prompt file and its
    ref_images replace the plan's cast refs (the plan's guide stays image 1). ``--dry-run`` creates NOTHING on disk
    (no take folder, no prompt.txt); ``dry_index`` is the position in a multi-take call, so planned names run on."""
    require_provider(ctx, "codex-exec")
    provenance = bool(domain_policy(ctx).get("provenance_required"))
    if not dry_run:
        if item is None:
            why = provenance_problem(None, provenance)
            if why:
                raise Refused(f"{why}; a real submit is refused; --dry-run still plans it")
        else:
            _refuse_blocked(item, provenance, ctx=ctx)
    loaded = recipe or load_recipe(RECIPE_NAME, RECIPE_SCHEMA)[0]
    if not accounts:
        raise Refused("no codex accounts configured (machine.images.codex_accounts or --codex-account LABEL=HOME)")
    cooling_labels = pool.cooling_labels(ctx.machine, accounts)
    if account is not None:
        accounts = [a for a in accounts if a.label == account]
        if not accounts:
            raise Refused(f"--account {account!r} is not a configured codex account label")
    if library_out is not None:  # library mode: no plan, no guide, no placement (N23-fix)
        if item is None:
            raise Refused("library mode takes its prompts and refs from a --prompt-batch item")
        inputs = {"guide": None, "placement_text": "", "refs": [dict(r) for r in item["ref_images"]]}
    else:
        inputs = shot_inputs(out, shot)
    if item is not None:
        inputs = {**inputs, "refs": [dict(r) for r in item["ref_images"]],
                  "_meta": {"prompt_id": item["prompt_id"], "batch_id": item["batch_id"], "library": library_out is not None,
                            "prompt_sha_verified": item.get("prompt_sha_verified"),
                            "prompt_text_sha256": item.get("prompt_text_sha256")}}
        brief = item["prompt_text"]
        brief_src = {"file": item["batch_file"], "prompt_id": item["prompt_id"],
                     "sha256": sha256_bytes(brief.encode("utf-8"))}
    else:
        brief, brief_src = compose_prompt(prompt_file, inputs["placement_text"])
    sent = loaded["prompt_template"].format(roles=_roles(inputs), brief=brief.strip())
    state = pool.load_state(state_path)
    order, cooling = pool.order(accounts, state, clock(), configured_labels=cooling_labels)
    if not dry_run and not order:  # nothing can run: do not leave an empty take folder behind
        raise Uncertain(f"every codex account is cooling: {cooling}; no job was started", evidence={"cooling": cooling})
    base = (Path(library_out) / item["batch_id"]) if library_out is not None else Path(out) / shot / "codex-exec"
    if dry_run:
        if take is not None and (base / take).exists():  # a dry run must refuse what the real run would refuse
            raise Refused(f"take folder {base / take} exists; a take is never reused (pass a new --take)")
        folder = base / (take or f"t{int(next_take(base)[1:]) + dry_index:03d}")
        prompt = {"file": None, "sha256": sha256_bytes(sent.encode("utf-8"))}
    else:
        folder = claim_take(base, take)
        prompt = write_prompt(folder, sent)
    take = folder.name
    prompt = {**prompt, "brief_source": brief_src, "brief_sha256": sha256_bytes(brief.encode("utf-8"))}
    images = [*([inputs["guide"]] if inputs["guide"] is not None else []), *inputs["refs"]]
    work = folder / "work"
    if not dry_run:
        work.mkdir()
    argv = [*codex_cmd, "exec", "-c", "mcp_servers={}", "--skip-git-repo-check", "--json", "-s", "read-only", "-C", str(work),
            "-o", str(folder / "last-message.txt"), *[a for r in images for a in ("-i", r["path"])]]
    plan = {"shot": shot, "take": take, "prompt_id": (inputs.get("_meta") or {}).get("prompt_id"),
            "batch_id": (inputs.get("_meta") or {}).get("batch_id"), "prompt_sha256": prompt["sha256"], "argv_without_prompt": argv,
            "account_order": [a.label for a in order], "cooling": {k: v for k, v in cooling.items()},
            "auth_file_present": {a.label: a.auth_present for a in accounts}}
    if item is not None:
        plan["dispatch_allowed"] = item.get("dispatch_allowed")
        if item.get("queue_present") and (item.get("queue_problem") or item.get("dispatch_allowed") is not True):
            plan["dispatch_gate"] = (f"REAL SUBMIT WOULD BE REFUSED: {item.get('queue_problem') or 'dispatch_allowed is not boolean true'}")
    gap = provenance_problem(item, provenance)
    if gap:
        plan["dispatch_gate"] = f"REAL SUBMIT WOULD BE REFUSED: {gap}"
    if dry_run:
        return {**plan, "dry_run": True, "submitted": False}
    return _run_pool(ctx, out, shot, folder, argv, sent, prompt, inputs, order, state, state_path, loaded,
                     timeout or loaded["timeout_seconds"], runner, base_env or os.environ, clock, plan, codex_cmd,
                     configured_labels=cooling_labels)


def submit_many(ctx: Context, out: Path, shot: str, prompt_file: Path, accounts: list[pool.Account], *, n: int = 1,
                take: str | None = None, **kw: Any) -> dict[str, Any]:
    """``--n N``: N takes in turn, each a full ``submit`` (own folder + receipt). N=1 returns the old single result.

    Takes run one after another here (each holds its account's lock); lanes parallelise by separate calls with --account.
    A failure on take k raises as before; takes 1..k-1 already have their receipts on disk."""
    if not isinstance(n, int) or not 1 <= n <= MAX_N:
        raise Refused(f"--n must be an integer 1..{MAX_N} (got {n!r}); {MAX_N_WHY}")
    if n == 1:
        return submit(ctx, out, shot, prompt_file, accounts, take=take, **kw)
    if take is not None:
        raise Refused("--take names one folder; it cannot be combined with --n > 1 (takes are numbered automatically)")
    rows: list[dict[str, Any]] = []
    for index in range(n):
        try:
            rows.append(submit(ctx, out, shot, prompt_file, accounts, dry_index=index, **kw))
        except EngineError as error:  # takes already done stay visible in the error output
            if rows:
                error.evidence["completed_takes"] = rows
            raise
    dry = bool(kw.get("dry_run"))
    return {"shot": shot, "n": n, "dry_run": dry, "submitted": not dry, "takes": rows}



def submit_batch(ctx: Context, out: Path, shot: str, batch_file: Path, accounts: list[pool.Account],
                 **kw: Any) -> dict[str, Any]:
    """``--prompt-batch FILE`` with a shot: one take per item, each with ITS prompt and refs (the shot guide is Image 1).

    Items run in turn under the account lock; lanes = separate calls with --account. A failure on item k raises with
    ``evidence.completed_takes`` = the rows already done."""
    allowed, forbidden = batch_roots(ctx, accounts)
    items = load_batch(batch_file, allowed=allowed, forbidden=forbidden)  # Refused here leaves no folder behind
    return _run_items(ctx, out, shot, items, accounts, library_out=None, **kw)


def submit_library_batch(ctx: Context, library_out: Path, batch_file: Path, accounts: list[pool.Account],
                         **kw: Any) -> dict[str, Any]:
    """Library mode (character images, no shot): no guide, no plan; Image 1 is the first ref, in ``-i`` order.
    Takes land in ``<library_out>/<batch_id>/tNNN`` with a ``jjv/library-image-receipt/v1`` receipt."""
    allowed, forbidden = batch_roots(ctx, accounts)
    items = load_batch(batch_file, allowed=allowed, forbidden=forbidden, library=True)
    return _run_items(ctx, library_out, items[0]["batch_id"], items, accounts, library_out=Path(library_out), **kw)


def _run_items(ctx: Context, out: Path, shot: str, items: list[dict[str, Any]], accounts: list[pool.Account], *,
               library_out: Path | None, **kw: Any) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if not kw.get("dry_run"):
        provenance = bool(domain_policy(ctx).get("provenance_required"))
        for item in items:  # refuse the whole batch before any folder or codex call
            _refuse_blocked(item, provenance, ctx=ctx)
    for index, item in enumerate(items):
        try:
            rows.append(submit(ctx, out, shot, Path(item["batch_file"]), accounts, item=item, dry_index=index,
                               library_out=library_out, **kw))
        except EngineError as error:
            if rows:
                error.evidence["completed_takes"] = rows
            raise
    dry = bool(kw.get("dry_run"))
    return {"shot": None if library_out else shot, "batch_id": items[0]["batch_id"], "library": library_out is not None,
            "n": len(items), "dry_run": dry, "submitted": not dry, "takes": rows}


def _register_library(ctx: Context, folder: Path, png: Path, body: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Receipt for a library image (no shot, no plan, no ComfyUI review workflow). Never holds a token."""
    from ..core.io import pretty_json, write_once
    from . import receipts

    data = Path(png).read_bytes()
    sha = sha256_bytes(data)
    info = receipts.png_info(png)
    final, receipt_path = folder / f"{sha[:12]}.png", folder / f"{sha[:12]}.receipt.json"
    if write_once(final, data) != sha:
        raise Refused(f"library image write did not produce the source bytes: {final}")
    receipt = {"schema": LIBRARY_RECEIPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
               "status": "rendered_candidate", "created_at": time.time(), **{k: v for k, v in body.items() if k != "ref_hashes"},
               "ref_hashes": inputs["refs"], "output": {"path": final.resolve().as_posix(), "sha256": sha, **info}}
    write_once(receipt_path, pretty_json(receipt, mode="ascii"))
    return {"output": receipt["output"], "receipt_path": receipt_path.as_posix()}


def _run_pool(ctx: Context, out: Path, shot: str, folder: Path, argv: list[str], sent: str, prompt: dict, inputs: dict,
              order: list[pool.Account], state: dict, state_path: Path, recipe: dict, timeout: float, runner: Runner,
              base_env: Mapping[str, str], clock: Callable[[], float], plan: dict, codex_cmd: list[str], *,
              configured_labels: set[str] | None = None) -> dict[str, Any]:
    cooling_labels = pool.cooling_labels(ctx.machine, order) if configured_labels is None else configured_labels
    failovers: list[dict[str, Any]] = []
    for account in order:  # at most the pool size: each account is tried once per request
        if not account.auth_present:
            failovers.append({"label": account.label, "outcome": "no_auth_file", "at": clock()})
            continue
        # one job at a time per label; other labels run meanwhile. Wait as long as a job may legitimately take
        stack = ExitStack()
        try:
            stack.enter_context(pool.locked(pool.label_lock_path(state_path, account.label), timeout_seconds=timeout + LOCK_EXTRA_SECONDS,
                                            what=f"codex image label lock {account.label}"))
        except EngineError:
            if not failovers:
                _drop_unstarted(folder)  # no lock, no job: do not leave an empty take behind
            raise
        with stack:
            # Another lane may have cooled this base while we queued; keep the full configuration in this check.
            again, cooling = pool.order([account], pool.load_state(state_path), clock(), configured_labels=cooling_labels)
            if not again:
                failovers.append({"label": account.label, "outcome": "cooling_after_lock", "cooling_until": cooling.get(account.label)})
                continue
            outcome = _try_account(ctx, out, shot, folder, argv, sent, prompt, inputs, account, state_path, recipe, timeout,
                                   runner, base_env, clock, codex_cmd, failovers)
        if outcome is not None:
            return outcome
    write_json_once(folder / "failovers.json", {"failovers": failovers}, mode="ascii")
    raise Uncertain(f"no codex account could make the image ({[f['label'] + ':' + f['outcome'] for f in failovers]}); "
                    "not retried in a loop", evidence={"failovers": failovers, "folder": str(folder)})


def _drop_unstarted(folder: Path) -> None:
    """Remove a take folder that holds nothing but ``prompt.txt`` and an empty ``work/`` (the job never started)."""
    import shutil

    work = folder / "work"
    names = {p.name for p in folder.iterdir()} if folder.is_dir() else set()
    if names <= {"prompt.txt", "work"} and (not work.exists() or not any(work.iterdir())):
        shutil.rmtree(folder, ignore_errors=True)


def _try_account(ctx: Context, out: Path, shot: str, folder: Path, argv: list[str], sent: str, prompt: dict, inputs: dict,
                 account: pool.Account, state_path: Path, recipe: dict, timeout: float, runner: Runner,
                 base_env: Mapping[str, str], clock: Callable[[], float], codex_cmd: list[str],
                 failovers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One account, lock already held. Returns the result, or None when the account failed over (cooled)."""
    before = snapshot(account.codex_home, recipe)
    env = {**base_env, "CODEX_HOME": str(account.codex_home)}
    try:
        done = runner(argv, input_text=sent, env=env, cwd=str(folder / "work"), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        appeared = set(snapshot(account.codex_home, recipe)) - set(before)
        session = thread_id(_text(error.stdout))
        unknown = {"label": account.label, "timeout_seconds": timeout,
                   "new_images": _unknown_images(appeared, session)}
        if not session:
            unknown.update({"unattributed_images_in_shared_home": sorted(appeared), "thread_id": None})
        write_json_once(folder / "unknown.json", unknown, mode="ascii")
        raise Uncertain(f"codex exec exceeded {timeout:g} s on account {account.label}; the image may exist "
                        "(see unknown.json). No retry, no failover", evidence={"folder": str(folder)}) from error
    except OSError as error:
        raise Uncertain(f"cannot start the Codex CLI: {error!r}") from error
    text = (done.stdout or "") + "\n" + (done.stderr or "")
    appeared = set(snapshot(account.codex_home, recipe)) - set(before)
    session = thread_id(done.stdout or "")
    new = own_session(appeared, session)  # N87: only THIS run's session folder, never another process's image
    if not session and appeared and done.returncode == 0:
        raise Uncertain(f"codex exec on {account.label} printed no thread id and {len(appeared)} image(s) appeared in the shared "
                        "home: cannot attribute them, nothing adopted", evidence={"new_images": sorted(appeared), "folder": str(folder)})
    if done.returncode == 0 and len(new) == 1:
        return _adopt(ctx, out, shot, folder, account, Path(new[0]), done, text, failovers, prompt, inputs,
                      state_path, recipe, codex_cmd, clock)
    if len(new) > 1 or (new and done.returncode != 0):
        raise Uncertain(f"codex exec on {account.label} left {len(new)} new image(s) with exit {done.returncode}: "
                        "ambiguous, nothing adopted", evidence={"new_images": new, "folder": str(folder)})
    kind = failure_kind(text, recipe)
    if kind is None:
        raise Uncertain(f"codex exec on {account.label} produced no image (exit {done.returncode}): "
                        f"{text.strip()[-300:]!r}", evidence={"folder": str(folder)})
    seconds = cooling_seconds(text, recipe["default_cooling_seconds"])
    until = clock() + seconds
    pool.update_state(state_path, lambda st: pool.mark_cooling(st, account.label, until, kind, clock()))
    failovers.append({"label": account.label, "outcome": kind, "cooling_seconds": seconds, "cooling_until": until})
    return None


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def _unknown_images(appeared: set[str], session: str | None) -> list[str]:
    """unknown.json lists this session's images when the id is known; without an id, none are attributable."""
    return own_session(appeared, session) if session else []


def _adopt(ctx: Context, out: Path, shot: str, folder: Path, account: pool.Account, png: Path, done: Any, text: str,
           failovers: list, prompt: dict, inputs: dict, state_path: Path, recipe: dict,
           codex_cmd: list[str], clock: Callable[[], float]) -> dict[str, Any]:
    last = folder / "last-message.txt"
    printed = last.read_text(encoding="utf-8", errors="replace").strip()[-300:] if last.is_file() else None
    body = {"route": "codex-exec", "provider": "codex-exec", "requested_model": recipe["requested_model"],
            "resolved_model": None, "runtime_id": thread_id(done.stdout or ""),
            "prompt_id": (inputs.get("_meta") or {}).get("prompt_id"), "batch_id": (inputs.get("_meta") or {}).get("batch_id"),
            "prompt": prompt, "prompt_sha256": prompt["sha256"], "account_label": account.label,
            "prompt_text_sha256": (inputs.get("_meta") or {}).get("prompt_text_sha256"),
            "prompt_sha_verified": (inputs.get("_meta") or {}).get("prompt_sha_verified"), "failovers": failovers,
            "source_path": png.as_posix(), "codex": {"command": codex_cmd, "exit_code": done.returncode,
            "session_folder": png.parent.name, "printed_tail": printed},
            "tool_evidence": "built-in image_gen via `codex exec`; the tool exposes no resolved model",
            "recipe": recipe["id"]}
    if (inputs.get("_meta") or {}).get("library"):
        receipt = _register_library(ctx, folder, png, body, inputs)
    else:
        receipt = register(ctx, out, shot, png, inputs, body)
    pool.update_state(state_path, lambda st: pool.mark_good(st, account.label, clock()))  # only after the receipt exists
    return {"shot": shot, "take": folder.name, "submitted": True, "dry_run": False, "account_label": account.label,
            "prompt_id": body["prompt_id"], "batch_id": body["batch_id"],
            "failovers": failovers, "runtime_id": body["runtime_id"], "candidate_sha256": receipt["output"]["sha256"],
            "receipt": receipt["receipt_path"], "source_path": png.as_posix(),
            "workflow": receipt.get("review_workflow")}
