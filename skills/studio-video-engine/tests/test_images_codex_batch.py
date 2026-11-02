"""N23: ``jjv images submit --provider codex-exec --prompt-batch FILE``: one take per item, each with ITS prompt and refs.
FAKE codex only."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.images import codex
from images_fixtures import make_png, python_cmd
from test_images_codex import FAKE, SECRET, Setup, no_auth_reads  # noqa: F401

N27_DIR = Path(r"J:\1.JennieHomeSchool\03 Voice\production-local\engine\staging\newtecons-30s\image-batches")


def write_batch(tmp: Path, name: str, count: int, *, dup: bool = False, empty: int | None = None,
                missing_ref: bool = False) -> Path:
    ref = make_png(tmp / "ref-a.png", (200, 10, 10), (64, 64))
    items = []
    for i in range(count):
        pid = "ID_1" if dup and i == 1 else f"{name}_ID_{i + 1}"
        items.append({"prompt_id": pid, "prompt_text": "" if empty == i else f"PROMPT-{name}-{i + 1} un dieu",
                      "ref_images": [{"path": str(tmp / "nope.png") if missing_ref else str(ref),
                                      "sha256": sha256_file(ref), "role": "identity"}]})
    if dup:
        items[0]["prompt_id"] = "ID_1"
    path = tmp / f"{name}.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def allow_refs(setup: Setup) -> None:
    """N23-fix: batch refs must lie under an allowed root (the repo, or machine.images.batch_ref_roots); tests use tmp."""
    setup.world.machine.setdefault("images", {})["batch_ref_roots"] = [str(setup.world.tmp)]
    setup.world.write_machine()


def batch(setup: Setup, path: Path, shot: str = "S01_A", **kw):
    kw.setdefault("account", None)
    allow_refs(setup)
    return codex.submit_batch(setup.world.ctx(), setup.out, shot, path, setup.accounts, codex_cmd=python_cmd(FAKE),
                              state_path=setup.state, base_env=setup.env, clock=lambda: setup.clock[0], timeout=30, **kw)


def codex_dir(setup: Setup, shot: str = "S01_A") -> Path:
    return setup.out / shot / "codex-exec"


def test_a_batch_of_10_makes_10_takes_each_with_its_own_prompt(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    result = batch(setup, write_batch(tmp_path, "b1", 10))
    assert result["n"] == 10 and len(result["takes"]) == 10 and result["batch_id"] == "b1"
    for i, row in enumerate(result["takes"], 1):
        folder = codex_dir(setup) / row["take"]
        assert f"PROMPT-b1-{i} un dieu" in (folder / "prompt.txt").read_text("utf-8")
        assert row["prompt_id"] == f"b1_ID_{i}"
    sent = [c["stdin"] for c in setup.calls("acct1") + setup.calls("acct2")]
    assert len(sent) == 10 and len({s for s in sent}) == 10


def test_b_eleven_items_refused_before_any_folder(tmp_path):
    setup = Setup(tmp_path)
    with pytest.raises(Refused, match="at most"):
        batch(setup, write_batch(tmp_path, "b11", 11), dry_run=True)
    assert not codex_dir(setup).exists()


def test_c_duplicate_prompt_id_empty_prompt_missing_ref_refused(tmp_path):
    setup = Setup(tmp_path)
    with pytest.raises(Refused, match="duplicate prompt_id"):
        batch(setup, write_batch(tmp_path, "d", 3, dup=True), dry_run=True)
    with pytest.raises(Refused, match="prompt_text is empty"):
        batch(setup, write_batch(tmp_path, "e", 3, empty=2), dry_run=True)
    with pytest.raises(Refused, match="reference missing"):
        batch(setup, write_batch(tmp_path, "f", 2, missing_ref=True), dry_run=True)
    assert not codex_dir(setup).exists()


def test_d_two_lanes_two_batches_same_shot_make_20_distinct_takes(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    paths = [write_batch(tmp_path, "laneA", 10), write_batch(tmp_path, "laneB", 10)]
    results: dict = {}

    def lane(label: str, path: Path) -> None:
        try:
            results[label] = batch(setup, path, account=label)
        except BaseException as error:  # reported to the main thread
            results[label] = error

    threads = [threading.Thread(target=lane, args=(lbl, p)) for lbl, p in zip(("acct1", "acct2"), paths)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(isinstance(r, dict) for r in results.values()), results
    names = [row["take"] for r in results.values() for row in r["takes"]]
    assert len(names) == 20 and len(set(names)) == 20
    assert len([p for p in codex_dir(setup).iterdir() if p.is_dir()]) == 20
    assert {row["account_label"] for row in results["acct1"]["takes"]} == {"acct1"}


def test_e_receipt_has_batch_id_prompt_id_item_refs_and_no_token(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    path = write_batch(tmp_path, "rc", 2)
    result = batch(setup, path)
    for i, row in enumerate(result["takes"], 1):
        receipt = json.loads(Path(row["receipt"]).read_text("utf-8"))
        assert receipt["schema"] == "jjv/image-receipt/v1"
        assert receipt["batch_id"] == "rc" and receipt["prompt_id"] == f"rc_ID_{i}"
        assert receipt["prompt_sha256"] == receipt["prompt"]["sha256"]
        assert [r["role"] for r in receipt["ref_hashes"]] == ["identity"]
        assert receipt["ref_hashes"][0]["sha256"] == sha256_file(tmp_path / "ref-a.png")
        assert SECRET not in json.dumps(receipt)
    assert SECRET not in json.dumps(result)
    argv = setup.calls("acct1")[0]["argv"]
    assert str(tmp_path / "ref-a.png") in argv  # the item's ref reached codex -i


def test_midbatch_failure_reports_completed_takes(tmp_path, no_auth_reads):
    setup = Setup(tmp_path, accounts=1)
    path = write_batch(tmp_path, "mid", 3)
    original = codex.submit
    count = {"n": 0}

    def flaky(*a, **k):
        count["n"] += 1
        if count["n"] == 3:
            from engine.core.errors import Uncertain
            raise Uncertain("boom")
        return original(*a, **k)

    codex.submit, saved = flaky, codex.submit
    try:
        with pytest.raises(Exception) as caught:
            batch(setup, path)
    finally:
        codex.submit = saved
    assert len(caught.value.evidence["completed_takes"]) == 2


def test_f_real_n27_batch_is_refused_in_shot_mode_because_its_brief_numbers_its_own_images(tmp_path):
    """N23-fix: the N27 briefs say Image1..ImageN from the first ref; shot mode would send the guide as Image 1 (off by one),
    so the engine refuses and points to --library-out. The library-mode run of the same file is in test_images_n23fix."""
    files = sorted(N27_DIR.glob("batch-*-FACE.json")) if N27_DIR.is_dir() else []
    if not files:
        pytest.skip("N27 batch files not present")
    setup = Setup(tmp_path)
    with pytest.raises(Refused, match="--library-out"):
        batch(setup, files[0], dry_run=True)
    assert not codex_dir(setup).exists()
