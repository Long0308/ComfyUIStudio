"""`images library review`: HTML trắng Blue Web, rev theo loại, cờ khung sai."""
from __future__ import annotations

import re
from pathlib import Path

from engine.images.library_review import review
from images_library_fixtures import add_take, build, build_partial


def test_library_review_flags_canvas_and_precedence(tmp_path: Path) -> None:
    fx = build(tmp_path)
    out = tmp_path / "docs" / "review.html"
    r = review([fx["r1"], fx["r2"]], out)
    assert r["per_character"]["CHAR_01"] == {"FACE": 1, "ACTION": 3, "FACE_takes": 1, "ACTION_takes": 3}
    # rev cũ (ACTION 16:9 của r001) không hiện; chỉ ảnh 16:9 chưa receipt của r002 bị cờ.
    assert r["canvas_flags"] == {"CHAR_01": [fx["sha"]["pend"]]}
    assert r["missing_receipts"] == {"CHAR_01": [fx["sha"]["pend"]]}
    page = out.read_text(encoding="utf-8")
    assert fx["sha"]["act_old"] not in page and "KHÔNG 3:4" in page
    assert "prefers-color-scheme" not in page and "data-theme" not in page
    assert "background:#FFFFFF" in page
    assert not re.search(r"orange|#FF[6-9A-F][0-9A-F]00", page, re.I)
    assert review([fx["r1"], fx["r2"]], out)["output_sha256"] == r["output_sha256"]  # idempotent


def test_library_review_canvas_override(tmp_path: Path) -> None:
    fx = build(tmp_path)
    r = review([fx["r1"], fx["r2"]], tmp_path / "x.html", canvas={"FACE": "16:9"})
    assert r["canvas_flags"] == {"CHAR_01": [fx["sha"]["face"]]}


def test_library_review_refuses_bad_char_id(tmp_path: Path) -> None:
    import pytest
    from engine.core.errors import Refused
    from engine.images.library_review import review
    out = tmp_path / "o" / "r.html"
    with pytest.raises(Refused, match="escaped"):
        review([tmp_path], out, refs_dir=tmp_path / "refs", chars=["../../escaped"])
    assert not out.exists()


def test_library_review_partial_revision_has_four_labelled_cards(tmp_path: Path) -> None:
    fx = build_partial(tmp_path)
    out = tmp_path / "review.html"
    result = review([fx["r1"], fx["r2"]], out)
    assert result["per_character"] == {
        "CHAR_01": {"FACE": 2, "ACTION": 2, "FACE_takes": 2, "ACTION_takes": 2}}
    page = out.read_text(encoding="utf-8")
    assert page.count("<div class='card'>") == 4
    assert page.count("rev r001<br>") == 3 and page.count("rev r002<br>") == 1
    assert fx["pids"][0] + "</b>" not in page
    assert fx["replacement"] + "</b>" in page
    assert review([fx["r1"], fx["r2"]], out)["output_sha256"] == result["output_sha256"]


def test_library_review_refuses_ambiguous_current_key(tmp_path: Path) -> None:
    import pytest
    from engine.core.errors import Refused
    fx = build_partial(tmp_path)
    add_take(fx["r2"], "batch-01-CHAR_01-FACE", "t002",
             "CHAR_01_FACE_01_OTHER_r002", (30, 40))
    out = tmp_path / "review.html"
    with pytest.raises(Refused, match="multiple current images for key"):
        review([fx["r1"], fx["r2"]], out)
    assert not out.exists()
