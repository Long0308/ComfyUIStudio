"""``engine.video.anchor_stage`` (``jjv video anchor-stage``): nạp ảnh GỐC của pack (không phải thumbnail) vào GỐC ComfyUI input
dưới tên ``<prefix>_<episode>_<shot>_<slot>_<sha12>.<ext>`` (LoadImage không đọc subfolder — UI lane đo 31/10), write-once, rồi ghi
``staged[]`` + ``staged_at`` vào pack; pack lệch nguồn, shotlist đổi context, lệch sha hay tên stage pilot ⇒ Refused TRƯỚC mọi ghi.
Không GPU, không mạng."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _folder in (_HERE, _HERE.parent):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from pack_fixtures import BOARD_BYTES, EP, ROWS, SHOT, dump, presets, saved_pack, sha, staged_name  # noqa: E402

from engine.comfy.settings import settings_from_machine  # noqa: E402
from engine.core.errors import Refused  # noqa: E402
from engine.core.io import read_json  # noqa: E402
from engine.video import anchor_stage  # noqa: E402

PREFIX = "demo_anc"


def stage(world, pack_path: Path, **kw):
    return anchor_stage.stage(world.ctx(), pack_path, settings_from_machine(world.ctx().machine), input_prefix=PREFIX, **kw)


def staged_files(world) -> list[str]:
    return sorted(p.name for p in world.input.glob(f"{PREFIX}_*"))


def test_stage_copies_originals_write_once_and_records_staged_in_pack(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    before = read_json(pack_path)
    result = stage(world, pack_path, shotlist=world.tmp / "shotlist-draft.json")
    rows = result["staged"]
    assert [r["slot"] for r in rows] == [f"ref_images.ref_image_{i}" for i in range(4)]
    assert [r["role"] for r in rows] == ["face", "body", "wardrobe", "wardrobe"]
    for row in rows:
        assert row["input_subfolder"] == "" and row["filename"] == staged_name(PREFIX, row["slot"], row["sha256"])
        target = world.input / row["filename"]
        assert target.is_file() and sha(target) == row["sha256"] and row["state"] == "linked"
    face = lib.entry("alice", "FACE", 1)
    staged_face = world.input / rows[0]["filename"]
    assert rows[0]["sha256"] == face["sha256"]
    assert staged_face.read_bytes() == (lib.dir / face["file"]).read_bytes()  # ảnh gốc, không phải jpg thumbnail
    pack = read_json(pack_path)
    recorded = [{k: r[k] for k in anchor_stage.STAGED_KEYS} for r in rows]  # ``state`` là của lượt chạy, không ghi vào pack
    assert pack["staged"] == recorded and isinstance(pack["staged_at"], str) and pack["staged_at"]
    assert set(pack) - set(before) == {"staged", "staged_at"} and {k: pack[k] for k in before} == before
    assert result["unchanged"] is False and result["stale_unchecked"] == [] and result["overflow"] == []
    again = stage(world, pack_path, shotlist=world.tmp / "shotlist-draft.json")  # idempotent, không đổi staged_at
    assert again["unchanged"] is True and read_json(pack_path)["staged_at"] == pack["staged_at"]
    assert all(r["state"] == "present" for r in again["staged"])
    staged_face.write_bytes(b"other")  # file trong input đã bị đổi ⇒ không ghi đè, từ chối
    with pytest.raises(Refused, match="hash mismatch"):
        stage(world, pack_path)
    assert staged_face.read_bytes() == b"other"


def test_dry_run_lists_the_slots_and_writes_nothing(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    before = sha(pack_path)
    result = stage(world, pack_path, dry_run=True)
    assert result["dry_run"] is True and [r["state"] for r in result["staged"]] == ["missing"] * 4
    assert [r["filename"] for r in result["staged"]] == [staged_name(PREFIX, r["slot"], r["sha256"]) for r in result["staged"]]
    assert staged_files(world) == [] and sha(pack_path) == before


def test_storyboard_is_staged_for_the_guide_slot(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path, storyboard=True)
    rows = stage(world, pack_path)["staged"]
    guide = rows[-1]
    assert guide["slot"] == "guide.image" and guide["role"] == "storyboard"
    assert guide["filename"] == staged_name(PREFIX, "guide.image", guide["sha256"])
    assert (world.input / guide["filename"]).read_bytes() == BOARD_BYTES
    assert len(rows) == 5


def test_stale_sources_or_a_changed_shotlist_context_refuse_before_any_write(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    presets(world, approved=True)  # file preset ghi lại sau khi pack dựng ⇒ nguồn lệch
    with pytest.raises(Refused, match="ANCHOR_PACK_STALE"):
        stage(world, pack_path)
    assert staged_files(world) == []
    site = [{**r, "context": "cong_truong"} if r["id"] == SHOT else r for r in ROWS]
    world, lib, pack_path = saved_pack(tmp_path / "b", rows=site)
    office = [{**r, "context": "van_phong"} if r["id"] == SHOT else r for r in ROWS]
    v2 = dump(world.tmp / "shotlist-v2.json", {"schema": "jjv/shotlist-draft/v1", "episode": EP, "fps": 24, "rows": office})
    with pytest.raises(Refused, match="ANCHOR_PACK_STALE") as error:  # context đổi theo shotlist ⇒ pack trang phục cũ
        stage(world, pack_path, shotlist=v2)
    assert "cong_truong" in str(error.value) and "van_phong" in str(error.value) and "context" in str(error.value)
    assert staged_files(world) == []
    result = stage(world, pack_path)  # không đưa shotlist ⇒ ghi rõ chưa so, không đoán
    assert result["stale_unchecked"] == ["shotlist"]
    assert stage(world, pack_path, shotlist=world.tmp / "shotlist-draft.json")["stale_unchecked"] == []


def test_ref_sha_drift_refuses_before_any_write(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    (lib.dir / lib.entry("alice", "FACE", 1)["file"]).write_bytes(b"tampered")
    with pytest.raises(Refused, match="ANCHOR_PACK_INVALID|SHA_MISMATCH"):
        stage(world, pack_path)
    assert staged_files(world) == [] and "staged" not in read_json(pack_path)


def test_default_prefix_derives_from_the_domain_id(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    result = anchor_stage.stage(world.ctx(), pack_path, settings_from_machine(world.ctx().machine), input_prefix=None, dry_run=True)
    first = world.domain.split("_")[0]
    assert result["staged"][0]["filename"].startswith(f"{first}_anc_{EP}_{SHOT}_ref_image_0_")


def test_cli_round_trip_and_the_jjv_video_verb(tmp_path, capsys) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    packs = pack_path.parent.parent
    code = anchor_stage.main(["--episode", str(world.root), "--machine", str(world.machine), "--out", str(packs), "--shot", SHOT,
                              "--input-prefix", PREFIX, "--shotlist", str(world.tmp / "shotlist-draft.json")])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["ok"] and len(printed["staged"]) == 4
    assert printed["staged"][0]["filename"] == staged_name(PREFIX, "ref_images.ref_image_0", printed["staged"][0]["sha256"])
    from engine.video import cli

    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    args = parser.parse_args(["video", "anchor-stage", "--episode", str(world.root), "--machine", str(world.machine), "--out", str(packs),
                              "--shot", SHOT, "--input-prefix", PREFIX, "--dry-run"])
    code = cli.run_video(args)
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["dry_run"] is True and all(r["state"] == "present" for r in printed["staged"])
