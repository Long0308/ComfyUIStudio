"""`images library view`: 2 rev, di chuyển rev cũ, idempotent, copy thật, PROMPTS đủ prompt."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from engine.images.library_view import view
from images_library_fixtures import ACT1, ACT3, FACE1, add_take, build, build_partial

QUIET = lambda _m: None  # noqa: E731


def _tree(out: Path) -> dict[str, str]:
    return {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*")) if p.is_file()}


def test_library_view_two_revs_move_and_idempotent(tmp_path: Path) -> None:
    fx = build(tmp_path)
    out, sha = tmp_path / "by", fx["sha"]
    src_before = _tree(fx["r1"]) | _tree(fx["r2"])
    # Lượt 1: chỉ r001 -> cả ACTION r001 được copy.
    r = view([fx["r1"]], [fx["q1"]], out, echo=QUIET)
    assert r["exit"] == 0, r["errors"]
    assert r["counts"]["CHAR_01"] == {"FACE": 1, "ACTION": 1}
    assert len(list((out / "CHAR_01" / "ACTION").glob("*.png"))) == 1
    # Lượt 2: thêm r002 -> ACTION r001 bị rút, ACTION r002 thay vào; FACE giữ r001.
    r = view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out, echo=QUIET)
    assert r["exit"] == 0, r["errors"]
    assert r["counts"]["CHAR_01"] == {"FACE": 1, "ACTION": 2}
    rej = out / "CHAR_01" / "ACTION_r001_rejected"
    assert [p.name.split("__")[1] for p in rej.glob("*.png")] == [sha["act_old"] + ".png"]
    assert len(list(rej.glob("*.prompt.txt"))) == 1
    names = {p.name for p in (out / "CHAR_01" / "ACTION").glob("*.png")}
    assert all(sha["act_old"] not in n for n in names) and any(sha["act1"] in n for n in names)
    assert len(r["superseded"]) == 1 and r["superseded"][0]["prompt_id"] == ACT1
    # pending: PNG chưa receipt không bị copy, không là lỗi.
    assert len(r["pending"]) == 1 and sha["pend"] not in " ".join(names)
    # Copy thật, không hardlink; byte prompt giữ nguyên.
    dst = next((out / "CHAR_01" / "FACE").glob("*.png"))
    src = next(fx["r1"].glob("batch-01*/t001/*.png"))
    assert not os.path.samefile(dst, src) and os.stat(dst).st_nlink == 1
    assert dst.with_name(dst.stem + ".prompt.txt").read_bytes() == (src.parent / "prompt.txt").read_bytes()
    # PROMPTS.md liệt kê cả prompt chưa render.
    md = (out / "CHAR_01" / "PROMPTS.md").read_text(encoding="utf-8")
    assert f"### {ACT3}" in md and "chưa có ảnh" in md and f"### {FACE1}" in md and f"brief {ACT3}" in md
    # Lượt 3 idempotent: cây thư mục y hệt, không lỗi.
    before = _tree(out)
    r = view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out, echo=QUIET)
    assert r["exit"] == 0 and _tree(out) == before
    assert _tree(fx["r1"]) | _tree(fx["r2"]) == src_before  # nguồn không bị đụng
    idx = json.loads((out / "INDEX.json").read_text(encoding="utf-8"))
    assert idx["revs"] == {"FACE": "r001", "ACTION": "r002"}


def test_library_view_refuses_overwrite_and_unknown(tmp_path: Path) -> None:
    fx = build(tmp_path)
    out = tmp_path / "by"
    assert view([fx["r1"]], [fx["q1"]], out, echo=QUIET)["exit"] == 0
    dst = next((out / "CHAR_01" / "FACE").glob("*.png"))
    dst.write_bytes(b"corrupt")
    r = view([fx["r1"]], [fx["q1"]], out, echo=QUIET)
    assert r["exit"] == 1 and any("không ghi đè" in e for e in r["errors"]) and dst.read_bytes() == b"corrupt"
    out2 = tmp_path / "by2"
    assert view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out2, echo=QUIET)["exit"] == 0
    (out2 / "CHAR_01" / "ACTION" / "99_X__0123456789ab.png").write_bytes(b"x")
    r = view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out2, echo=QUIET)
    assert r["exit"] == 1 and any("0123456789ab" in e for e in r["errors"])


def test_library_view_rejects_missing_inputs(tmp_path: Path) -> None:
    r = view([tmp_path / "nope"], [tmp_path / "q.json"], tmp_path / "o", echo=QUIET)
    assert r["exit"] == 1 and len(r["errors"]) == 2


def _evil_queue(tmp_path: Path, **patch: str) -> tuple[dict, Path]:
    fx = build(tmp_path)
    q = fx["q1"]
    rows = json.loads(q.read_text(encoding="utf-8"))
    rows[0].update(patch)
    q.write_text(json.dumps(rows), encoding="utf-8")
    return fx, q


def _outside_files(tmp_path: Path) -> set[str]:
    return {str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if "escaped" in p.name or "outside" in p.name}


def test_library_view_refuses_escape_via_char(tmp_path: Path) -> None:
    import pytest
    from engine.core.errors import Refused
    fx, q = _evil_queue(tmp_path, char="../../escaped")
    with pytest.raises(Refused, match="escaped"):
        view([fx["r1"]], [q], tmp_path / "x" / "by", echo=QUIET)
    assert not _outside_files(tmp_path) and not (tmp_path / "x").exists()


def test_library_view_refuses_escape_via_batch_id(tmp_path: Path) -> None:
    import pytest
    from engine.core.errors import Refused
    (tmp_path / "outside.json").write_text("[]", encoding="utf-8")
    fx, q = _evil_queue(tmp_path, batch_id="../../outside")
    with pytest.raises(Refused, match="outside"):
        view([fx["r1"]], [q], tmp_path / "by", echo=QUIET)
    assert not (tmp_path / "by").exists()


def test_library_view_refuses_escape_via_prompt_id(tmp_path: Path) -> None:
    import pytest
    from engine.core.errors import Refused
    fx, q = _evil_queue(tmp_path, prompt_id="../../escaped")
    with pytest.raises(Refused, match="escaped"):
        view([fx["r1"]], [q], tmp_path / "by", echo=QUIET)
    assert not (tmp_path / "by").exists()


def test_library_view_contained_helper(tmp_path: Path) -> None:
    import pytest
    from engine.core.errors import Refused
    from engine.images.library_revs import contained
    assert contained(tmp_path / "a" / "b", tmp_path)
    with pytest.raises(Refused):
        contained(tmp_path / ".." / "z", tmp_path, "p")


@pytest.mark.parametrize("incremental", [False, True])
def test_library_view_partial_revision_per_key(tmp_path: Path, incremental: bool) -> None:
    fx = build_partial(tmp_path)
    out = tmp_path / "out"
    sources = {lib: _tree(fx[lib]) for lib in ("r1", "r2")}
    if incremental:
        assert view([fx["r1"]], [fx["q1"]], out, echo=QUIET)["exit"] == 0
    args = ([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out)
    r = view(*args, episode=Path("episode.json"), machine=Path("machine.json"),
             engine_dir=tmp_path, echo=QUIET)
    assert r["exit"] == 0, r["errors"]
    assert r["counts"] == {"CHAR_01": {"FACE": 2, "ACTION": 2}}
    idx = json.loads((out / "INDEX.json").read_text(encoding="utf-8"))
    current = idx["characters"]["CHAR_01"]
    assert {e["prompt_id"]: e["rev"] for e in current["FACE"]} == {
        fx["pids"][1]: "r001", fx["replacement"]: "r002"}
    assert {e["rev"] for e in current["ACTION"]} == {"r001"}
    assert len(list((out / "CHAR_01" / "FACE").glob("*.png"))) == 2
    assert len(list((out / "CHAR_01" / "ACTION").glob("*.png"))) == 2
    rejected = list((out / "CHAR_01" / "FACE_r001_rejected").glob("*.png"))
    assert len(rejected) == len(r["superseded"]) == 1
    assert fx["shas"][0] in rejected[0].name
    assert rejected[0].with_suffix(".prompt.txt").is_file()
    assert not (out / "CHAR_01" / "ACTION_r001_rejected").exists()
    md = (out / "CHAR_01" / "PROMPTS.md").read_text(encoding="utf-8")
    assert md.count("### CHAR_") == 4
    assert f"### {fx['pids'][0]}\n" not in md
    for pid, lib in [(fx["pids"][1], fx["r1"]), (fx["replacement"], fx["r2"])]:
        section = md.split(f"### {pid}\n", 1)[1].split("### ", 1)[0]
        assert f"prompt of {pid}" in section
        assert f"--library-out '{lib}'" in section
    before = _tree(out)
    again = view(*args, episode=Path("episode.json"), machine=Path("machine.json"),
                 engine_dir=tmp_path, echo=QUIET)
    assert again["exit"] == 0 and _tree(out) == before
    assert {lib: _tree(fx[lib]) for lib in ("r1", "r2")} == sources


def test_library_view_same_bytes_changed_label_retires_only_old_path(tmp_path: Path) -> None:
    fx = build_partial(tmp_path, replacement="CHAR_01_FACE_01_RENAMED_r001_r002")
    old = next(fx["r1"].glob("batch-*-FACE/t001/*.png"))
    new = next(fx["r2"].glob("batch-*-FACE/t001/*.png"))
    receipt = new.with_suffix(".receipt.json")
    new.write_bytes(old.read_bytes())
    new.rename(new.with_name(old.name))
    receipt.rename(receipt.with_name(old.stem + ".receipt.json"))
    out = tmp_path / "out"
    assert view([fx["r1"]], [fx["q1"]], out, echo=QUIET)["exit"] == 0
    result = view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out, echo=QUIET)
    assert result["exit"] == 0, result["errors"]
    names = [p.name for p in (out / "CHAR_01" / "FACE").glob("*.png")]
    assert len(names) == 2 and sum("RENAMED" in n for n in names) == 1
    assert not any("NEUTRAL" in n for n in names)
    assert len(result["superseded"]) == 1
    before = _tree(out)
    assert view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out, echo=QUIET)["exit"] == 0
    assert _tree(out) == before


def test_library_view_refuses_ambiguous_current_key_before_copy(tmp_path: Path) -> None:
    from engine.core.errors import Refused
    fx = build_partial(tmp_path)
    add_take(fx["r2"], "batch-01-CHAR_01-FACE", "t002",
             "CHAR_01_FACE_01_OTHER_r002", (30, 40))
    out = tmp_path / "out"
    with pytest.raises(Refused, match="multiple current images for key"):
        view([fx["r1"], fx["r2"]], [fx["q1"], fx["q2"]], out, echo=QUIET)
    assert not out.exists()
