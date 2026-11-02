"""Dựng dữ liệu CHỈ-ĐỌC cho panel NEWTECONS Step UI từ đĩa (không GPU, không gửi /prompt, không xoá gì).

1. ``web/data/image/results-index.json`` (``jjv/image-results-index/v1``): ảnh trong ``ComfyUI/output/NEWTECONS`` theo thư mục.
   Lý do: ``/history`` chỉ giữ ~200 job nên kết quả cũ biến mất, và render của engine dùng prefix riêng.
2. ``web/data/video/media/<episode>.media.json`` (``jjv/video-ui-media/v1``): poster, bản 1440 (SeedVR2) và phim cuối của tập, lấy từ
   receipt trên đĩa. File nằm ngoài ``output/`` được HARDLINK vào ``output/NEWTECONS/step-ui-media/<episode>/`` (cùng ổ, không
   tốn chỗ) để ``GET /view`` xem được; poster là frame JPG trích bằng ffmpeg.

Chạy: ``python -I tools/build_step_ui_index.py [--episode-config tools/episodes/ep05.json]`` (mặc định chỉ dựng chỉ mục ảnh +
media tập ep05 nếu cấu hình có).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

NODE = Path(__file__).resolve().parents[1]
COMFY = NODE.parents[1]
OUTPUT = COMFY / "output"
REPO = COMFY.parents[1]
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
INDEX_SCHEMA = "jjv/image-results-index/v1"
MEDIA_SCHEMA = "jjv/video-ui-media/v1"
MAX_FILES_PER_FOLDER = 60
MEDIA_DIR = "NEWTECONS/step-ui-media"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scan_images(root: Path = OUTPUT, top: str = "NEWTECONS") -> dict:
    """Thư mục -> {count, files[<=60 mới nhất]} cho mọi ảnh dưới ``output/<top>`` (bỏ ``step-ui-media``)."""
    folders: dict[str, dict] = {}
    base = root / top
    for path in base.rglob("*") if base.is_dir() else []:
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXT:
            continue
        rel = path.parent.relative_to(root).as_posix()
        if rel.startswith(MEDIA_DIR):
            continue
        st = path.stat()
        folders.setdefault(rel, {"count": 0, "files": []})
        folders[rel]["count"] += 1
        folders[rel]["files"].append({"name": path.name, "mtime": int(st.st_mtime), "size": st.st_size})
    for entry in folders.values():
        entry["files"] = sorted(entry["files"], key=lambda f: f["mtime"], reverse=True)[:MAX_FILES_PER_FOLDER]
    return {"schema": INDEX_SCHEMA, "generated_at": now(), "root": f"output/{top}", "folders": dict(sorted(folders.items()))}


def view_url(rel_path: str) -> str:
    from urllib.parse import quote
    folder, _, name = rel_path.rpartition("/")
    return f"/view?filename={quote(name)}&subfolder={quote(folder)}&type=output"


def link_into_output(src: Path, rel_dest: str) -> str | None:
    """Hardlink (không có thì copy) ``src`` vào ``output/<rel_dest>``; trả URL /view, hoặc None khi nguồn không có."""
    if not src.is_file():
        return None
    dest = OUTPUT / rel_dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        try:
            os.link(src, dest)
        except OSError:
            shutil.copy2(src, dest)
    return view_url(rel_dest)


def make_poster(video: Path, rel_dest: str, at: str = "1.0") -> str | None:
    dest = OUTPUT / rel_dest
    if not video.is_file():
        return None
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", at, "-i", str(video), "-frames:v", "1", "-vf", "scale=640:-2",
                               str(dest)], capture_output=True, text=True)
        if done.returncode != 0 or not dest.is_file():
            return None
    return view_url(rel_dest)


def _abs(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO / p


def build_media(cfg: dict) -> dict:
    """``cfg``: {episode, native_dir (output-rel), shots:{ID:{native, hd, logo, note}}, final:{label, file, receipt}}."""
    ep = cfg["episode"]
    shots: dict[str, dict] = {}
    for shot, src in cfg.get("shots", {}).items():
        entry: dict = {"sources": {}}
        native = _abs(src["native"]) if src.get("native") else None
        if native:
            entry["thumb_url"] = make_poster(native, f"{MEDIA_DIR}/{ep}/{shot}_poster.jpg")
            entry["sources"]["native"] = str(native)
        for key, slot in (("hd", "hd_url"), ("logo", "logo_url")):
            if src.get(key):
                entry[slot] = link_into_output(_abs(src[key]), f"{MEDIA_DIR}/{ep}/{shot}_{key}_{_abs(src[key]).name}")
                entry["sources"][key] = str(_abs(src[key]))
        if src.get("note"):
            entry["note"] = src["note"]
        shots[shot] = {k: v for k, v in entry.items() if v not in (None, {})}
    final = None
    if cfg.get("final"):
        f = cfg["final"]
        file = _abs(f["file"])
        url = link_into_output(file, f"{MEDIA_DIR}/{ep}/{file.name}")
        final = {"label": f.get("label"), "url": url, "path": str(file), "bytes": file.stat().st_size if file.is_file() else None,
                 "receipt": f.get("receipt"), "exists": bool(url)}
    return {"schema": MEDIA_SCHEMA, "generated_at": now(), "episode": ep, "shots": shots, "final": final}


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episode-config", action="append", default=[], help="JSON {episode, shots, final}; lặp được")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args(argv)
    if not args.no_images:
        idx = scan_images()
        write_json(NODE / "web/data/image/results-index.json", idx)
        print(f"image index: {len(idx['folders'])} folders, {sum(f['count'] for f in idx['folders'].values())} images")
    for cfg_path in args.episode_config:
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        doc = build_media(cfg)
        write_json(NODE / f"web/data/video/media/{cfg["episode"]}.media.json", doc)
        print(f"media {cfg['episode']}: {len(doc['shots'])} shots, final={'yes' if doc['final'] and doc['final']['exists'] else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
