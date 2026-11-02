"""N20: codex-exec lanes. One lock PER account label: two labels run in parallel, one label queues; the shared pool
state never loses a record under concurrent writes. FAKE codex only (real threads, real fake-codex processes)."""

from __future__ import annotations

import json
import threading
import traceback
import time
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import codex, pool
from images_fixtures import World, python_cmd
from test_images_codex import FAKE, SECRET, Setup, no_auth_reads  # noqa: F401  (fixture re-used)

SLEEP = 2.0


def lane_setup(tmp: Path) -> Setup:
    original = World.images_plan  # Setup plans once; make that one plan cover both lane shots
    World.images_plan = lambda self, out, layout, shots=("S01_A", "S02_A"): original(self, out, layout, shots)
    try:
        setup = Setup(tmp)
    finally:
        World.images_plan = original
    setup.env = {**setup.env, "FAKE_CODEX_SLEEP": str(SLEEP)}
    return setup


def lane(setup: Setup, shot: str, label: str | None, results: dict, key: str, take: str | None = None) -> None:
    try:
        results[key] = codex.submit(setup.world.ctx(), setup.out, shot, setup.prompt, setup.accounts,
                                    codex_cmd=python_cmd(FAKE), state_path=setup.state, base_env=setup.env,
                                    timeout=60, account=label, take=take)
    except BaseException as error:  # reported to the main thread
        results[key] = error


def run_lanes(setup: Setup, jobs: list[tuple[str, str]]) -> tuple[dict, float]:
    results: dict = {}
    threads = [threading.Thread(target=lane, args=(setup, shot, label, results, f"{shot}:{label}"))
               for shot, label in jobs]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, time.monotonic() - started


def spans(setup: Setup, label: str) -> list[dict]:
    log = next(a for a in setup.accounts if a.label == label).codex_home / "spans.jsonl"
    return [json.loads(line) for line in log.read_text("utf-8").splitlines()]


def test_two_labels_run_in_parallel_total_is_about_one_job(tmp_path, no_auth_reads):
    setup = lane_setup(tmp_path)
    results, elapsed = run_lanes(setup, [("S01_A", "acct1"), ("S02_A", "acct2")])
    print(f"LANE_TIMING parallel_two_labels elapsed={elapsed:.2f}s (one job sleeps {SLEEP}s)")
    assert all(isinstance(r, dict) for r in results.values()), results
    assert results["S01_A:acct1"]["account_label"] == "acct1" and results["S02_A:acct2"]["account_label"] == "acct2"
    a, b = spans(setup, "acct1")[0], spans(setup, "acct2")[0]
    assert a["start"] < b["end"] and b["start"] < a["end"], "the two jobs must overlap in time"
    assert elapsed < 2 * SLEEP, f"parallel lanes took {elapsed:.2f}s, no better than serial"


def test_same_label_stays_sequential(tmp_path):
    setup = lane_setup(tmp_path)
    results, elapsed = run_lanes(setup, [("S01_A", "acct1"), ("S02_A", "acct1")])
    print(f"LANE_TIMING same_label elapsed={elapsed:.2f}s")
    assert all(isinstance(r, dict) for r in results.values()), results
    first, second = sorted(spans(setup, "acct1"), key=lambda s: s["start"])
    assert second["start"] >= first["end"], "same label must never run two jobs at once"
    assert elapsed >= 2 * SLEEP


def test_label_lock_file_is_per_label_and_distinct_from_the_state_lock(tmp_path):
    # naming only; the wait budget (job timeout + 120 s, not 30 s) is read in codex._run_pool
    setup = lane_setup(tmp_path)
    lock = pool.label_lock_path(setup.state, "acct1")
    assert lock.name == "pool-state.acct1.lock" and lock != setup.state.with_suffix(".lock")


def test_pool_state_loses_no_record_under_concurrent_writes(tmp_path):
    state = tmp_path / "pool-state.json"
    errors: list[BaseException] = []

    def worker(t: int) -> None:
        try:
            for i in range(15):
                pool.update_state(state, lambda s, key=f"l{t}-{i}": pool.mark_cooling(s, key, 5.0, "quota", 1.0))
        except BaseException:
            errors.append(traceback.format_exc())

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        print("TB>>>", errors[0][-1400:])
    assert not errors
    assert len(pool.load_state(state)["cooling"]) == 8 * 15


def test_parallel_lanes_record_both_accounts_in_state_and_no_token_leaks(tmp_path):
    setup = lane_setup(tmp_path)
    results, _ = run_lanes(setup, [("S01_A", "acct1"), ("S02_A", "acct2")])
    assert all(isinstance(r, dict) for r in results.values()), results
    events = {(h["label"], h["event"]) for h in pool.load_state(setup.state)["history"]}
    assert {("acct1", "ok"), ("acct2", "ok")} <= events
    everything = "".join(p.read_text("utf-8", errors="ignore") for p in tmp_path.rglob("*.json") if "homes" not in p.parts)
    assert SECRET not in everything


def test_account_flag_pins_the_lane_and_unknown_label_is_refused(tmp_path):
    setup = Setup(tmp_path)
    result = setup.run(account="acct2")
    assert result["account_label"] == "acct2" and not setup.calls("acct1")
    with pytest.raises(Refused, match="nope"):
        setup.run(account="nope")
