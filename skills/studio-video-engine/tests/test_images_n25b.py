"""N25b: adopt binds --source-path to the adopted BYTES (exists, resolves inside a codex generated_images, same sha as
--file); --dry-run --take checks an existing folder like a real run; role sentences (identity token, no 'reference reference')."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.images import codex
from images_fixtures import make_png, run_images
from test_images_codex import Setup
from test_images_flow import Flow
from images_fixtures import LIVE
from test_images_n25 import live_flow


def adopt_args(flow: Flow, png: Path, src: Path) -> tuple:
    return flow.run("adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin", "--prompt-file", str(flow.prompt),
                    "--refs-from-plan", "--requested-model", "gpt-image-2", "--source-path", str(src))


def make_link(link: Path, target: Path) -> bool:
    """A directory junction (no privilege needed on Windows), else a symlink; False when neither can be made."""
    try:
        if os.name == "nt":
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
            return done.returncode == 0
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def test_live_adopt_source_that_does_not_exist_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    code, out = adopt_args(flow, png, tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "ghost.png")
    assert code == 1 and "does not exist" in json.dumps(out)
    assert not (flow.out / "S01_A" / "candidates").exists()


def test_live_adopt_source_with_other_bytes_than_the_file_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    src = make_png(tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "x.png", (9, 9, 9), (1672, 941))
    make_rollout(tmp_path / "home", "019a3c1e-0000-7000-8000-00000000000a", "x.png")  # N25c: reach the sha256 check
    code, out = adopt_args(flow, png, src)
    assert code == 1 and "sha256" in json.dumps(out)
    assert not (flow.out / "S01_A" / "candidates").exists()


def test_live_adopt_source_reached_through_a_junction_to_comfy_output_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    comfy_out = tmp_path / "comfy" / "output"
    comfy_out.mkdir(parents=True, exist_ok=True)
    shutil.copy(png, comfy_out / "x.png")  # SAME bytes: only the link target can give it away
    (tmp_path / "home" / "generated_images").mkdir(parents=True)
    if not make_link(tmp_path / "home" / "generated_images" / "link", comfy_out):
        pytest.skip("cannot create a junction or symlink here")
    code, out = adopt_args(flow, png, tmp_path / "home" / "generated_images" / "link" / "x.png")
    assert code == 1 and "generated_images" in json.dumps(out)
    assert not (flow.out / "S01_A" / "candidates").exists()


def test_live_adopt_with_real_matching_source_is_accepted_and_the_receipt_has_source_sha256(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    src = tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "exec-1.png"
    src.parent.mkdir(parents=True)
    shutil.copy(png, src)
    rollout = make_rollout(tmp_path / "home", "019a3c1e-0000-7000-8000-00000000000a", "exec-1.png")
    code, summary = adopt_args(flow, png, src)
    assert code == 0, summary
    receipt = json.loads(Path(summary["receipt"]).read_text("utf-8"))
    assert receipt["source_sha256"] == sha256_file(png) and receipt["source_path"] == str(src)
    assert receipt["source_session"] == "019a3c1e-0000-7000-8000-00000000000a" and receipt["source_rollout"] == rollout.as_posix()


def make_rollout(home: Path, session: str, name: str) -> Path:
    path = home / "sessions" / "2026" / "10" / "30" / f"rollout-2026-10-30T00-00-00-{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"item": f"saved generated_images/{session}/{name}"}), "utf-8")
    return path


def test_live_adopt_hand_copied_file_without_rollout_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    src = tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000b" / "x.png"
    src.parent.mkdir(parents=True)
    shutil.copy(png, src)
    code, out = adopt_args(flow, png, src)
    assert code == 1 and "rollout" in json.dumps(out)
    make_rollout(tmp_path / "home", "019a3c1e-0000-7000-8000-00000000000b", "other.png")  # rollout exists but does not name the file
    code, out = adopt_args(flow, png, src)
    assert code == 1 and "rollout" in json.dumps(out)


def test_live_adopt_hardlinked_file_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    comfy = tmp_path / "comfy.png"
    shutil.copy(png, comfy)
    src = tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000b" / "x.png"
    src.parent.mkdir(parents=True)
    try:
        os.link(comfy, src)
    except OSError:
        pytest.skip("cannot hardlink here")
    make_rollout(tmp_path / "home", "019a3c1e-0000-7000-8000-00000000000b", "x.png")
    code, out = adopt_args(flow, png, src)
    assert code == 1 and "hard link" in json.dumps(out)


def test_live_adopt_file_not_directly_under_a_session_folder_is_refused(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "a.png", (1, 2, 3), (1672, 941))
    src = tmp_path / "home" / "generated_images" / "019a3c1e-0000-7000-8000-00000000000b" / "deep" / "x.png"
    src.parent.mkdir(parents=True)
    shutil.copy(png, src)
    make_rollout(tmp_path / "home", "019a3c1e-0000-7000-8000-00000000000b", "x.png")
    code, out = adopt_args(flow, png, src)
    assert code == 1 and "<session>" in json.dumps(out)


def test_cartoon_adopt_keeps_trusting_a_missing_source_and_records_no_sha(tmp_path):
    flow = Flow(tmp_path)
    (code, summary), _ = flow.adopt()
    assert code == 0
    assert json.loads(Path(summary["receipt"]).read_text("utf-8"))["source_sha256"] is None


def test_dry_run_with_an_existing_take_name_is_refused_like_a_real_run(tmp_path):
    setup = Setup(tmp_path)
    setup.run(take="t050")  # real run claims the folder
    with pytest.raises(Refused, match="exists"):
        setup.run(take="t050", dry_run=True)
    assert setup.run(take="t051", dry_run=True)["take"] == "t051"
    assert not (setup.out / "S01_A" / "codex-exec" / "t051").exists()


@pytest.mark.parametrize("role, identity", [("identity", True), ("face_identity", True), ("Identity_master", True),
                                            ("wardrobe_vest_front_geometry_no_identity_replace_department", False),
                                            ("wardrobe_only", False), ("mandatory_white_vest_logo", False)])
def test_identity_sentence_goes_by_the_identity_token(role, identity):
    line = codex._ref_line(2, role, True, "x.png")
    assert ("keep this exact character" in line) is identity, line
    assert ("do NOT take" in line) is (not identity), line


@pytest.mark.parametrize("role", ["reference", "", "  "])
def test_a_ref_without_a_role_does_not_say_reference_reference(role):
    line = codex._ref_line(3, role, True, "x.png")
    assert "reference reference" not in line and "do NOT take" in line and "[x.png]" in line


def test_a_role_ending_in_reference_is_not_doubled():
    assert "reference reference" not in codex._ref_line(2, "wardrobe_reference", True, None)
