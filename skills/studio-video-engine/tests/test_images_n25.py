"""N25: adopt proves its source for NEWTECONS; codex-exec dry-run creates no folder; ref sentences follow the role;
--prompt-batch combinations are refused through the CLI. FAKE codex only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import codex
from images_fixtures import LIVE, make_png, python_cmd, run_images
from test_images_codex import FAKE, Setup
from test_images_codex_batch import batch, codex_dir, write_batch
from test_images_codex_n import many
from test_images_flow import Flow


def live_flow(tmp: Path, home: Path | None = None) -> Flow:
    flow = Flow(tmp, domain=LIVE)
    if home is not None:
        flow.world.machine["images"] = {"codex_accounts": [{"label": "acct1", "codex_home": str(home)}]}
        flow.world.write_machine()
    return flow


def test_live_adopt_without_source_path_or_model_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    base = ["--shot", "S01_A", "--file", str(png), "--route", "codex-builtin", "--prompt-file", str(flow.prompt), "--refs-from-plan"]
    code, out = flow.run("adopt", *base, "--requested-model", "GPT Image Gen 2")
    assert code == 1 and "--source-path" in json.dumps(out)
    code, out = flow.run("adopt", *base, "--source-path", str(tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "x.png"))
    assert code == 1 and "--requested-model" in json.dumps(out)


def test_live_adopt_source_outside_codex_generated_images_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    for bad in (tmp_path / "comfy" / "output" / "x.png", tmp_path / "home" / "other" / "x.png",
                tmp_path / "home" / "generated_images" / ".." / "x.png"):
        code, out = flow.run("adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin", "--prompt-file",
                             str(flow.prompt), "--refs-from-plan", "--requested-model", "GPT Image Gen 2", "--source-path", str(bad))
        assert code == 1 and "generated_images" in json.dumps(out), bad
    assert not (flow.out / "S01_A" / "candidates").exists()


def test_live_adopt_with_machine_codex_home_source_and_model_is_accepted(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    src = tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "exec-1.png"
    src.parent.mkdir(parents=True)
    shutil.copy(png, src)  # N25b: the source must exist and carry the adopted bytes
    from images_fixtures import write_rollout
    write_rollout(tmp_path / "home", "019a3c1e-0000-7000-8000-00000000000a", "exec-1.png")  # N25c: a rollout of the session must name the file
    code, summary = flow.run("adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin", "--prompt-file",
                             str(flow.prompt), "--refs-from-plan", "--requested-model", "gpt-image-2", "--source-path", str(src))
    assert code == 0 and summary["requested_model"] == "gpt-image-2"


def test_live_adopt_with_no_codex_account_in_machine_is_refused(tmp_path):
    flow = live_flow(tmp_path)
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    code, out = flow.run("adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin", "--prompt-file",
                         str(flow.prompt), "--refs-from-plan", "--requested-model", "m", "--source-path", "C:/x/generated_images/a/b.png")
    assert code == 1 and "codex" in json.dumps(out)


def test_cartoon_adopt_keeps_the_old_behaviour(tmp_path):
    flow = Flow(tmp_path)
    (code, summary), _ = flow.adopt()
    assert code == 0 and summary["requested_model"] == "GPT Image Gen 2"


def test_dry_run_n_creates_no_folder_and_no_prompt(tmp_path):
    setup = Setup(tmp_path)
    result = many(setup, 3, dry_run=True)
    assert [t["take"] for t in result["takes"]] == ["t001", "t002", "t003"]
    assert all(t["prompt_sha256"] for t in result["takes"])
    assert not codex_dir(setup).exists() and not setup.calls("acct1")


def test_dry_run_batch_creates_no_folder_and_names_ten_takes(tmp_path):
    setup = Setup(tmp_path)
    result = batch(setup, write_batch(tmp_path, "dry", 10), dry_run=True)
    assert [t["take"] for t in result["takes"]] == [f"t{i:03d}" for i in range(1, 11)]
    assert not codex_dir(setup).exists()


def test_dry_run_numbers_continue_after_real_takes(tmp_path):
    setup = Setup(tmp_path)
    setup.run()
    result = many(setup, 2, dry_run=True)
    assert [t["take"] for t in result["takes"]] == ["t002", "t003"]
    assert sorted(p.name for p in codex_dir(setup).iterdir()) == ["t001"]


def test_roles_get_their_own_sentence_not_identity(tmp_path):
    setup = Setup(tmp_path)
    path = write_batch(tmp_path, "roles", 1)
    items = json.loads(path.read_text("utf-8"))
    logo = make_png(tmp_path / "logo.png", (9, 9, 9), (32, 32))
    items[0]["ref_images"].append({"path": str(logo), "role": "wardrobe_only"})
    path.write_text(json.dumps(items), encoding="utf-8")
    batch(setup, path)
    stdin = (setup.calls("acct1") + setup.calls("acct2"))[0]["stdin"]
    lines = {line.split(":")[0]: line for line in stdin.splitlines() if line.startswith("Image ")}
    assert "identity reference" in lines["Image 2"]
    assert "wardrobe only" in lines["Image 3"] and "identity reference" not in lines["Image 3"]


def cli_args(setup: Setup, *extra: str) -> list[str]:
    setup.world.machine["images"] = {"batch_ref_roots": [str(setup.world.tmp)], "codex_bin": python_cmd(FAKE), "codex_accounts": [
        {"label": a.label, "codex_home": str(a.codex_home)} for a in setup.accounts]}
    setup.world.write_machine()
    return ["submit", "--episode", str(setup.world.root), "--out", str(setup.out), "--machine", str(setup.world.machine_path),
            "--shot", "S01_A", "--provider", "codex-exec", "--dry-run", *extra]


@pytest.mark.parametrize("extra", [["--n", "2"], ["--take", "t900"], ["--prompt-file", "BRIEF"]])
def test_prompt_batch_with_n_take_or_prompt_file_is_refused_via_cli(tmp_path, extra):
    setup = Setup(tmp_path)
    path = write_batch(tmp_path, "cli", 2)
    extra = [str(setup.prompt) if e == "BRIEF" else e for e in extra]
    code, _ = run_images(cli_args(setup, "--prompt-batch", str(path), *extra))
    assert code == 1 and not codex_dir(setup).exists()


def test_prompt_batch_alone_works_via_cli_and_other_providers_refuse_it(tmp_path):
    setup = Setup(tmp_path)
    path = write_batch(tmp_path, "cli2", 2)
    code, summary = run_images(cli_args(setup, "--prompt-batch", str(path)))
    assert code == 0 and summary["n"] == 2
    args = cli_args(setup, "--prompt-batch", str(path))
    args[args.index("--provider") + 1] = "comfyui-local"
    code, _ = run_images(args)
    assert code == 1
