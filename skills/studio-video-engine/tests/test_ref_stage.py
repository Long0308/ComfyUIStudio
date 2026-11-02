"""``jjv ref stage``: dry-run mặc định (không ghi), ``--apply`` copy (không move), idempotent theo sha, xung đột tên
đích từ chối cả lượt, lựa chọn, an toàn đường dẫn, không mạng.  Luật quyền (kept set + license) đo ở
``test_ref_stage_license.py``; thư viện giả ở ``ref_stage_fixtures.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ref_stage_fixtures import (KEPT, POSE_HEADER, build_library, common, jjv, kept_json, pose_kept, pose_row, refusals,
                                run_stage, sha, sha_bytes, staged_files, status_file, write_file)
from ref_stage_fixtures import index as make_index


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    return build_library(tmp_path)


@pytest.fixture()
def comfy_input(tmp_path: Path) -> Path:
    path = tmp_path / "comfy-input"
    path.mkdir()
    return path


# ---- dry-run mặc định: liệt kê, không ghi ----------------------------------------------
def test_dry_run_lists_kept_candidates_and_writes_nothing(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--type", "pose", "--series", "standing", "--limit", "3", *common(library, comfy_input)], capsys)
    assert code == 0, out
    assert out["ok"] is True and out["dry_run"] is True
    assert out["counts"] == {"selected": 3, "stageable": 3, "present": 0, "copied": 0, "refused": 0}
    by_id = {item["id"]: item for item in out["items"]}
    assert set(by_id) == {"P001_front", "P002_front", "P003_front"}
    front = by_id["P001_front"]
    assert front["variant"] == "full"
    assert front["staged_path"] == "reference-library/pose/standing/P001_front.png"
    assert front["source_sha256"] == sha(library / "by-type/pose/standing/full/P001_front.png")
    assert front["license_status"] == KEPT and front["license_source"] == "license-status-file"
    assert front["kept_set"] == {"index": "kept-pose.json", "index_sha256": sha(library / "kept-pose.json"),
                                 "sha256_bound": True}
    assert front["state"] == "missing"
    assert staged_files(comfy_input) == []
    assert out["manifest"] is None


def test_apply_copies_never_moves_and_writes_manifest(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--type", "pose", "--series", "standing", "--limit", "3", "--apply",
                           *common(library, comfy_input)], capsys)
    assert code == 0, out
    assert out["dry_run"] is False
    assert out["counts"]["copied"] == 3 and out["counts"]["present"] == 0
    source = library / "by-type/pose/standing/full/P001_front.png"
    staged = comfy_input / "reference-library/pose/standing/P001_front.png"
    assert source.is_file(), "nguồn phải còn nguyên (copy, không move)"
    assert staged.read_bytes() == source.read_bytes()
    assert (comfy_input / "reference-library/pose/standing/P003_front.png").is_file()

    manifest = Path(out["manifest"])
    assert manifest.is_file() and manifest.parent == comfy_input / "reference-library" / "manifests"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert doc["schema"] == "jjv/ref-stage-manifest/v1"
    assert doc["manifest_id"] == out["manifest_id"] and manifest.name == f"stage-{doc['manifest_id']}.json"
    assert doc["license_status_file"]["sha256"] == sha(library / "LICENSE-STATUS.json")
    rows = {row["id"]: row for row in doc["items"]}
    row = rows["P001_front"]
    assert set(row) >= {"id", "type", "group", "variant", "index_path", "source_path", "source_sha256", "bytes",
                        "license_status", "license_source", "kept_set", "staged_path"}
    assert Path(row["source_path"]) == source.resolve()
    assert row["source_sha256"] == sha(source) and row["bytes"] == source.stat().st_size
    assert row["license_status"] == KEPT and row["kept_set"]["index"] == "kept-pose.json"
    assert row["staged_path"] == "reference-library/pose/standing/P001_front.png"
    assert "utc_time" not in doc  # manifest deterministic theo lựa chọn, thời gian nằm ở ledger

    ledger = (comfy_input / "reference-library" / "STAGED-LEDGER.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 3
    first = json.loads(ledger[0])
    assert set(first) == {"utc_time", "manifest_id", "id", "sha256", "staged_path", "source_path"}


def test_apply_twice_is_a_no_op_by_sha(library, comfy_input, capsys) -> None:
    argv = ["--type", "pose", "--series", "standing", "--limit", "3", "--apply", *common(library, comfy_input)]
    code, first = run_stage(argv, capsys)
    assert code == 0
    before = {p: sha(p) for p in staged_files(comfy_input)}
    code, second = run_stage(argv, capsys)
    assert code == 0, second
    assert second["counts"]["copied"] == 0 and second["counts"]["present"] == 3
    assert second["manifest"] == first["manifest"] and second["manifest_id"] == first["manifest_id"]
    assert {p: sha(p) for p in staged_files(comfy_input)} == before
    manifests = list((comfy_input / "reference-library" / "manifests").glob("*.json"))
    assert len(manifests) == 1
    ledger = (comfy_input / "reference-library" / "STAGED-LEDGER.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 3  # không thêm dòng cho file đã có


# ---- xung đột tên đích: cả lượt bị từ chối, không copy nửa chừng --------------------------
def test_different_file_under_the_staged_name_refuses_the_whole_run(library, comfy_input, capsys) -> None:
    clash = comfy_input / "reference-library/pose/standing/P001_front.png"
    clash.parent.mkdir(parents=True)
    clash.write_bytes(b"\x89PNG something else entirely")
    argv = ["--type", "pose", "--series", "standing", "--limit", "3", *common(library, comfy_input)]
    code, out = run_stage(argv, capsys)
    assert code == 1 and out["ok"] is False
    assert refusals(out) == {"P001_front": "staged-name-conflict"}

    code, out = run_stage([*argv, "--apply"], capsys)
    assert code == 1
    assert not (comfy_input / "reference-library/pose/standing/P002_front.png").exists()
    assert not (comfy_input / "reference-library/manifests").exists()
    assert clash.read_bytes() == b"\x89PNG something else entirely"


# ---- lựa chọn -----------------------------------------------------------------------------
def test_ids_select_across_types_and_an_unknown_id_is_refused(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--ids", "P001_front,f0001", *common(library, comfy_input)], capsys)
    assert code == 0, out
    assert [(i["id"], i["type"], i["staged_path"]) for i in out["items"]] == [
        ("f0001", "face", "reference-library/face/closeup/f0001.webp"),
        ("P001_front", "pose", "reference-library/pose/standing/P001_front.png"),
    ]
    code, out = run_stage(["--ids", "NOPE-1", *common(library, comfy_input)], capsys)
    assert code == 1 and "not found" in out["error"]


def test_source_file_missing_on_disk_is_refused(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--ids", "f0002", *common(library, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"f0002": "source-file-missing"}


def test_ids_and_type_are_mutually_exclusive_and_series_needs_type(library, comfy_input, capsys) -> None:
    with pytest.raises(SystemExit):
        jjv().main(["ref", "stage", "--ids", "P001_front", "--type", "pose", *common(library, comfy_input)])
    capsys.readouterr()
    code, out = run_stage(["--ids", "P001_front", "--series", "standing", *common(library, comfy_input)], capsys)
    assert code == 1 and "--series" in out["error"]


def test_limit_caps_the_series_selection(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--type", "pose", "--series", "standing", "--limit", "1", *common(library, comfy_input)], capsys)
    assert code == 0 and out["counts"]["selected"] == 1 and out["items"][0]["id"] == "P001_front"


# ---- an toàn đường dẫn và mạng --------------------------------------------------------------
def test_an_unsafe_id_from_the_index_cannot_escape_the_input_dir(tmp_path, comfy_input, capsys) -> None:
    root = tmp_path / "lib4"
    folder = make_index(root, "pose", "standing", POSE_HEADER, [
        "True,../escape,P001,standing,https://ai-pose-gallery.pages.dev/img/x.png,True",
    ])
    write_file(folder, "full/escape.png", b"\x89PNG")
    kept_json(root, "kept-pose.json", [{"id": "../escape", "sha256": sha_bytes(b"\x89PNG")}])
    status_file(root, {"pose/standing": {"status": KEPT, "kept_set": pose_kept()}})
    code, out = run_stage(["--ids", "../escape", "--apply", *common(root, comfy_input)], capsys)
    assert code == 1 and "unsafe" in out["error"]
    assert staged_files(comfy_input) == []
    assert not (tmp_path / "escape.png").exists()


def test_a_source_symlink_that_leaves_the_library_is_refused(library, tmp_path, comfy_input, capsys) -> None:
    outside = tmp_path / "outside-secret.png"
    outside.write_bytes(b"\x89PNG outside the library")
    link = library / "by-type/pose/standing/full/L001_front.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create file symlinks")
    csv_path = library / "by-type/pose/standing/INDEX.csv"
    csv_path.write_text(csv_path.read_text(encoding="utf-8") + pose_row("L001_front", True) + "\n", encoding="utf-8")
    kept = json.loads((library / "kept-pose.json").read_text(encoding="utf-8"))
    kept["items"].append({"id": "L001_front", "sha256": sha(outside)})
    (library / "kept-pose.json").write_text(json.dumps(kept), encoding="utf-8")
    code, out = run_stage(["--ids", "L001_front", "--apply", *common(library, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"L001_front": "source-outside-library"}
    assert staged_files(comfy_input) == []


def test_stage_never_uses_the_network(library, comfy_input, monkeypatch, capsys) -> None:
    import urllib.request

    def no_network(*_args, **_kwargs):
        raise AssertionError("ref stage must never open a URL")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    code, out = run_stage(["--ids", "P001_front", "--apply", *common(library, comfy_input)], capsys)
    assert code == 0, out


def test_comfy_input_dir_comes_from_the_machine_config_when_not_given(library, tmp_path, capsys) -> None:
    comfy_root = tmp_path / "comfy"
    (comfy_root / "input").mkdir(parents=True)
    machine = tmp_path / "machine.json"
    machine.write_text(json.dumps({
        "comfy": {"url": "http://127.0.0.1:1", "root": str(comfy_root), "container": "fake"},
        "gpu_lock_path": str(tmp_path / "lock.json"),
    }), encoding="utf-8")
    code, out = run_stage(["--ids", "P001_front", "--library-root", str(library), "--machine", str(machine)], capsys)
    assert code == 0, out
    assert Path(out["comfy_input_dir"]) == (comfy_root / "input").resolve()


def test_missing_comfy_input_dir_is_refused(library, tmp_path, capsys) -> None:
    code, out = run_stage(["--ids", "P001_front", "--library-root", str(library),
                           "--comfy-input", str(tmp_path / "nowhere")], capsys)
    assert code == 1 and "input" in out["error"]
