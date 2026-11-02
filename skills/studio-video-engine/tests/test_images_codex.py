"""``jjv images submit --provider codex-exec``: FAKE Codex CLI, account pool, failover, cooling, token hygiene."""

from __future__ import annotations

import builtins
import json
import os
import pathlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.core.errors import Refused, Uncertain
from engine.images import codex, pool
from images_fixtures import World, make_png, python_cmd, run_images, run_layout

FAKE = Path(__file__).with_name("fake_codex.py")
SECRET = "SECRET-DO-NOT-READ"


class Setup:
    def __init__(self, tmp: Path, domain: str = "jenniejoy_cartoon_3d", accounts: int = 2) -> None:
        self.world = World(tmp, domain=domain)
        self.layout, self.out = tmp / "layout", tmp / "images"
        self.world.plan_layout(self.layout)
        self.world.images_plan(self.out, self.layout)
        self.png = make_png(tmp / "fake-image.png", (10, 20, 30), (320, 180))
        self.prompt = tmp / "brief.txt"
        self.prompt.write_text("A sunny garden, mother seated, child kneeling.", encoding="utf-8")
        self.accounts = []
        for index in range(accounts):
            home = tmp / "homes" / f"acct{index + 1}"
            home.mkdir(parents=True)
            (home / "auth.json").write_text(SECRET, encoding="utf-8")
            self.accounts.append(pool.Account(f"acct{index + 1}", home))
        self.state = tmp / "pool-state.json"
        self.env = {**os.environ, "FAKE_CODEX_PNG": str(self.png)}
        self.clock = [1_000_000.0]

    def run(self, **kw):
        return codex.submit(self.world.ctx(), self.out, "S01_A", self.prompt, kw.pop("accounts", self.accounts),
                            codex_cmd=python_cmd(FAKE), state_path=self.state, base_env=self.env,
                            clock=lambda: self.clock[0], timeout=kw.pop("timeout", 30), **kw)

    def flag(self, label: str, name: str, text: str = "") -> None:
        (next(a for a in self.accounts if a.label == label).codex_home / name).write_text(text, encoding="utf-8")

    def calls(self, label: str) -> list[dict]:
        log = next(a for a in self.accounts if a.label == label).codex_home / "calls.jsonl"
        return [json.loads(line) for line in log.read_text("utf-8").splitlines()] if log.exists() else []


@pytest.fixture
def no_auth_reads(monkeypatch):
    """The engine may only ASK whether auth.json exists; any READ of it in this process fails the test
    (the test itself writes it, which is allowed)."""
    def guard(path, mode="r"):
        if "auth.json" in str(path) and not any(c in str(mode) for c in "wax"):
            raise AssertionError(f"engine tried to read {path}")

    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda f, mode="r", *a, **k: (guard(f, mode), real_open(f, mode, *a, **k))[1])
    real_path_open = pathlib.Path.open
    monkeypatch.setattr(pathlib.Path, "open", lambda self, mode="r", *a, **k: (guard(self, mode), real_path_open(self, mode, *a, **k))[1])
    for name in ("read_text", "read_bytes"):
        real = getattr(pathlib.Path, name)
        monkeypatch.setattr(pathlib.Path, name, lambda self, *a, _real=real, **k: (guard(self), _real(self, *a, **k))[1])


def test_success_adopts_the_exact_file_with_label_runtime_id_and_unexposed_model(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    result = setup.run()
    assert result["account_label"] == "acct1" and result["failovers"] == []
    receipt = json.loads(Path(result["receipt"]).read_text("utf-8"))
    assert receipt["route"] == "codex-exec" and receipt["requested_model"] == "GPT Image Gen 2"
    assert receipt["resolved_model"] is None and receipt["runtime_id"] and receipt["runtime_id"] == receipt["codex"]["session_folder"]
    assert receipt["source_path"].endswith(".png") and "generated_images" in receipt["source_path"].replace("\\", "/")
    assert receipt["output"]["sha256"] == result["candidate_sha256"]
    assert [r["role"] for r in receipt["ref_hashes"]] == ["mother", "alice"] and receipt["guide"]["sha256"]
    call = setup.calls("acct1")[0]
    assert call["argv"][0] == "exec" and call["argv"].count("-i") == 3     # guide + two cast refs, in order
    assert "Image 1: guide" in call["stdin"] and "Image 2: mother" in call["stdin"] and "print only the absolute path" in call["stdin"]
    assert "Mother seated on the bench" in call["stdin"]                    # placement lines travel with the brief
    assert receipt["prompt_sha256"]
    workflow = json.loads(Path(result["workflow"]["workflow"]).read_text(encoding="utf-8"))
    evidence = workflow["extra"]["jjv"]
    assert evidence["account_label"] == "acct1"
    assert evidence["codex_session_id"] == receipt["runtime_id"]
    note = next(node for node in workflow["nodes"] if node["type"] == "Note")["widgets_values"][0]
    assert "account_label: acct1" in note and f"codex_session_id: {receipt['runtime_id']}" in note


def test_no_token_ever_reaches_a_receipt_a_state_file_or_a_summary(tmp_path):
    setup = Setup(tmp_path)
    result = setup.run()
    everything = "".join(p.read_text("utf-8", errors="ignore") for p in tmp_path.rglob("*.json")
                         if "homes" not in p.parts) + json.dumps(result)
    assert SECRET not in everything and "auth.json" not in everything.replace("auth_file_present", "")


def test_quota_on_account_one_fails_over_to_account_two_and_account_one_cools(tmp_path):
    setup = Setup(tmp_path)
    setup.flag("acct1", "quota.flag")
    result = setup.run()
    assert result["account_label"] == "acct2"
    assert [(f["label"], f["outcome"]) for f in result["failovers"]] == [("acct1", "quota")]
    assert result["failovers"][0]["cooling_seconds"] == 2 * 3600 + 30 * 60            # the time the message names
    state = pool.load_state(setup.state)
    assert state["last_good"] == "acct2" and state["cooling"]["acct1"] == 1_000_000.0 + 9000
    receipt = json.loads(Path(result["receipt"]).read_text("utf-8"))
    assert receipt["account_label"] == "acct2" and receipt["failovers"][0]["label"] == "acct1"
    assert len(setup.calls("acct1")) == 1 and len(setup.calls("acct2")) == 1


def test_selection_is_sticky_and_a_cooling_account_is_skipped_until_it_cools_down(tmp_path):
    setup = Setup(tmp_path)
    setup.flag("acct1", "quota.flag", "usage limit reached")                      # no time named -> default 1 h
    first = setup.run()
    assert first["account_label"] == "acct2" and first["failovers"][0]["cooling_seconds"] == 3600
    (setup.accounts[0].codex_home / "quota.flag").unlink()
    second = setup.run(take="t900")
    assert second["account_label"] == "acct2" and second["failovers"] == []        # sticky + acct1 still cooling
    assert len(setup.calls("acct1")) == 1
    setup.clock[0] += 3601
    third = setup.run(take="t901")
    assert third["account_label"] == "acct2"                                       # sticky to the last good one, not back to acct1
    pool.mark_cooling(state := pool.load_state(setup.state), "acct2", setup.clock[0] + 100, "quota", setup.clock[0])
    pool.save_state(setup.state, state)
    fourth = setup.run(take="t902")
    assert fourth["account_label"] == "acct1"                                      # acct2 cooling, acct1 is back


def test_every_account_failing_is_uncertain_and_each_account_is_tried_once(tmp_path):
    setup = Setup(tmp_path, accounts=3)
    for label in ("acct1", "acct2", "acct3"):
        setup.flag(label, "quota.flag")
    with pytest.raises(Uncertain, match="no codex account could make the image") as caught:
        setup.run()
    assert [f["outcome"] for f in caught.value.evidence["failovers"]] == ["quota"] * 3
    assert all(len(setup.calls(label)) == 1 for label in ("acct1", "acct2", "acct3"))
    with pytest.raises(Uncertain, match="every codex account is cooling"):
        setup.run(take="t900")
    assert all(len(setup.calls(label)) == 1 for label in ("acct1", "acct2", "acct3"))   # nothing was spawned


def test_auth_failure_and_a_missing_auth_file_also_move_to_the_next_account(tmp_path):
    setup = Setup(tmp_path, accounts=3)
    (setup.accounts[0].codex_home / "auth.json").unlink()                          # not logged in: file absent
    setup.flag("acct2", "auth.flag")
    result = setup.run()
    assert result["account_label"] == "acct3"
    assert [(f["label"], f["outcome"]) for f in result["failovers"]] == [("acct1", "no_auth_file"), ("acct2", "auth")]
    assert not setup.calls("acct1")                                                # never spawned without a login


def test_timeout_is_uncertain_with_no_failover_and_no_retry(tmp_path):
    setup = Setup(tmp_path)
    setup.flag("acct1", "hang.flag")
    with pytest.raises(Uncertain, match="exceeded"):
        setup.run(timeout=1)
    assert len(setup.calls("acct1")) == 1 and not setup.calls("acct2")
    assert not list((setup.out / "S01_A" / "candidates").glob("*.png")) if (setup.out / "S01_A" / "candidates").exists() else True


@pytest.mark.parametrize("flag, match", [("two.flag", "ambiguous"), ("nothing.flag", "produced no image")])
def test_two_images_or_none_is_never_adopted(tmp_path, flag, match):
    setup = Setup(tmp_path)
    setup.flag("acct1", flag)
    with pytest.raises(Uncertain, match=match):
        setup.run()
    assert not list((setup.out / "S01_A" / "candidates").glob("*")) if (setup.out / "S01_A" / "candidates").exists() else True
    assert not setup.calls("acct2")


def test_dry_run_writes_the_prompt_and_argv_and_spawns_nothing(tmp_path):
    setup = Setup(tmp_path)
    result = setup.run(dry_run=True)
    assert result["dry_run"] and result["account_order"] == ["acct1", "acct2"] and not setup.calls("acct1")
    assert result["take"] == "t001" and result["prompt_sha256"]
    assert not (setup.out / "S01_A" / "codex-exec").exists()  # N25: dry-run creates nothing
    assert "-i" in result["argv_without_prompt"] and not setup.state.exists()


def test_cooling_text_and_failure_kind_parsing():
    assert codex.cooling_seconds("Try again in 45 minutes.", 99) == 2700
    assert codex.cooling_seconds("retry after 3h", 99) == 10800
    assert codex.cooling_seconds("usage limit", 99) == 99
    recipe = json.loads((Path(codex.__file__).parents[2] / "recipes" / "images" / "codex-exec-v001.json").read_text("utf-8"))
    assert codex.failure_kind("HTTP 429 Too Many Requests", recipe) == "quota"
    assert codex.failure_kind("id 74290a", recipe) is None                           # digits inside an id are not a status
    assert codex.failure_kind("please log in", recipe) == "auth"
    assert codex.thread_id('noise\n{"type":"thread.started","thread_id":"abc-123"}\n') == "abc-123"
    assert codex.thread_id("no json here") is None


def test_accounts_come_from_machine_config_or_the_flag_and_labels_are_validated(tmp_path):
    machine = {"images": {"codex_accounts": [{"label": "a", "codex_home": str(tmp_path / "a")},
                                             {"label": "b", "codex_home": str(tmp_path / "b")}]}}
    assert [a.label for a in pool.accounts_from(machine, None)] == ["a", "b"]
    assert [a.label for a in pool.accounts_from(machine, [f"z={tmp_path}"])] == ["z"]
    with pytest.raises(Refused):
        pool.accounts_from({"images": {"codex_accounts": [{"label": "a", "codex_home": "x"}] * 2}}, None)
    with pytest.raises(Refused):
        pool.accounts_from({}, ["no-equals-sign"])


def test_cli_end_to_end_with_the_binary_and_accounts_from_machine_config(tmp_path, monkeypatch):
    setup = Setup(tmp_path)
    setup.world.machine["images"] = {"codex_bin": python_cmd(FAKE), "codex_accounts": [
        {"label": a.label, "codex_home": str(a.codex_home)} for a in setup.accounts]}
    setup.world.write_machine()
    monkeypatch.setenv("FAKE_CODEX_PNG", str(setup.png))
    setup.flag("acct1", "quota.flag")
    code, summary = run_images(["submit", "--episode", str(setup.world.root), "--out", str(setup.out), "--machine",
                                str(setup.world.machine_path), "--shot", "S01_A", "--provider", "codex-exec",
                                "--prompt-file", str(setup.prompt), "--timeout", "30"])
    assert code == 0 and summary["account_label"] == "acct2" and summary["failovers"][0]["label"] == "acct1"
    assert (setup.out / "codex-pool-state.json").is_file()
    code, listing = run_images(["compare", "--episode", str(setup.world.root), "--out", str(setup.out),
                                "--machine", str(setup.world.machine_path), "--shot", "S01_A"])
    assert code == 0 and listing["candidates"] == [summary["candidate_sha256"]]
    _ = (time, subprocess, sys, run_layout)


def test_the_auth_read_guard_itself_trips(tmp_path, no_auth_reads):
    """A guard that never fires proves nothing: reading auth.json under the fixture must fail loudly."""
    home = tmp_path / "h"
    home.mkdir()
    (home / "auth.json").write_text(SECRET, encoding="utf-8")
    with pytest.raises(AssertionError, match="tried to read"):
        (home / "auth.json").read_text(encoding="utf-8")
    with pytest.raises(AssertionError, match="tried to read"):
        open(home / "auth.json", "rb")
    assert pool.Account("x", home).auth_present                      # existence is allowed
