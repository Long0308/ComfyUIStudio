"""N87: two processes on ONE codex_home must not adopt each other's image (new = this run's session folder only)."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.errors import Uncertain
from engine.images import codex
from images_fixtures import python_cmd
from test_images_codex import FAKE, Setup


def drop(home, session: str) -> None:
    folder = home / "generated_images" / session
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"exec-{uuid.uuid4()}.png").write_bytes((home.parent.parent / "fake-image.png").read_bytes() + uuid.uuid4().bytes)


def runner_for(home, *, own: str | None, other: str | None, mine: bool, theirs: bool, upper: bool = False):
    def run(argv, input_text, env, cwd, timeout):
        if theirs:
            drop(home, other)  # the other process lands first
        if mine:
            drop(home, own)
        shown = own.upper() if upper else own
        out = f'{{"type": "thread.started", "thread_id": "{shown}"}}\n' if own else ""
        return SimpleNamespace(stdout=out, stderr="", returncode=0)
    return run


def submit(setup: Setup, runner):
    return codex.submit(setup.world.ctx(), setup.out, "S01_A", setup.prompt, setup.accounts[:1], codex_cmd=python_cmd(FAKE),
                        state_path=setup.state, base_env=setup.env, clock=lambda: setup.clock[0], timeout=30, runner=runner)


def test_other_sessions_image_is_not_adopted_when_this_run_made_none(tmp_path):
    setup = Setup(tmp_path, accounts=1)
    home = setup.accounts[0].codex_home
    with pytest.raises(Uncertain, match="no image"):
        submit(setup, runner_for(home, own=str(uuid.uuid4()), other=str(uuid.uuid4()), mine=False, theirs=True))


def test_both_sessions_landed_this_run_adopts_its_own(tmp_path):
    setup = Setup(tmp_path, accounts=1)
    home = setup.accounts[0].codex_home
    own, other = str(uuid.uuid4()), str(uuid.uuid4())
    result = submit(setup, runner_for(home, own=own, other=other, mine=True, theirs=True, upper=True))
    assert own in result["source_path"] and other not in result["source_path"]


def test_missing_thread_id_is_uncertain_and_adopts_nothing(tmp_path):
    setup = Setup(tmp_path, accounts=1)
    home = setup.accounts[0].codex_home
    run = runner_for(home, own=None, other=str(uuid.uuid4()), mine=False, theirs=True)
    with pytest.raises(Uncertain, match="no thread id"):
        submit(setup, run)

def test_timeout_without_thread_id_reports_other_session_images_as_unattributed(tmp_path):
    setup = Setup(tmp_path, accounts=1)
    home = setup.accounts[0].codex_home
    other = str(uuid.uuid4())

    def timed_out(argv, input_text, env, cwd, timeout):
        drop(home, other)
        raise subprocess.TimeoutExpired(argv, timeout, output="", stderr="")

    with pytest.raises(Uncertain, match="exceeded") as caught:
        submit(setup, timed_out)
    unknown = json.loads((Path(caught.value.evidence["folder"]) / "unknown.json").read_text("utf-8"))
    assert unknown["thread_id"] is None
    assert unknown["new_images"] == []
    assert len(unknown["unattributed_images_in_shared_home"]) == 1
    assert other in unknown["unattributed_images_in_shared_home"][0]
