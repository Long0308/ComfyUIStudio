"""Guard: a take rejected in one --out folder is refused in a FRESH --out folder of the same episode (episode ledger).

The broader scenario (with a forged pick in the second folder) already exists as
test_h3_m7.py::test_rejection_is_episode_wide_not_scoped_to_the_out_folder.  This file adds the clean case that test
does not cover: a plain copy with no acceptance history and no forgery must still be refused and must not be listed.
"""

from __future__ import annotations

import shutil

import pytest
from fake_comfy import FakeComfy
from h3_fixtures import SHOT, FakeProbe, H3World, fake_with_video, ok_ps, run_h3
from test_h3_inputs_m8b import library_stub  # noqa: F401  (library_stub: fixture)

from engine.comfy.client import ComfyClient
from engine.core.errors import Refused
from engine.h3 import accept, adopt, submit


pytestmark = pytest.mark.usefixtures("library_stub")

@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def _go(world: H3World, fake: FakeComfy):
    return submit.submit(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5),
                         probe=FakeProbe(), ps=ok_ps, wait_timeout=5, approve_gpu=True)


def _adopted_world(tmp_path, fake: FakeComfy) -> H3World:
    world = H3World(tmp_path, comfy_url=fake.url)
    fake_with_video(world, fake)
    world.prepare()
    _go(world, fake)
    adopt.adopt(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5))
    return world


def _fresh_out_with_same_take(world: H3World, name: str):
    """A new --out folder holding the same adopted take, copied WITHOUT the acceptance folder (no history)."""
    other = world.tmp / name
    shutil.copytree(world.out / SHOT, other / SHOT, ignore=shutil.ignore_patterns("acceptance"))
    return other


def test_reject_in_out_a_then_fresh_out_b_refuses_pick_and_lists_nothing(tmp_path, fake) -> None:
    world = _adopted_world(tmp_path, fake)
    ctx = world.ctx()
    sha = accept.status(world.out, ctx=ctx)[0]["sha256"]
    accept.decide(world.out, SHOT, "reject", by="Kim", reason="lips drift at 3s", ctx=ctx)

    out_b = _fresh_out_with_same_take(world, "h3out-b")
    assert accept.status(out_b, ctx=ctx)[0]["sha256"] == sha  # the copied take is the same adopted take

    with pytest.raises(Refused, match="rejected"):
        accept.decide(out_b, SHOT, "pick", by="Kim", reason="fresh folder", ctx=ctx)
    assert not (out_b / SHOT / "acceptance").exists()  # the refused pick wrote nothing

    assert accept.accepted_takes(out_b, ctx=ctx) == []  # episode ledger: not listed as accepted
    assert accept.status(out_b, ctx=ctx)[0]["review"] == "rejected"
    with pytest.raises(Refused, match="never reach the edit"):
        accept.require_accepted(out_b, SHOT, sha, ctx=ctx)


def test_cli_pick_in_fresh_out_b_is_refused_with_no_acceptance_written(tmp_path, fake) -> None:
    world = _adopted_world(tmp_path, fake)
    ctx = world.ctx()
    accept.decide(world.out, SHOT, "reject", by="Kim", reason="lips drift at 3s", ctx=ctx)
    out_b = _fresh_out_with_same_take(world, "h3out-b")
    base = ["--episode", str(world.root), "--out", str(out_b), "--machine", str(world.world.machine_path)]
    code, _ = run_h3(["accept", *base, "--shot", SHOT, "--pick", "--by", "Kim", "--reason", "fresh folder"])
    assert code != 0
    assert not (out_b / SHOT / "acceptance").exists()
    code, body = run_h3(["accept", *base, "--list"])
    assert code == 0 and body["accepted"] == []

