"""Thư viện tham chiếu giả cho các test ``jjv ref stage`` (``test_ref_stage*.py``).

Không mạng, không chạm thư viện thật, không chạm thư mục input ComfyUI thật.  ``build_library`` dựng: nhóm pose
``standing`` (3 id kept có bản full, 2 id chỉ thumbnail KHÔNG kept, 1 id kept nhưng trên đĩa chỉ còn thumbnail), nhóm
face ``closeup`` (danh sách CC0 theo id, không sha), nhóm costume không được cấp, nhóm pose ``quarantine`` bị cách ly.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
KEPT = "KEPT_BY_USER_2026-10-31_INTERNAL_REFERENCE_ONLY"
CC0 = "CC0_1_0_INTERNAL_REFERENCE_ONLY"
POSE_HEADER = "full_png,id,pose_id,series_ja,source_url,thumb"
FACE_HEADER = "hair_length_zh,id,source_url,thumb"
POSE_URL = "https://ai-pose-gallery.pages.dev/img/{id}.png"


def jjv():
    spec = importlib.util.spec_from_file_location("jjv_ref_stage", SKILL / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def index(library: Path, ref_type: str, group: str, header: str, rows: list[str]) -> Path:
    folder = library / "by-type" / ref_type / group
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "INDEX.csv").write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return folder


def pose_row(item_id: str, full: bool, series: str = "standing") -> str:
    return f"{full},{item_id},{item_id.split('_')[0]},{series},{POSE_URL.format(id=item_id)},True"


def write_file(folder: Path, name: str, payload: bytes) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def kept_json(library: Path, name: str, rows: list[dict], *, wrap: bool = True) -> Path:
    path = library / name
    path.write_text(json.dumps({"library": name, "status": KEPT, "items": rows} if wrap else rows), encoding="utf-8")
    return path


def pose_kept(sha256_key: str = "sha256", **extra) -> dict:
    return {"path": "kept-pose.json", "items": "items", "id": "id", "sha256": sha256_key, **extra}


def face_kept(**extra) -> dict:
    return {"path": "kept-face.json", "id": "id", **extra}


def status_file(library: Path, groups: dict[str, dict], not_granted: dict[str, str] | None = None) -> Path:
    doc: dict = {"schema": "jjv/ref-license-status/v1", "groups": groups}
    if not_granted:
        doc["not_granted"] = not_granted
    path = library / "LICENSE-STATUS.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def build_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    pose = index(root, "pose", "standing", POSE_HEADER, [
        pose_row("P001_front", True), pose_row("P002_front", True), pose_row("P003_front", True),
        pose_row("P047_side", False),   # có dòng CSV, chỉ thumbnail, KHÔNG thuộc kept set (ca thật của critic)
        pose_row("P001_high", False),   # thumbnail của một pose có bản full khác: cũng không thuộc kept set
        pose_row("P008_front", True),   # thuộc kept set (sha bản full) nhưng trên đĩa chỉ còn thumbnail
    ])
    full = {item: write_file(pose, f"full/{item}.png", f"\x89PNG {item} full".encode())
            for item in ("P001_front", "P002_front", "P003_front")}
    for item in ("P001_front", "P002_front", "P047_side", "P001_high", "P008_front"):
        write_file(pose, f"thumbs/{item}.webp", f"RIFF {item} thumb".encode())
    kept_json(root, "kept-pose.json", [
        *({"id": item, "sha256": sha(path), "local_path": f"{item}.png"} for item, path in full.items()),
        {"id": "P008_front", "sha256": sha_bytes(b"\x89PNG P008_front full that is not on disk"),
         "local_path": "P008_front.png"},
    ])
    face = index(root, "face", "closeup", FACE_HEADER, [
        f"short,{item},https://ai-portrait-gallery.pages.dev/img/full/{item}.png,True"
        for item in ("f0001", "f0002", "f0003")
    ])
    write_file(face, "f0001.webp", b"RIFF face f0001")
    write_file(face, "f0003.webp", b"RIFF face f0003")  # có file, có CSV, KHÔNG có trong danh sách CC0
    kept_json(root, "kept-face.json", [{"id": "f0001"}, {"id": "f0002"}], wrap=False)
    costume = index(root, "costume", "spring", "id,source_url,tags_en,thumb", [
        "AUT-0001,https://ai-costume-gallery.pages.dev/png/AUT-0001.png,black;dress,True",
    ])
    write_file(costume, "AUT-0001.webp", b"RIFF costume AUT-0001")
    quarantine = index(root, "pose", "quarantine", POSE_HEADER, [pose_row("Q001_front", True, "quarantine")])
    q_file = write_file(quarantine, "full/Q001_front.png", b"\x89PNG Q001 front full")
    kept_json(root, "kept-quarantine.json", [{"id": "Q001_front", "sha256": sha(q_file)}])
    status_file(root, {
        "pose/standing": {"status": KEPT, "kept_set": pose_kept(), "basis": "test"},
        "face/closeup": {"status": CC0, "kept_set": face_kept(), "basis": "test"},
        "pose/quarantine": {"status": "QUARANTINED_2026-10-31", "basis": "test",
                            "kept_set": {"path": "kept-quarantine.json", "items": "items", "id": "id", "sha256": "sha256"}},
    })
    return root


def run_stage(argv: list[str], capsys) -> tuple[int, dict]:
    code = jjv().main(["ref", "stage", *argv])
    return code, json.loads(capsys.readouterr().out)


def common(library: Path, comfy_input: Path) -> list[str]:
    return ["--library-root", str(library), "--comfy-input", str(comfy_input)]


def staged_files(comfy_input: Path) -> list[Path]:
    return sorted(p for p in comfy_input.rglob("*") if p.is_file())


def refusals(out: dict) -> dict[str, str]:
    return {row["id"]: row["reason"] for row in out["refused"]}


__all__ = ["SKILL", "KEPT", "CC0", "POSE_HEADER", "FACE_HEADER", "jjv", "sha", "sha_bytes", "index", "pose_row",
           "write_file", "kept_json", "pose_kept", "face_kept", "status_file", "build_library", "run_stage", "common",
           "staged_files", "refusals"]
