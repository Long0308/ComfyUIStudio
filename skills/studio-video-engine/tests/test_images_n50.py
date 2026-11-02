"""N50: library character images (receipt jjv/library-image-receipt/v1, made by the engine through FAKE codex) can be
compared and approved: compare lists every take of a prompt_id across lanes, approve binds a user's pick to a sha with
the 4-item checklist, an approval goes stale when the bytes change. Shot mode is untouched (its own tests)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from engine.core.errors import Refused
from engine.images import library
from images_fixtures import run_images
from test_images_n23fix import Lib

PID = "CHAR_07_1_r005"
ITEMS = ["identity", "wardrobe_r005", "logo", "real_skin"]


def two_lanes(lib: Lib) -> dict:
    """Lane acct1 and lane acct2 each run a batch (own file) whose prompt_ids are the same: 2 takes per prompt_id."""
    a = lib.run(lib.batch_file("laneA", 2, id_prefix="CHAR_07"), account="acct1")
    b = lib.run(lib.batch_file("laneB", 2, id_prefix="CHAR_07"), account="acct2")
    return {"a": a, "b": b}


def fill(path: Path, sha: str, status: str = "pass", only=None) -> None:
    sheet = json.loads(path.read_text("utf-8"))
    for item in only or ITEMS:
        sheet["candidates"][sha][item] = {"status": status, "note": "looked at the pixels"}
    path.write_text(json.dumps(sheet), encoding="utf-8")


def test_compare_lists_the_takes_of_both_lanes_with_account_and_refs(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    out = library.compare(lib.world.ctx(), lib.lib_out, prompt_id=PID)
    shas = {runs["a"]["takes"][0]["candidate_sha256"], runs["b"]["takes"][0]["candidate_sha256"]}
    assert set(out["candidates"]) == shas and len(out["candidates"]) == 2
    assert {r["account_label"] for r in out["takes"]} == {"acct1", "acct2"}
    assert out["checklist_items"] == ITEMS and Path(out["sheet"]).is_file()
    assert len(json.loads(Path(out["record"]).read_text("utf-8"))["refs"]) == 3
    image = Image.open(out["sheet"])
    assert image.width > 300 and image.height > 100
    checklist = json.loads(Path(out["checklist"]).read_text("utf-8"))
    assert all(checklist["candidates"][s][i]["status"] == "unreviewed" for s in shas for i in ITEMS)


def test_compare_by_character_lists_every_prompt_of_that_character(tmp_path):
    lib = Lib(tmp_path)
    two_lanes(lib)
    out = library.compare(lib.world.ctx(), lib.lib_out, character="CHAR_07")
    assert len(out["candidates"]) == 4
    with pytest.raises(Refused, match="no library take"):
        library.compare(lib.world.ctx(), lib.lib_out, prompt_id="CHAR_99_1_r005")
    with pytest.raises(Refused, match="exactly one"):
        library.compare(lib.world.ctx(), lib.lib_out, prompt_id=PID, character="CHAR_07")


def test_rerunning_compare_keeps_a_reviewed_checklist_entry(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    sha = runs["a"]["takes"][0]["candidate_sha256"]
    first = library.compare(lib.world.ctx(), lib.lib_out, prompt_id=PID)
    fill(Path(first["checklist"]), sha)
    library.compare(lib.world.ctx(), lib.lib_out, prompt_id=PID)
    assert json.loads(Path(first["checklist"]).read_text("utf-8"))["candidates"][sha]["identity"]["status"] == "pass"


def test_approve_wrong_sha_is_refused(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    ctx = lib.world.ctx()
    library.compare(ctx, lib.lib_out, prompt_id=PID)
    other_prompt = runs["a"]["takes"][1]["candidate_sha256"]  # a real take, but of ANOTHER prompt_id
    for bad in ("0" * 64, "deadbeef", "abc", other_prompt):
        with pytest.raises(Refused):
            library.approve(ctx, lib.lib_out, bad, prompt_id=PID, reviewer="user", scope="CHAR_07 face 1")
    assert not list((lib.lib_out / "_review").glob("**/approval-v*.json"))


def test_approve_needs_every_checklist_item_pass_reviewer_and_scope(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    ctx = lib.world.ctx()
    sha = runs["a"]["takes"][0]["candidate_sha256"]
    cmp_ = library.compare(ctx, lib.lib_out, prompt_id=PID)
    with pytest.raises(Refused, match="not 'pass'"):
        library.approve(ctx, lib.lib_out, sha, prompt_id=PID, reviewer="user", scope="s")
    fill(Path(cmp_["checklist"]), sha, only=ITEMS[:3])  # real_skin still unreviewed
    with pytest.raises(Refused, match="real_skin"):
        library.approve(ctx, lib.lib_out, sha, prompt_id=PID, reviewer="user", scope="s")
    fill(Path(cmp_["checklist"]), sha)
    with pytest.raises(Refused, match="--reviewer"):
        library.approve(ctx, lib.lib_out, sha, prompt_id=PID, reviewer=" ", scope="s")


def test_approve_is_versioned_binds_the_sha_and_goes_stale_when_the_bytes_change(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    ctx = lib.world.ctx()
    a, b = runs["a"]["takes"][0], runs["b"]["takes"][0]
    cmp_ = library.compare(ctx, lib.lib_out, prompt_id=PID)
    for take in (a, b):
        fill(Path(cmp_["checklist"]), take["candidate_sha256"])
    first = library.approve(ctx, lib.lib_out, a["candidate_sha256"][:12], prompt_id=PID, reviewer="user", scope="CHAR_07 face 1")
    assert first["approval"].endswith("approval-v001.json") and first["supersedes"] is None
    current = library.current_approval(lib.lib_out, PID)
    assert current["candidate_sha256"] == a["candidate_sha256"] and current["batch_id"] == "laneA"
    second = library.approve(ctx, lib.lib_out, b["candidate_sha256"], prompt_id=PID, reviewer="user", scope="CHAR_07 face 1 (lane B)")
    assert second["approval"].endswith("approval-v002.json") and second["supersedes"] == first["approval"]
    assert library.current_approval(lib.lib_out, PID)["candidate_sha256"] == b["candidate_sha256"]
    image = Path(json.loads(Path(b["receipt"]).read_text("utf-8"))["output"]["path"])
    image.write_bytes(image.read_bytes() + b"x")  # the approved bytes change
    assert library.current_approval(lib.lib_out, PID) is None  # stale: the older v001 is not revived
    with pytest.raises(Refused, match="no longer matches"):
        library.approve(ctx, lib.lib_out, b["candidate_sha256"], prompt_id=PID, reviewer="user", scope="again")


def test_approval_goes_stale_when_a_reference_changes(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    ctx = lib.world.ctx()
    a = runs["a"]["takes"][0]
    cmp_ = library.compare(ctx, lib.lib_out, prompt_id=PID)
    fill(Path(cmp_["checklist"]), a["candidate_sha256"])
    library.approve(ctx, lib.lib_out, a["candidate_sha256"], prompt_id=PID, reviewer="user", scope="s")
    lib.refs[0].write_bytes(lib.refs[0].read_bytes() + b"x")
    assert library.current_approval(lib.lib_out, PID) is None
    with pytest.raises(Refused, match="changed"):
        library.compare(ctx, lib.lib_out, prompt_id=PID)


def cli(lib: Lib, verb: str, *extra: str):
    return run_images([verb, "--episode", str(lib.world.root), "--out", str(lib.tmp / "images"), "--machine",
                       str(lib.world.machine_path), *extra])


def test_cli_library_compare_then_approve_end_to_end_and_the_forbidden_combinations(tmp_path):
    lib = Lib(tmp_path)
    runs = two_lanes(lib)
    sha = runs["b"]["takes"][0]["candidate_sha256"]
    code, cmp_ = cli(lib, "compare", "--library-out", str(lib.lib_out), "--prompt-id", PID)
    assert code == 0 and len(cmp_["candidates"]) == 2, cmp_
    fill(Path(cmp_["checklist"]), sha)
    code, bad = cli(lib, "approve", "--library-out", str(lib.lib_out), "--prompt-id", PID, "--sha", "0" * 64, "--reviewer", "u", "--scope", "s")
    assert code == 1
    code, ok = cli(lib, "approve", "--library-out", str(lib.lib_out), "--prompt-id", PID, "--sha", sha, "--reviewer", "user", "--scope", "s")
    assert code == 0 and ok["candidate_sha256"] == sha and ok["approval"].endswith("approval-v001.json")
    for verb, extra in (("compare", []), ("approve", ["--sha", sha, "--reviewer", "u", "--scope", "s"])):
        assert cli(lib, verb, "--library-out", str(lib.lib_out), "--prompt-id", PID, "--shot", "S01_A", *extra)[0] == 1
        assert cli(lib, verb, "--library-out", str(lib.lib_out), *extra)[0] == 1  # neither --prompt-id nor --character
        assert cli(lib, verb, "--prompt-id", PID, *extra)[0] == 1  # --prompt-id without --library-out
        assert cli(lib, verb, *extra)[0] == 1  # no --shot and no --library-out
