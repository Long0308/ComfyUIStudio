"""N19: ``jjv images submit --provider codex-exec --n N`` makes N takes (one folder + one receipt each); FAKE codex only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import codex
from images_fixtures import python_cmd, run_images
from test_images_codex import FAKE, SECRET, Setup


def many(setup: Setup, n: int, **kw):
    return codex.submit_many(setup.world.ctx(), setup.out, "S01_A", setup.prompt, setup.accounts, n=n,
                             codex_cmd=python_cmd(FAKE), state_path=setup.state, base_env=setup.env,
                             clock=lambda: setup.clock[0], timeout=30, **kw)


def takes(setup: Setup) -> list[Path]:
    return sorted(p for p in (setup.out / "S01_A" / "codex-exec").iterdir() if p.is_dir())


def test_n10_dry_run_plans_ten_takes_and_sends_nothing(tmp_path):
    setup = Setup(tmp_path)
    result = many(setup, 10, dry_run=True)
    assert result["n"] == 10 and result["dry_run"] and result["submitted"] is False
    assert [t["take"] for t in result["takes"]] == [f"t{i:03d}" for i in range(1, 11)]
    assert not (setup.out / "S01_A" / "codex-exec").exists() and not setup.calls("acct1")  # N25: no folder in dry-run and not setup.state.exists()


def test_n_above_the_limit_is_refused_before_any_folder(tmp_path):
    setup = Setup(tmp_path)
    with pytest.raises(Refused, match="--n"):
        many(setup, codex.MAX_N + 1, dry_run=True)
    with pytest.raises(Refused, match="--n"):
        many(setup, 0, dry_run=True)
    assert not (setup.out / "S01_A" / "codex-exec").exists() and not setup.calls("acct1")


def test_n1_keeps_the_old_single_result_shape(tmp_path):
    setup = Setup(tmp_path)
    result = many(setup, 1)
    assert "takes" not in result and result["take"] == "t001" and result["submitted"] is True
    assert Path(result["receipt"]).is_file()


def test_real_n3_makes_three_takes_each_with_its_own_receipt_and_no_token(tmp_path):
    setup = Setup(tmp_path)
    result = many(setup, 3)
    assert result["n"] == 3 and len(result["takes"]) == 3
    shas = [t["candidate_sha256"] for t in result["takes"]]
    assert len(set(shas)) == 3
    for row in result["takes"]:
        receipt = json.loads(Path(row["receipt"]).read_text("utf-8"))
        assert receipt["schema"] == "jjv/image-receipt/v1" and receipt["output"]["sha256"] == row["candidate_sha256"]
        assert SECRET not in json.dumps(receipt)
    assert SECRET not in json.dumps(result)
    assert len(setup.calls("acct1")) == 3


def test_take_name_cannot_be_combined_with_n(tmp_path):
    setup = Setup(tmp_path)
    with pytest.raises(Refused, match="--take"):
        many(setup, 2, take="t900", dry_run=True)


@pytest.mark.parametrize("provider, extra", [("comfyui-local", ["--pilot"]), ("openrouter", ["--spend-ok"])])
def test_other_providers_refuse_n_greater_than_one_with_nothing_sent(tmp_path, provider, extra):
    setup = Setup(tmp_path)
    code, _ = run_images(["submit", "--episode", str(setup.world.root), "--out", str(setup.out), "--machine",
                          str(setup.world.machine_path), "--shot", "S01_A", "--provider", provider,
                          "--prompt-file", str(setup.prompt), "--n", "2", "--dry-run", *extra])
    assert code == 1
    assert not (setup.out / "S01_A" / provider.replace("comfyui-local", "local")).exists()


def test_cli_accepts_n_for_codex_exec_dry_run(tmp_path):
    setup = Setup(tmp_path)
    setup.world.machine["images"] = {"codex_bin": python_cmd(FAKE), "codex_accounts": [
        {"label": a.label, "codex_home": str(a.codex_home)} for a in setup.accounts]}
    setup.world.write_machine()
    code, summary = run_images(["submit", "--episode", str(setup.world.root), "--out", str(setup.out), "--machine",
                                str(setup.world.machine_path), "--shot", "S01_A", "--provider", "codex-exec",
                                "--prompt-file", str(setup.prompt), "--n", "10", "--dry-run"])
    assert code == 0 and summary["n"] == 10 and len(summary["takes"]) == 10
