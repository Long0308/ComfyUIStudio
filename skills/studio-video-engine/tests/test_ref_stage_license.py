"""``jjv ref stage`` — quyền (CR-REFSTAGE): một item chỉ stageable khi nhóm có status dùng-nội-bộ VÀ id nằm trong KEPT
SET của nhóm VÀ sha256 khớp khi index có sha.  Cột ``license_status`` của INDEX.csv chỉ thu hồi, không cấp;
``not_granted`` là deny thực thi; kept set phải nằm trong thư viện và khớp sha đã pin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ref_stage_fixtures import (CC0, KEPT, POSE_HEADER, build_library, common, kept_json, pose_kept, pose_row, refusals,
                                run_stage, sha, staged_files, status_file, write_file)
from ref_stage_fixtures import index as make_index

from engine.ref.license import is_internal_use


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    return build_library(tmp_path)


@pytest.fixture()
def comfy_input(tmp_path: Path) -> Path:
    path = tmp_path / "comfy-input"
    path.mkdir()
    return path


# ---- KEPT SET: id + sha256 ---------------------------------------------------------------
def test_a_csv_row_outside_the_kept_set_is_refused_even_with_a_group_grant(library, comfy_input, capsys) -> None:
    """Ca thật của critic: full_single_P047_side có dòng CSV, chỉ thumbnail, không thuộc 622 id được giữ."""
    argv = ["--ids", "P047_side", *common(library, comfy_input)]
    code, out = run_stage(argv, capsys)
    assert code == 1 and out["ok"] is False
    assert refusals(out) == {"P047_side": "kept-set-missing-id"}
    assert "kept-pose.json" in out["refused"][0]["detail"]
    code, _ = run_stage([*argv, "--apply"], capsys)
    assert code == 1 and staged_files(comfy_input) == []


def test_a_series_selection_reports_every_unkept_row_and_exits_1(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--type", "pose", "--series", "standing", "--limit", "6", *common(library, comfy_input)], capsys)
    assert code == 1
    assert out["counts"]["selected"] == 6 and out["counts"]["stageable"] == 3 and out["counts"]["refused"] == 3
    assert refusals(out) == {"P047_side": "kept-set-missing-id", "P001_high": "kept-set-missing-id",
                             "P008_front": "kept-set-sha-mismatch"}
    assert {item["id"] for item in out["items"]} == {"P001_front", "P002_front", "P003_front"}


def test_a_kept_id_whose_only_file_is_a_thumbnail_is_refused_by_sha(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--ids", "P008_front", *common(library, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"P008_front": "kept-set-sha-mismatch"}
    assert "thumb" in out["refused"][0]["detail"]


def test_face_ids_are_bound_to_the_cc0_list_without_sha(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--ids", "f0001", *common(library, comfy_input)], capsys)
    assert code == 0, out
    item = out["items"][0]
    assert item["license_status"] == CC0 and item["variant"] == "root"
    assert item["kept_set"] == {"index": "kept-face.json", "index_sha256": sha(library / "kept-face.json"),
                                "sha256_bound": False}
    code, out = run_stage(["--ids", "f0003", *common(library, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"f0003": "kept-set-missing-id"}


def test_a_group_grant_without_a_kept_set_is_refused(tmp_path, comfy_input, capsys) -> None:
    root = tmp_path / "lib-nokept"
    folder = make_index(root, "pose", "standing", POSE_HEADER, [pose_row("P001_front", True)])
    write_file(folder, "full/P001_front.png", b"\x89PNG")
    status_file(root, {"pose/standing": {"status": KEPT, "basis": "no kept set declared"}})
    code, out = run_stage(["--ids", "P001_front", *common(root, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"P001_front": "kept-set-missing"}


def test_a_pinned_kept_index_sha_that_does_not_match_refuses_the_whole_run(library, comfy_input, capsys) -> None:
    status_file(library, {"pose/standing": {"status": KEPT, "kept_set": pose_kept(index_sha256="0" * 64)}})
    code, out = run_stage(["--ids", "P001_front", *common(library, comfy_input)], capsys)
    assert code == 1 and "kept set" in out["error"] and "kept-pose.json" in out["error"]
    assert "items" not in out


def test_a_kept_index_outside_the_library_is_refused(library, tmp_path, comfy_input, capsys) -> None:
    outside = tmp_path / "outside-kept.json"
    outside.write_text(json.dumps({"items": [{"id": "P001_front", "sha256": "0" * 64}]}), encoding="utf-8")
    status_file(library, {"pose/standing": {"status": KEPT, "kept_set": pose_kept(path=str(outside))}})
    code, out = run_stage(["--ids", "P001_front", *common(library, comfy_input)], capsys)
    assert code == 1 and "kept set" in out["error"] and "escaped" in out["error"]


# ---- license ----------------------------------------------------------------------------
def test_missing_license_status_is_refused_and_nothing_is_written(library, comfy_input, capsys) -> None:
    argv = ["--ids", "AUT-0001", *common(library, comfy_input)]
    code, out = run_stage(argv, capsys)
    assert code == 1 and out["ok"] is False
    assert refusals(out) == {"AUT-0001": "license-status-missing"}
    code, _ = run_stage([*argv, "--apply"], capsys)
    assert code == 1
    assert staged_files(comfy_input) == []


def test_non_internal_use_status_is_refused(library, comfy_input, capsys) -> None:
    code, out = run_stage(["--ids", "Q001_front", *common(library, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"Q001_front": "license-status-not-internal-use"}
    assert "QUARANTINED_2026-10-31" in out["refused"][0]["detail"]


@pytest.mark.parametrize("status,internal", [
    (KEPT, True), (CC0, True), ("INTERNAL_REFERENCE_ONLY", True),
    ("DENIED_INTERNAL_REFERENCE_ONLY", False), ("QUARANTINED_2026-10-31_INTERNAL_REFERENCE_ONLY", False),
    ("NOT_INTERNAL_REFERENCE_ONLY", False), ("REVOKED_INTERNAL_REFERENCE_ONLY", False),
    ("kept_internal_reference_only", False), ("INTERNAL_REFERENCE", False), ("PUBLIC", False), ("", False),
])
def test_internal_use_needs_the_suffix_and_no_negative_token(status: str, internal: bool) -> None:
    assert is_internal_use(status) is internal


def test_the_index_column_can_only_revoke_never_grant(tmp_path, comfy_input, capsys) -> None:
    root = tmp_path / "lib2"
    header = f"{POSE_HEADER},license_status"
    granted = make_index(root, "pose", "col", header, [f"{pose_row('C001_front', True, 'col')},{KEPT}"])
    write_file(granted, "full/C001_front.png", b"\x89PNG C001")
    revoked = make_index(root, "pose", "standing", header, [f"{pose_row('R001_front', True)},QUARANTINED"])
    r_file = write_file(revoked, "full/R001_front.png", b"\x89PNG R001")
    kept_json(root, "kept-pose.json", [{"id": "R001_front", "sha256": sha(r_file)}])
    status_file(root, {"pose/standing": {"status": KEPT, "kept_set": pose_kept()}})  # cột cấp cho col: vô hiệu

    code, out = run_stage(["--ids", "C001_front", *common(root, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"C001_front": "license-status-missing"}
    code, out = run_stage(["--ids", "R001_front", *common(root, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"R001_front": "license-status-not-internal-use"}
    assert "index column" in out["refused"][0]["detail"]


def test_not_granted_is_an_enforced_deny_that_beats_a_grant(library, comfy_input, capsys) -> None:
    doc = json.loads((library / "LICENSE-STATUS.json").read_text(encoding="utf-8"))
    doc["not_granted"] = {"pose/standing": "user withdrew this group"}
    (library / "LICENSE-STATUS.json").write_text(json.dumps(doc), encoding="utf-8")
    code, out = run_stage(["--ids", "P001_front", *common(library, comfy_input)], capsys)
    assert code == 1 and refusals(out) == {"P001_front": "license-status-not-granted"}
    assert "withdrew" in out["refused"][0]["detail"]


def test_no_status_file_at_all_refuses_every_candidate(tmp_path, comfy_input, capsys) -> None:
    root = tmp_path / "lib3"
    folder = make_index(root, "face", "closeup", "hair_length_zh,id,source_url,thumb", [
        "short,f0001,https://ai-portrait-gallery.pages.dev/img/full/f0001.png,True",
    ])
    write_file(folder, "f0001.webp", b"RIFF f0001")
    code, out = run_stage(["--ids", "f0001", *common(root, comfy_input)], capsys)
    assert code == 1
    assert out["license_status_file"] is None
    assert refusals(out) == {"f0001": "license-status-missing"}
