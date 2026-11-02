"""N50-fix: library approvals are per prompt_id, stale-proof against the checklist, character-bounded, id-safe."""
import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.images import library
from test_images_n23fix import Lib

ITEMS = ["identity", "wardrobe_r005", "logo", "real_skin"]


def fill(path, sha, status="pass"):
    d = json.loads(Path(path).read_text("utf-8"))
    for i in ITEMS:
        d["candidates"][sha][i] = {"status": status, "note": "x"}
    Path(path).write_text(json.dumps(d), encoding="utf-8")


def test_two_prompts_of_one_character_keep_their_own_approvals(tmp_path):
    lib = Lib(tmp_path)
    r = lib.run(lib.batch_file("bA", 2, id_prefix="CHAR_08_FACE"), account="acct1")
    ctx = lib.world.ctx()
    s1, s2 = (t["candidate_sha256"] for t in r["takes"])
    c = library.compare(ctx, lib.lib_out, character="CHAR_08")
    fill(c["checklist"], s1)
    fill(c["checklist"], s2)
    a1 = library.approve(ctx, lib.lib_out, s1, character="CHAR_08", reviewer="u", scope="CHAR_08 face 1")
    a2 = library.approve(ctx, lib.lib_out, s2, character="CHAR_08", reviewer="u", scope="CHAR_08 face 2")
    assert a2["supersedes"] is None and a1["key"] != a2["key"]
    assert library.current_approval(lib.lib_out, "CHAR_08_FACE_1_r005")["candidate_sha256"] == s1
    assert library.current_approval(lib.lib_out, "CHAR_08_FACE_2_r005")["candidate_sha256"] == s2
    got = library.current_approvals(lib.lib_out, "CHAR_08")
    assert {k: v["candidate_sha256"] for k, v in got.items()} == {"CHAR_08_FACE_1_r005": s1, "CHAR_08_FACE_2_r005": s2}


def test_checklist_flipped_to_fail_after_approval_invalidates_it(tmp_path):
    lib = Lib(tmp_path)
    r = lib.run(lib.batch_file("bA", 1, id_prefix="CHAR_01_FACE"), account="acct1")
    pid, sha, ctx = "CHAR_01_FACE_1_r005", r["takes"][0]["candidate_sha256"], lib.world.ctx()
    c = library.compare(ctx, lib.lib_out, prompt_id=pid)
    fill(c["checklist"], sha)
    library.approve(ctx, lib.lib_out, sha, prompt_id=pid, reviewer="u", scope="s")
    assert library.current_approval(lib.lib_out, pid) is not None
    fill(c["checklist"], sha, "fail")
    assert library.current_approval(lib.lib_out, pid) is None


def test_character_selector_is_bounded_and_cross_character_is_refused(tmp_path):
    lib = Lib(tmp_path)
    lib.run(lib.batch_file("bA", 1, id_prefix="CHAR_01_FACE"), account="acct1")
    b = lib.run(lib.batch_file("bB", 1, id_prefix="CHAR_02_FACE"), account="acct2")
    ctx = lib.world.ctx()
    with pytest.raises(Refused):
        library.compare(ctx, lib.lib_out, character="CHAR")
    c = library.compare(ctx, lib.lib_out, character="CHAR_01")
    assert {t["prompt_id"] for t in c["takes"]} == {"CHAR_01_FACE_1_r005"}
    sha2 = b["takes"][0]["candidate_sha256"]
    with pytest.raises(Refused):
        library.approve(ctx, lib.lib_out, sha2, character="CHAR_01", reviewer="u", scope="s")
    c2 = library.compare(ctx, lib.lib_out, character="CHAR_02")
    fill(c2["checklist"], sha2)
    with pytest.raises(Refused):  # the scope names another character
        library.approve(ctx, lib.lib_out, sha2, character="CHAR_02", reviewer="u", scope="CHAR_01 face")


def test_character_code_must_not_prefix_match_a_longer_number(tmp_path):
    lib = Lib(tmp_path)
    lib.run(lib.batch_file("bA", 1, id_prefix="CHAR_010_FACE"), account="acct1")
    with pytest.raises(Refused):
        library.compare(lib.world.ctx(), lib.lib_out, character="CHAR_01")


@pytest.mark.parametrize("bad", ["../../ESCAPED", "a/b", "a\b", "x..y", "", "a b", "é"])
def test_prompt_id_chars_are_checked_before_any_write(tmp_path, bad):
    lib = Lib(tmp_path)
    with pytest.raises(Refused):
        library.compare(lib.world.ctx(), lib.lib_out, prompt_id=bad)
    with pytest.raises(Refused):
        library.approve(lib.world.ctx(), lib.lib_out, "a" * 8, prompt_id=bad, reviewer="u", scope="s")
    assert not (lib.lib_out / "_review").exists()


def test_batch_file_check_refuses_underscore_names_and_bad_prompt_ids(tmp_path):
    lib = Lib(tmp_path)
    with pytest.raises(Refused):
        library.check_batch_file(lib.batch_file("_review", 1, id_prefix="CHAR_03_FACE"))
    path = lib.batch_file("trav", 1, id_prefix="x")
    items = json.loads(path.read_text("utf-8"))
    items[0]["prompt_id"] = "../../ESCAPED"
    path.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(Refused):
        library.check_batch_file(path)
    library.check_batch_file(lib.batch_file("ok", 1, id_prefix="CHAR_03_FACE"))


def test_cli_submit_refuses_underscore_batch_even_as_dry_run(tmp_path):
    from images_fixtures import run_images
    from test_images_n23fix import lib_cli
    lib = Lib(tmp_path)
    path = lib.batch_file("_review", 1, id_prefix="CHAR_03_FACE")
    code, _ = run_images(lib_cli(lib, "--prompt-batch", str(path), "--library-out", str(lib.lib_out)))
    assert code == 1 and not lib.lib_out.exists()
