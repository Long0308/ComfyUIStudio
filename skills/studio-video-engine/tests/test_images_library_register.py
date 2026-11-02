"""``jjv images library register``: ảnh ngoài luồng (user duyệt) vào thư viện qua compare + approve + `library view`, rồi anchor_pack tìm thấy.

Không GPU, không mạng; thế giới giả = fixture thư viện nhỏ + một ảnh PNG/JPG tự tạo.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from engine.comfy.settings import settings_from_machine
from engine.core.errors import Refused
from engine.images import library, library_register
from engine.images.library_view import view
from engine.layout.context import load_context
from engine.video import anchor_pack, anchor_verify
from images_fixtures import CARTOON, LIVE, World
from images_library_fixtures import build

QUIET = lambda _m: None  # noqa: E731


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _approval_doc(*shas: str, domain: str = LIVE, status: str = "approved") -> dict:
    """Shape của APPROVALS-*.json thật: ``items[]`` mỗi dòng có sha256, status, domain."""
    return {"by": "user (chat)", "items": [{"shot": "CHAR_01_FACE", "file": "ext/x.png", "sha256": sha, "status": status,
                                            "domain": domain} for sha in shas]}


class Setup:
    """Thư viện r001 (CHAR_01 FACE 01) đã có view; một ảnh nguồn + file duyệt; các thư mục đích của register."""

    def __init__(self, tmp: Path, *, kind: str = "png", mention: bool = True) -> None:
        self.tmp = tmp
        self.world = World(tmp, domain=LIVE)
        self.ctx = load_context(self.world.root, self.world.machine_path)
        self.fx = build(tmp / "fx")
        self.out = tmp / "by"
        assert view([self.fx["r1"]], [self.fx["q1"]], self.out, echo=QUIET)["exit"] == 0
        image = Image.new("RGB", (48, 64), (200, 30, 90))
        image.putpixel((3, 4), (10, 20, 30))
        self.source = tmp / "ext" / ("face." + ("png" if kind == "png" else "jpg"))
        self.source.parent.mkdir(parents=True)
        image.save(self.source, format="PNG" if kind == "png" else "JPEG", **({"quality": 90} if kind == "jpg" else {}))
        self.approval = tmp / "ext" / "approval.json"
        self.approval.write_text(json.dumps(_approval_doc(_sha(self.source) if mention else "0" * 64)), encoding="utf-8")
        self.lib, self.queues = tmp / "library-ext", tmp / "q-ext"

    def register(self, **over):
        args = dict(character="CHAR_01", kind="FACE", file=self.source, label="OFFICE_EXPLAINING", approved_by="user (chat)",
                    approval_source=self.approval, library_out=self.out, source_library=self.lib, queue_dir=self.queues,
                    view_libraries=[self.fx["r1"]], view_queues=[self.fx["q1"]])
        return library_register.register(self.ctx, **{**args, **over})


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()} if root.is_dir() else {}


def test_register_then_view_then_anchor_pack_finds_it(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    result = s.register()
    assert result["status"] == "registered" and result["view"]["exit"] == 0
    pid = result["prompt_id"]
    assert pid == "CHAR_01_FACE_90_OFFICE_EXPLAINING_r001x" and result["sha256"] == _sha(s.source)
    index = json.loads((s.out / "INDEX.json").read_text("utf-8"))
    entry = next(e for e in index["characters"]["CHAR_01"]["FACE"] if e["prompt_id"] == pid)
    assert entry["sha256"] == result["sha256"] and entry["file"].startswith("CHAR_01/FACE/90_90_OFFICE_EXPLAINING__")
    assert any(e["prompt_id"].startswith("CHAR_01_FACE_01") for e in index["characters"]["CHAR_01"]["FACE"])  # ảnh cũ còn nguyên
    assert library.current_approval(s.lib, pid) is not None  # đường approve của thư viện nhận
    receipt = json.loads(Path(result["receipt"]).read_text("utf-8"))
    assert receipt["route"] == "user-approved-external" and receipt["approval_source"]["sha256"] == _sha(s.approval)
    assert receipt["source"] == {"path": s.source.resolve().as_posix(), "sha256": _sha(s.source), "converted": False}
    problems: list[str] = []
    ref = anchor_pack._library_ref(s.ctx, s.out, "CHAR_01", "face", entry, "selection", thumbs=None,
                                   settings=settings_from_machine(s.ctx.machine), library_out=None, problems=problems)
    assert ref["sha256"] == result["sha256"] and ref["approval"] == "approved" and ref["route"] == "user-approved-external"
    assert ref["source_route"] == "user-approved-external" and problems == []
    assert anchor_verify._receipt_problem(ref, s.ctx.machine) is None  # pack đã lưu cũng qua kiểm lại


def test_jpg_becomes_an_exact_png_with_stable_bytes(tmp_path: Path) -> None:
    s = Setup(tmp_path, kind="jpg")
    first, second = library_register._png_of(s.source), library_register._png_of(s.source)
    assert first == second and first.startswith(b"\x89PNG")
    with Image.open(s.source) as jpg, Image.open(__import__("io").BytesIO(first)) as png:
        assert list(jpg.convert("RGB").getdata()) == list(png.getdata())
    result = s.register()
    png_sha = hashlib.sha256(first).hexdigest()
    assert result["sha256"] == png_sha != _sha(s.source) and Path(result["image"]).name == f"{png_sha[:12]}.png"
    receipt = json.loads(Path(result["receipt"]).read_text("utf-8"))
    assert receipt["source"]["sha256"] == _sha(s.source) and receipt["source"]["converted"] is True
    assert receipt["ref_hashes"][0]["sha256"] == _sha(s.source)


def test_missing_or_blind_approval_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    with pytest.raises(Refused, match="APPROVAL_SOURCE_MISSING"):
        s.register(approval_source=tmp_path / "nope.json")
    blind = Setup(tmp_path / "blind", mention=False)
    with pytest.raises(Refused, match="APPROVAL_SHA_NOT_FOUND"):
        blind.register()
    with pytest.raises(Refused, match="approved-by"):
        s.register(approved_by="  ")
    with pytest.raises(Refused, match="--label"):
        s.register(label="bad label!")
    with pytest.raises(Refused, match="--kind"):
        s.register(kind="BODY")
    assert not s.lib.exists() and not s.queues.exists() and not blind.lib.exists()


def test_cross_domain_source_is_refused_by_approval_domain(tmp_path: Path) -> None:
    """Duyệt ghi domain khác (cartoon) ⇒ không đăng vào thư viện live-action; không ghi gì."""
    s = Setup(tmp_path)
    s.approval.write_text(json.dumps(_approval_doc(_sha(s.source), domain=CARTOON)), encoding="utf-8")
    with pytest.raises(Refused, match="SOURCE_DOMAIN_MISMATCH"):
        s.register()
    assert not s.lib.exists() and not s.queues.exists()


def test_source_under_another_domains_library_root_is_refused(tmp_path: Path, monkeypatch) -> None:
    """Ảnh nằm trong root thư viện/staging khai trong domain KHÁC ⇒ từ chối, dù duyệt ghi đúng domain."""
    s = Setup(tmp_path)
    domains = tmp_path / "domains"
    domains.mkdir()
    (domains / f"{CARTOON}.json").write_text(json.dumps({"domain_id": CARTOON, "library_roots": [s.source.parent.as_posix()]}),
                                             encoding="utf-8")
    monkeypatch.setattr(library_register, "DOMAINS_DIR", domains)
    with pytest.raises(Refused, match="SOURCE_DOMAIN_MISMATCH"):
        s.register()
    assert not s.lib.exists() and not s.queues.exists()


def test_unstructured_text_that_only_mentions_the_sha_is_refused(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    s.approval.write_text(f"Anh duyet {_sha(s.source)} roi\n", encoding="utf-8")
    with pytest.raises(Refused, match="APPROVAL_NOT_STRUCTURED"):
        s.register()
    assert not s.lib.exists() and not s.queues.exists()


@pytest.mark.parametrize("doc,reason", [
    (lambda sha: _approval_doc("0" * 64), "APPROVAL_SHA_NOT_FOUND"),
    (lambda sha: _approval_doc(sha, status="rejected"), "APPROVAL_NOT_APPROVED"),
    (lambda sha: {"decisions": [{"id": "x", "sha256": sha, "note": "approved"}]}, "APPROVAL_NOT_APPROVED"),
    (lambda sha: {"items": [{"sha256": sha, "status": "approved"}]}, "APPROVAL_DOMAIN_MISSING"),
])
def test_structured_approval_that_does_not_cover_this_sha_is_refused(tmp_path: Path, doc, reason: str) -> None:
    s = Setup(tmp_path)
    s.approval.write_text(json.dumps(doc(_sha(s.source))), encoding="utf-8")
    with pytest.raises(Refused, match=reason):
        s.register()
    assert not s.lib.exists() and not s.queues.exists()


def test_registering_the_same_bytes_again_is_a_no_op(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    first = s.register()
    before = (_tree(s.lib), _tree(s.queues), _tree(s.out))
    again = s.register()
    assert again["status"] == "unchanged" and again["prompt_id"] == first["prompt_id"] and again["sha256"] == first["sha256"]
    assert (_tree(s.lib), _tree(s.queues), _tree(s.out)) == before


def test_second_image_gets_the_next_free_number_and_both_are_listed(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    one = s.register()
    other = tmp_path / "ext" / "face2.png"
    Image.new("RGB", (40, 40), (1, 2, 3)).save(other, format="PNG")
    s.approval.write_text(json.dumps(_approval_doc(_sha(s.source), _sha(other))), encoding="utf-8")
    two = s.register(file=other, label="SECOND")
    assert one["prompt_id"].startswith("CHAR_01_FACE_90_") and two["prompt_id"].startswith("CHAR_01_FACE_91_SECOND")
    rows = json.loads((s.out / "INDEX.json").read_text("utf-8"))["characters"]["CHAR_01"]["FACE"]
    assert {r["prompt_id"] for r in rows} >= {one["prompt_id"], two["prompt_id"]}
    queue = json.loads((s.queues / "queue-ext.json").read_text("utf-8"))
    assert [q["prompt_id"] for q in queue] == sorted([one["prompt_id"], two["prompt_id"]])


def test_cli_register_runs_through_the_library_verb(tmp_path: Path) -> None:
    import argparse
    import io
    from contextlib import redirect_stdout

    from engine.images import cli

    s = Setup(tmp_path)
    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    args = parser.parse_args(["images", "library", "register", "--episode", str(s.world.root), "--machine", str(s.world.machine_path),
                              "--character", "CHAR_01", "--kind", "FACE", "--file", str(s.source), "--label", "OFFICE_EXPLAINING",
                              "--approved-by", "user (chat)", "--approval-source", str(s.approval), "--library-out", str(s.out),
                              "--source-library", str(s.lib), "--queue-dir", str(s.queues), "--view-library", str(s.fx["r1"]),
                              "--view-queue", str(s.fx["q1"])])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.run_images(args)
    printed = json.loads(buffer.getvalue())
    assert code == 0 and printed["ok"] and printed["status"] == "registered" and printed["view"]["exit"] == 0
    assert any(p.name.startswith("90_90_OFFICE_EXPLAINING__") for p in (s.out / "CHAR_01" / "FACE").glob("*.png"))
