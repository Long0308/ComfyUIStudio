"""M4-f1: publication appends to an episode manifest; it never re-sorts, re-serialises or drops existing rows.

A foreign manifest (schema this publisher did not write, e.g. milk-and-mom-workflow-manifest/v2) is refused
unless ``--allow-foreign-manifest`` is given. Nothing here touches a production folder.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.images import workflow_publish
from images_fixtures import make_png, sha
from test_images_workflow_publish import ITEMS, Flow, read

FOREIGN_SCHEMA = "milk-and-mom-workflow-manifest/v2"
ADOPT_PATH = "03_STORYBOARD_IMAGES/S01_A-codex-builtin-review-v001.workflow.json"

# Deliberately NOT sorted by stage or path: a re-sort would move them.
OLD_ENTRIES = [
    {"stage": "09_review_cut_v010", "path": "workflows/review-cut-v010/z.json", "root": "film",
     "sha256": "1" * 64, "bytes": 10, "kind": "review", "status": "candidate",
     "x_unknown": {"nested": [1, 2]}, "note": None},
    {"stage": "01_character_casting", "path": "workflows/a.api.json", "root": "film",
     "sha256": "2" * 64, "bytes": 20, "kind": "api", "status": "accepted",
     "status_basis": "unicode caf\u00e9", "in_film_path": False},
    {"stage": "02_storyboard", "path": "workflows/b.api.json", "root": "film",
     "sha256": "3" * 64, "bytes": 30, "kind": "api", "status": "superseded", "future_field": 7},
]


def fake_v2_manifest() -> dict:
    return {
        "schema": FOREIGN_SCHEMA,
        "film_id": "04-milk-and-mom",
        "generated_by": "test fixture (shape of WORKFLOW-MANIFEST-ep04.json)",
        "roots": {"film": "D:\\fake\\04-milk-and-mom"},
        "counts_by_kind": {"api": 2, "review": 1},
        "counts_by_stage": {"01_character_casting": 1, "02_storyboard": 1, "09_review_cut_v010": 1},
        "entry_count": 3,
        "absent": [{"stage": "08_seam_blend", "why": "fixture"}],
        "entries": OLD_ENTRIES,
        "film_entry_count": 3,
        "zz_note": "unknown top-level field must survive",
    }


def render(data: dict, newline: str = "\n") -> bytes:
    return (json.dumps(data, ensure_ascii=True, indent=2) + "\n").replace("\n", newline).encode("ascii")


def write_foreign(flow: Flow, newline: str = "\n") -> Path:
    path = flow.world.root / "workflows" / "WORKFLOW-MANIFEST.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render(fake_v2_manifest(), newline))
    return path


def adopt_args(flow: Flow, name: str, *extra: str, color=(12, 90, 40)) -> tuple[list[str], Path]:
    png = flow.tmp / name
    make_png(png, color, (1672, 941))
    args = ["adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin",
            "--prompt-file", str(flow.prompt), "--refs-from-plan",
            "--source-path", "C:/generated_images/01a17e00-3746-7862-a27d-b01bfd71673b/exec-1.png", *extra]
    return args, png


def entries_prefix(raw: bytes) -> bytes:
    """The ``entries`` array bytes up to and including the last existing row's closing brace.

    Top-level counts may legitimately change (they sit above ``entries`` in the fixture), so the
    byte-identity check is made on the entries block itself, not on the whole file.
    """
    start = raw.index(b'\n  "entries": [')
    close = raw.index(b"\n  ]", start)
    return raw[start:raw.rindex(b"}", start, close) + 1]


def test_refused_without_flag_and_manifest_bytes_untouched(tmp_path):
    flow = Flow(tmp_path)
    manifest = write_foreign(flow)
    before = manifest.read_bytes()
    args, _ = adopt_args(flow, "refused.png")

    code, summary = flow.run(*args)

    assert code == 1
    assert "did not write" in summary["error"] and "--allow-foreign-manifest" in summary["error"]
    assert manifest.read_bytes() == before
    assert not (flow.world.root / "03_STORYBOARD_IMAGES").exists()
    assert not list((flow.world.comfy_root / "input").glob("jjv-result-*"))


def test_accepted_with_flag_appends_and_keeps_existing_bytes_order_and_unknown_fields(tmp_path):
    flow = Flow(tmp_path)
    manifest = write_foreign(flow)
    before = manifest.read_bytes()
    args, _ = adopt_args(flow, "accepted.png", "--allow-foreign-manifest", color=(200, 30, 30))

    code, summary = flow.run(*args)

    assert code == 0
    after = manifest.read_bytes()
    assert entries_prefix(after).startswith(entries_prefix(before)), "existing entries must stay byte-identical"

    data = read(str(manifest))
    assert data["entries"][:3] == OLD_ENTRIES
    assert [row["stage"] for row in data["entries"][:3]] == [
        "09_review_cut_v010", "01_character_casting", "02_storyboard"]
    appended = data["entries"][-1]
    assert len(data["entries"]) == 4 and appended["path"] == ADOPT_PATH
    assert appended["result_sha256"] == summary["sha256"]
    assert appended["kind"] == "review" and appended["status"] == "candidate"

    for key in ("zz_note", "absent", "film_entry_count", "film_id", "generated_by", "roots", "schema"):
        assert data[key] == fake_v2_manifest()[key], key
    assert data["entry_count"] == 4
    assert data["counts_by_kind"] == {"api": 2, "review": 2}
    assert data["counts_by_stage"]["09_review_cut_v010"] == 1
    assert data["counts_by_stage"]["03_storyboard_images"] == 1


def test_crlf_manifest_keeps_crlf_throughout(tmp_path):
    flow = Flow(tmp_path)
    manifest = write_foreign(flow, newline="\r\n")
    before = manifest.read_bytes()
    args, _ = adopt_args(flow, "crlf.png", "--allow-foreign-manifest", color=(70, 20, 150))

    assert flow.run(*args)[0] == 0

    after = manifest.read_bytes()
    assert entries_prefix(after).startswith(entries_prefix(before))
    assert after.count(b"\n") == after.count(b"\r\n"), "no bare LF may be mixed into a CRLF manifest"
    assert len(read(str(manifest))["entries"]) == 4


def test_own_schema_append_keeps_first_row_bytes(tmp_path):
    flow = Flow(tmp_path)
    first_args, _ = adopt_args(flow, "first.png")
    assert flow.run(*first_args)[0] == 0
    manifest = flow.world.root / "workflows" / "WORKFLOW-MANIFEST.json"
    before = manifest.read_bytes()

    second_args, _ = adopt_args(flow, "second.png", color=(30, 30, 200))
    assert flow.run(*second_args)[0] == 0

    after = manifest.read_bytes()
    assert entries_prefix(after).startswith(entries_prefix(before))
    data = read(str(manifest))
    assert data["schema"] == "jjv/workflow-manifest/v1"
    assert len(data["entries"]) == 2 and data["entry_count"] == 2


def snapshot(*roots: Path) -> dict[str, bytes | None]:
    """Every file under ``roots`` as ``{posix path: bytes}`` and every folder as ``{posix path: None}``.

    A refused publish must leave this identical: no file written and no empty folder left behind.
    """
    tree: dict[str, bytes | None] = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            tree[p.as_posix()] = p.read_bytes() if p.is_file() else None
    return tree


def approve_candidate(flow: Flow, candidate_sha: str) -> None:
    """compare + checklist pass for every item + approve: the steps before ``native`` (no native call)."""
    assert flow.run("compare", "--shot", "S01_A")[0] == 0
    checklist_path = flow.out / "S01_A" / "compare" / "checklist.json"
    checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
    for item in ITEMS:
        checklist["candidates"][candidate_sha][item] = {"status": "pass", "note": "reviewed"}
    checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
    assert flow.run("approve", "--shot", "S01_A", "--sha", candidate_sha[:12],
                    "--reviewer", "root", "--scope", "still")[0] == 0


def test_refused_native_publish_leaves_out_episode_and_comfy_identical(tmp_path):
    # Foreign manifest: the candidate publish needs --allow-foreign-manifest, the native publish does not have it,
    # so the native publish is refused AFTER the 864x480 copy was made under a temp name.
    flow = Flow(tmp_path)
    write_foreign(flow)
    args, _ = adopt_args(flow, "native-src.png", "--allow-foreign-manifest", color=(45, 70, 95))
    adopted_code, adopted = flow.run(*args)
    assert adopted_code == 0
    approve_candidate(flow, adopted["sha256"])
    files_before = snapshot(flow.out, flow.world.root, flow.world.comfy_root)
    assert not (flow.out / "S01_A" / "native").exists()

    code, summary = flow.run("native", "--shot", "S01_A", "--sha", adopted["sha256"][:12])

    assert code == 1 and "did not write" in summary["error"]
    assert snapshot(flow.out, flow.world.root, flow.world.comfy_root) == files_before
    assert not list((flow.out / "S01_A").rglob("*native*"))


def test_refused_candidate_publish_leaves_out_identical_too(tmp_path):
    flow = Flow(tmp_path)
    write_foreign(flow)
    files_before = snapshot(flow.out, flow.world.root, flow.world.comfy_root)
    args, _ = adopt_args(flow, "out-check.png")

    code, summary = flow.run(*args)

    assert code == 1 and "did not write" in summary["error"]
    assert snapshot(flow.out, flow.world.root, flow.world.comfy_root) == files_before
    assert not (flow.out / "S01_A").exists()


def test_same_path_with_different_content_is_refused_not_replaced(tmp_path):
    flow = Flow(tmp_path)
    manifest = write_foreign(flow)
    data = fake_v2_manifest()
    data["entries"] = data["entries"] + [{**OLD_ENTRIES[0], "path": ADOPT_PATH, "sha256": "4" * 64}]
    manifest.write_bytes(render(data))
    before = manifest.read_bytes()
    files_before = snapshot(flow.out, flow.world.root, flow.world.comfy_root)
    args, _ = adopt_args(flow, "collide.png", "--allow-foreign-manifest", color=(60, 60, 60))

    code, summary = flow.run(*args)

    assert code == 1
    assert "different content" in summary["error"]
    assert manifest.read_bytes() == before
    assert snapshot(flow.out, flow.world.root, flow.world.comfy_root) == files_before, "refused publish must write no file"
    assert not (flow.world.root / "03_STORYBOARD_IMAGES").exists()


def test_refused_foreign_schema_writes_no_file_under_episode_or_comfy(tmp_path):
    flow = Flow(tmp_path)
    write_foreign(flow)
    files_before = snapshot(flow.out, flow.world.root, flow.world.comfy_root)
    args, _ = adopt_args(flow, "foreign-no-write.png")

    code, summary = flow.run(*args)

    assert code == 1 and "did not write" in summary["error"]
    assert snapshot(flow.out, flow.world.root, flow.world.comfy_root) == files_before


def test_staged_input_name_with_different_bytes_is_refused_before_any_write(tmp_path):
    flow = Flow(tmp_path)
    args, png = adopt_args(flow, "input-collide.png", color=(15, 15, 240))
    squatter = flow.world.comfy_root / "input" / f"jjv-result-{sha(png)[:12]}.png"
    squatter.write_bytes(b"not the staged PNG")
    files_before = snapshot(flow.out, flow.world.root, flow.world.comfy_root)

    code, summary = flow.run(*args)

    assert code == 1 and "ComfyUI input" in summary["error"]
    assert snapshot(flow.out, flow.world.root, flow.world.comfy_root) == files_before
    assert not (flow.world.root / "03_STORYBOARD_IMAGES").exists()


def test_empty_entries_array_gets_the_first_row(tmp_path):
    raw = json.dumps({"schema": FOREIGN_SCHEMA, "entries": [], "keep": {"a": 1}}, indent=2) + "\n"
    entry = {"path": "x.json", "sha256": "5" * 64, "kind": "review", "stage": "03_storyboard_images"}

    text, kept = workflow_publish._append_only_manifest_text(raw, entry, Path("."))
    data = json.loads(text)

    assert kept == [] and data["entries"] == [entry] and data["keep"] == {"a": 1}
    assert data["entry_count"] == 1


def test_old_rows_appear_in_original_order_as_their_own_bytes(tmp_path):
    flow = Flow(tmp_path)
    manifest = write_foreign(flow)
    blocks = [json.dumps(row, ensure_ascii=True, indent=2).replace("\n", "\n    ") for row in OLD_ENTRIES]
    args, _ = adopt_args(flow, "stable.png", "--allow-foreign-manifest", color=(90, 90, 20))
    assert flow.run(*args)[0] == 0

    text = manifest.read_text(encoding="utf-8")
    positions = [text.index("    " + block) for block in blocks]
    assert positions == sorted(positions)
    for position, block in zip(positions, blocks):
        assert text[position + 4: position + 4 + len(block)] == block
