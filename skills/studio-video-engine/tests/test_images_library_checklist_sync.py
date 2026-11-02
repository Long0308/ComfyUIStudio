"""N76-fix: every review of the same library candidate can invalidate its approval."""

import json
from pathlib import Path

import pytest

from engine.core.io import sha256_file
from engine.images import library
from images_fixtures import LIVE, World, make_png, run_images

PID = "CHAR_08_FACE_1_r005"
CHARACTER = "CHAR_08"


def save(path, document):
    Path(path).write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture(params=["--character", "--prompt-id"])
def approved(tmp_path, request):
    world = World(tmp_path, domain=LIVE)
    root = tmp_path / "library"
    image = make_png(root / "batch" / "t001" / "image.png")
    sha = sha256_file(image)
    save(image.with_suffix(".receipt.json"), {
        "schema": library.LIBRARY_RECEIPT_SCHEMA, "prompt_id": PID,
        "batch_id": "batch", "account_label": "test", "created_at": 0,
        "output": {"path": str(image), "sha256": sha}, "ref_hashes": [],
    })

    def cli(verb, selector, *extra):
        return run_images([
            verb, "--episode", str(world.root), "--out", str(tmp_path / "images"),
            "--machine", str(world.machine_path), "--library-out", str(root),
            selector, CHARACTER if selector == "--character" else PID, *extra,
        ])

    paths = {}
    for selector in ("--character", "--prompt-id"):
        code, result = cli("compare", selector)
        assert code == 0, result
        path = Path(result["checklist"])
        document = json.loads(path.read_text("utf-8"))
        for item in result["checklist_items"]:
            document["candidates"][sha][item]["status"] = "pass"
        save(path, document)
        paths[selector] = path
    selected = request.param
    code, result = cli("approve", selected, "--sha", sha, "--reviewer", "test-user", "--scope", "CHAR_08 face")
    assert code == 0, result
    recorded = paths[selected]
    other = paths["--prompt-id" if selected == "--character" else "--character"]
    return root, sha, recorded, other


def test_library_all_pass_in_both_checklists_keeps_approval(approved):
    root, sha, recorded, _ = approved
    current = library.current_approval(root, PID)
    assert current["candidate_sha256"] == sha
    assert Path(current["checklist_path"]) == recorded


def test_library_fail_in_other_checklist_invalidates_approval(approved):
    root, sha, _, other = approved
    assert library.current_approval(root, PID) is not None
    document = json.loads(other.read_text("utf-8"))
    document["candidates"][sha]["identity"]["status"] = "fail"
    save(other, document)
    assert library.current_approval(root, PID) is None


@pytest.mark.parametrize("change", ["unreviewed", "missing-item", "extra-fail", "declared-missing"])
def test_library_other_checklist_requires_every_item_to_pass(approved, change):
    root, sha, _, other = approved
    document = json.loads(other.read_text("utf-8"))
    checks = document["candidates"][sha]
    if change == "missing-item":
        checks.pop("identity")
    elif change == "extra-fail":
        checks["additional-review"] = {"status": "fail"}
    elif change == "declared-missing":
        document["items"].append("additional-review")
    else:
        checks["identity"]["status"] = change
    save(other, document)
    assert library.current_approval(root, PID) is None


def test_library_unrelated_candidate_does_not_invalidate_approval(approved):
    root, _, _, other = approved
    document = json.loads(other.read_text("utf-8"))
    document["candidates"] = {"f" * 64: {"identity": {"status": "fail"}}}
    save(other, document)
    assert library.current_approval(root, PID) is not None


def test_library_missing_recorded_checklist_invalidates_approval(approved):
    root, _, recorded, _ = approved
    # Simulate a missing recorded file without deleting any test artefacts.
    recorded.rename(recorded.with_suffix(".missing"))
    assert library.current_approval(root, PID) is None


def test_library_other_review_folder_also_invalidates_approval(approved):
    root, sha, _, other = approved
    document = json.loads(other.read_text("utf-8"))
    document["candidates"][sha]["identity"]["status"] = "fail"
    extra = root / "_review" / "another-key" / "checklist.json"
    extra.parent.mkdir()
    save(extra, document)
    assert library.current_approval(root, PID) is None
