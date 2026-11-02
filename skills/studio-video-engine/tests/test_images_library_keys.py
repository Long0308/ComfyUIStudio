"""Rev theo KHÓA (nhân vật, loại, số prompt): rev mới chỉ thay đúng khóa nó có."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.images.library_review import review  # noqa: E402
from engine.images.library_view import view  # noqa: E402
from images_library_fixtures import add_take, write_queue  # noqa: E402

FB, AB = "batch-01-CHAR_01-FACE", "batch-02-CHAR_01-ACTION"
F1, F2 = "CHAR_01_FACE_01_NEUTRAL_r001", "CHAR_01_FACE_02_SMILE_r001"
A1, A2 = "CHAR_01_ACTION_01_WAVE_r001", "CHAR_01_ACTION_02_POINT_r001"
F1_NEW = "CHAR_01_FACE_01_NEUTRAL_r001_r002"


def build_partial(root: Path) -> dict:
    r1, r2 = root / "library-r001", root / "library-r002"
    s = {"f1": add_take(r1, FB, "t001", F1, (30, 40)), "f2": add_take(r1, FB, "t002", F2, (30, 40)),
         "a1": add_take(r1, AB, "t001", A1, (30, 40)), "a2": add_take(r1, AB, "t002", A2, (30, 40)),
         "f1n": add_take(r2, FB, "t001", F1_NEW, (30, 40))}
    q1 = write_queue(root / "b1", "r001", [(F1, "CHAR_01", "FACE", FB), (F2, "CHAR_01", "FACE", FB),
                                           (A1, "CHAR_01", "ACTION", AB), (A2, "CHAR_01", "ACTION", AB)])
    q2 = write_queue(root / "b2", "r002", [(F1_NEW, "CHAR_01", "FACE", FB)])
    return {"r1": r1, "r2": r2, "q": [q1, q2], "sha": s}


def test_partial_rev_keeps_untouched_keys_and_is_idempotent(tmp_path: Path) -> None:
    b = build_partial(tmp_path)
    out = tmp_path / "out"
    first = view([b["r1"]], b["q"][:1], out, echo=lambda *_: None)  # r1 đã được gom trước khi có r2
    assert first["exit"] == 0 and first["counts"]["CHAR_01"] == {"FACE": 2, "ACTION": 2}
    r = view([b["r1"], b["r2"]], b["q"], out, echo=lambda *_: None)
    assert r["exit"] == 0, r["errors"]
    assert r["counts"]["CHAR_01"] == {"FACE": 2, "ACTION": 2}
    face = sorted(p.name for p in (out / "CHAR_01" / "FACE").glob("*.png"))
    assert len(face) == 2 and any(b["sha"]["f1n"] in n for n in face) and any(b["sha"]["f2"] in n for n in face)
    assert len(list((out / "CHAR_01" / "ACTION").glob("*.png"))) == 2
    rej = list((out / "CHAR_01" / "FACE_r001_rejected").glob("*.png"))
    assert len(rej) == 1 and b["sha"]["f1"] in rej[0].name
    assert not (out / "CHAR_01" / "ACTION_r001_rejected").exists()
    assert len(r["superseded"]) == 1
    prompts = (out / "CHAR_01" / "PROMPTS.md").read_text(encoding="utf-8")
    assert F1_NEW in prompts and f"### {F1}\n" not in prompts and f"### {F2}\n" in prompts
    snap = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    r2 = view([b["r1"], b["r2"]], b["q"], out, echo=lambda *_: None)
    assert r2["exit"] == 0, r2["errors"]
    assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == snap


def test_partial_rev_review_shows_four_cards_with_rev_labels(tmp_path: Path) -> None:
    b = build_partial(tmp_path)
    page = tmp_path / "rev" / "review.html"
    r = review([b["r1"], b["r2"]], page)
    pc = r["per_character"]["CHAR_01"]
    assert (pc["FACE"], pc["ACTION"], pc["FACE_takes"], pc["ACTION_takes"]) == (2, 2, 2, 2)
    html = page.read_text(encoding="utf-8")
    assert html.count("<div class='card'>") == 4
    assert html.count("· rev r001<") == 3 and html.count("· rev r002<") == 1
    assert F1_NEW in html and F1 + "</b>" not in html


def test_suffixed_batch_is_a_later_revision_than_unsuffixed_in_same_library(tmp_path: Path) -> None:
    """batch-01f-... (cung khoa) THANG batch-01-...: take cu di vao FACE_r001_rejected, review khong hien take cu."""
    lib = tmp_path / "library-r001"
    fsfx = "batch-01f-CHAR_01-FACE"
    old = add_take(lib, FB, "t001", F1, (30, 40))
    keep = add_take(lib, FB, "t002", F2, (30, 40))
    new = add_take(lib, fsfx, "t001", F1, (30, 42))  # kich thuoc khac => PNG (sha) khac take cu
    q = write_queue(tmp_path / "b1", "r001", [(F1, "CHAR_01", "FACE", fsfx), (F2, "CHAR_01", "FACE", FB)])
    out = tmp_path / "out"
    r = view([lib], [q], out, echo=lambda *_: None)
    assert r["exit"] == 0, r["errors"]
    face = sorted(p.name for p in (out / "CHAR_01" / "FACE").glob("*.png"))
    assert len(face) == 2 and any(new in n for n in face) and any(keep in n for n in face)
    assert not any(old in n for n in face)
    rej = list((out / "CHAR_01" / "FACE_r001_rejected").glob("*.png"))
    assert len(rej) == 1 and old in rej[0].name
    page = tmp_path / "rev" / "review.html"
    pc = review([lib], page)["per_character"]["CHAR_01"]
    assert (pc["FACE"], pc["FACE_takes"]) == (2, 2)
    html = page.read_text(encoding="utf-8")
    assert new in html and old not in html


def corrupt_receipt_sha(lib: Path, batch: str, take: str) -> None:
    """Làm receipt.prompt_text_sha256 lệch queue (brief đổi sau khi sinh ảnh)."""
    rp = next((lib / batch / take).glob("*.receipt.json"))
    rec = json.loads(rp.read_text(encoding="utf-8"))
    rec["prompt_text_sha256"] = "0" * 64
    rp.write_text(json.dumps(rec), encoding="utf-8")


def test_same_rev_superseded_take_skips_queue_sha_check(tmp_path: Path) -> None:
    """(a) take bị thay CÙNG thư viện (batch-01 vs 01f), brief khác queue: không lỗi, vào *_rejected."""
    lib, fsfx = tmp_path / "library-r001", "batch-01f-CHAR_01-FACE"
    old = add_take(lib, FB, "t001", F1, (30, 40))
    add_take(lib, fsfx, "t001", F1, (30, 42))
    corrupt_receipt_sha(lib, FB, "t001")
    q = write_queue(tmp_path / "b1", "r001", [(F1, "CHAR_01", "FACE", fsfx)])
    out = tmp_path / "out"
    r = view([lib], [q], out, echo=lambda *_: None)
    assert r["exit"] == 0, r["errors"]
    rej = list((out / "CHAR_01" / "FACE_r001_rejected").glob("*.png"))
    assert len(rej) == 1 and old in rej[0].name


def test_current_take_with_sha_mismatch_still_raises(tmp_path: Path) -> None:
    """(b) take HIỆN HÀNH lệch queue vẫn báo lỗi (kiểm không bị bỏ qua)."""
    lib = tmp_path / "library-r001"
    add_take(lib, FB, "t001", F1, (30, 40))
    corrupt_receipt_sha(lib, FB, "t001")
    q = write_queue(tmp_path / "b1", "r001", [(F1, "CHAR_01", "FACE", FB)])
    r = view([lib], [q], tmp_path / "out", echo=lambda *_: None)
    assert r["exit"] == 1
    assert any("prompt_text_sha256 lệch" in e and F1 in e for e in r["errors"]), r["errors"]


def test_older_library_superseded_take_still_checked_against_queue(tmp_path: Path) -> None:
    """(c) take bị thay bởi thư viện MỚI HƠN vẫn bị kiểm queue của rev cũ."""
    b = build_partial(tmp_path)
    corrupt_receipt_sha(b["r1"], FB, "t001")  # t001 của r001 là F1 (bị r002 thay)
    r = view([b["r1"], b["r2"]], b["q"], tmp_path / "out", echo=lambda *_: None)
    assert r["exit"] == 1
    assert any("prompt_text_sha256 lệch" in e and F1 in e for e in r["errors"]), r["errors"]


def test_same_rev_superseded_take_survives_a_newer_library(tmp_path: Path) -> None:
    """CR-VIEWFIX (a): take thay CÙNG thư viện cũ (01 vs 01f) VÀ khóa đó còn bị thư viện mới hơn thay: vẫn bỏ qua kiểm queue."""
    r1, r2, fsfx = tmp_path / "library-r001", tmp_path / "library-r002", "batch-01f-CHAR_01-FACE"
    old = add_take(r1, FB, "t001", F1, (30, 40))
    add_take(r1, fsfx, "t001", F1, (30, 42))
    add_take(r2, FB, "t001", F1_NEW, (30, 44))
    corrupt_receipt_sha(r1, FB, "t001")
    q1 = write_queue(tmp_path / "b1", "r001", [(F1, "CHAR_01", "FACE", fsfx)])
    q2 = write_queue(tmp_path / "b2", "r002", [(F1_NEW, "CHAR_01", "FACE", FB)])
    out = tmp_path / "out"
    r = view([r1, r2], [q1, q2], out, echo=lambda *_: None)
    assert r["exit"] == 0, r["errors"]
    assert any(old in p.name for p in (out / "CHAR_01" / "FACE_r001_rejected").glob("*.png"))


def test_take_retired_inside_the_current_library_reaches_index(tmp_path: Path) -> None:
    """CR-VIEWFIX (b): take rút trong CHÍNH thư viện hiện hành phải có trong INDEX.json/superseded."""
    lib, fsfx = tmp_path / "library-r001", "batch-01f-CHAR_01-FACE"
    add_take(lib, FB, "t001", F1, (30, 40))
    add_take(lib, fsfx, "t001", F1, (30, 42))
    q = write_queue(tmp_path / "b1", "r001", [(F1, "CHAR_01", "FACE", fsfx)])
    out = tmp_path / "out"
    r = view([lib], [q], out, echo=lambda *_: None)
    assert r["exit"] == 0, r["errors"]
    assert len(r["superseded"]) == 1
    index = json.loads((out / "INDEX.json").read_text(encoding="utf-8"))
    assert len(index["superseded"]) == 1
