"""N19-fix: take numbers are claimed atomically (mkdir), so two lanes on ONE shot never collide; FAKE codex only."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from engine.core.errors import Uncertain
from engine.images import codex
from images_fixtures import python_cmd
from test_images_codex import FAKE, Setup


def many(setup: Setup, n: int, **kw):
    return codex.submit_many(setup.world.ctx(), setup.out, "S01_A", setup.prompt, setup.accounts, n=n,
                             codex_cmd=python_cmd(FAKE), state_path=setup.state, base_env=kw.pop("env", setup.env),
                             clock=lambda: setup.clock[0], timeout=30, **kw)


def folders(setup: Setup) -> list[str]:
    root = setup.out / "S01_A" / "codex-exec"
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def test_two_lanes_same_shot_get_six_distinct_takes_and_no_crash(tmp_path):
    setup = Setup(tmp_path, accounts=2)
    env = {**setup.env, "FAKE_CODEX_SLEEP": "0.3"}
    errors, got = [], []

    def lane(label: str) -> None:
        try:
            got.extend(t["take"] for t in many(setup, 3, account=label, env=env)["takes"])
        except Exception as error:  # the test reports whatever escaped
            errors.append((label, type(error).__name__, str(error)[:120]))

    threads = [threading.Thread(target=lane, args=(label,)) for label in ("acct1", "acct2")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert len(got) == 6 and len(set(got)) == 6
    assert folders(setup) == sorted(got)


def test_take_claim_skips_a_folder_taken_between_numbering_and_mkdir(tmp_path, monkeypatch):
    setup = Setup(tmp_path)
    base = setup.out / "S01_A" / "codex-exec"
    real = codex.next_take
    calls = []

    def racing(folder, *a, **k):
        name = real(folder, *a, **k)
        if not calls:  # another lane grabs the number we were just given
            (Path(folder) / name).mkdir(parents=True)
        calls.append(name)
        return name

    monkeypatch.setattr(codex, "next_take", racing)
    result = setup.run()
    assert calls[:2] == ["t001", "t002"] and result["take"] == "t002"
    assert (base / "t001").is_dir()


def test_all_accounts_cooling_creates_no_empty_folder(tmp_path):
    setup = Setup(tmp_path)
    setup.flag("acct1", "quota.flag")
    setup.flag("acct2", "quota.flag")
    with pytest.raises(Uncertain):
        setup.run()  # both cool down (failover), take t001 keeps its failovers.json
    before = folders(setup)
    with pytest.raises(Uncertain, match="cooling"):
        setup.run()
    assert folders(setup) == before


def test_mid_batch_failure_still_lists_finished_takes(tmp_path):
    setup = Setup(tmp_path, accounts=1)
    calls = {"n": 0}

    def runner(argv, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            (setup.accounts[0].codex_home / "quota.flag").write_text("", encoding="utf-8")
        return codex.default_runner(argv, **kw)

    with pytest.raises(Uncertain) as caught:
        many(setup, 5, runner=runner, account="acct1")
    done = caught.value.evidence["completed_takes"]
    assert [row["take"] for row in done] == ["t001", "t002"]
    assert all(row["receipt"] for row in done)
