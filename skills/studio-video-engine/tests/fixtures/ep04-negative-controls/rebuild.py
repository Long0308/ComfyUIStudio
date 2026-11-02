"""Rebuild picture-only regression fixtures on CPU from retained, hash-bound ep04 footage.

Run from the engine root with PYTHONDONTWRITEBYTECODE=1:
python tests/fixtures/ep04-negative-controls/rebuild.py --editorial <episode>/editorial

These are reconstructions, not recovered historical exports. They port the saved dip
schedule and dissolve easing. Pillow approximates the saved caption geometry, text,
colours and fade; icons, word-pop transforms and sparkles are omitted. FFmpeg fps
conversion and Pillow blur replace Chromium sampling and CSS blur.
No GPU, browser, ComfyUI, production write or gate implementation is used here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from engine.qa import review_media as media  # noqa: E402
from engine.seedvr2.seam_media import find_ffmpeg  # noqa: E402

SIZE = (640, 360)
FPS = 30
WINDOWS = (("012", 995, 60, "T1010", "Q3"), ("012", 1290, 60, "T1310", "Q3"),
           ("005", 1295, 40, "T1310", "Q4"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], **kwargs) -> bytes:
    result = subprocess.run(command, capture_output=True, check=True, **kwargs)
    return result.stdout


def write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)


def caption(image: np.ndarray, shot: dict, frame: int, fonts: dict) -> np.ndarray:
    """Approximate caption.jsx's panel, word colours and fade at the original 1920x1080 geometry."""
    local = frame - shot["start_frame"]
    hide = min(shot["duration_frames"], int(np.ceil((shot["speech_end_in_window_s"] + 0.3) * FPS)))
    opacity = min(np.clip(local / 6, 0, 1), np.clip((hide - local) / 6, 0, 1))
    if opacity <= 0:
        return image
    layer = Image.new("RGBA", (1920, 1080))
    draw = ImageDraw.Draw(layer)
    top = 911  # 1080 - 36 bottom - approximately 133 px of padding + the two text lines
    draw.rounded_rectangle((150, top, 1770, 1044), radius=30, fill="#FFFDF8F2")
    plain, keyword, vi = fonts["plain"], fonts["keyword"], fonts["vi"]
    words = shot["words"]
    widths = [(keyword if word["keyword"] else plain).getlength(word["w"]) + 10 for word in words]
    space = plain.getlength(" ")
    x = (1920 - sum(widths) - space * (len(words) - 1)) / 2

    def mix(a: str, b: str, amount: float) -> tuple[int, int, int, int]:
        rgb = lambda text: [int(text[i:i + 2], 16) for i in (0, 2, 4)]
        return (*[round(u * (1 - amount) + v * amount) for u, v in zip(rgb(a), rgb(b))], 255)

    for index, (word, width) in enumerate(zip(words, widths)):
        lit = float(np.clip((frame - word["startF"]) / 2, 0, 1))
        if word["keyword"]:
            draw.rounded_rectangle((x + 1, top + 15, x + width - 1, top + 72), radius=14,
                                   fill=mix("FFE3EE", "FF2E7E", lit))
            colour = mix("E58FB0", "FFFDF8", lit)
            font = keyword
        else:
            next_start = words[index + 1]["startF"] if index + 1 < len(words) else shot["end_frame_exclusive"]
            end = min(max(word["endF"], word["startF"] + 8), next_start + 4)
            if word["startF"] <= frame < end:
                draw.rounded_rectangle((x + 1, top + 15, x + width - 1, top + 72), radius=14, fill="#CFEFC9")
            colour, font = mix("7C9690", "173A34", lit), plain
        draw.text((x + 5, top + 20), word["w"], font=font, fill=colour, anchor="lt")
        x += width + space
    draw.text((960, top + 85), shot["dialogue_vi"], font=vi, fill="#173A34", anchor="mt")
    layer.putalpha(layer.getchannel("A").point(lambda a: round(a * opacity)))
    layer = layer.resize(SIZE, Image.Resampling.LANCZOS)
    base = Image.fromarray(np.clip(image, 0, 255).round().astype(np.uint8)).convert("RGBA")
    return np.array(Image.alpha_composite(base, layer).convert("RGB"))


def reconstruct(config: dict, first: int, count: int, boundary_id: str, ffmpeg: str, fonts: dict) -> tuple[np.ndarray, list[dict]]:
    width, height = SIZE
    transition = next(t for t in config["motion"]["transitions"] if t["id"] == boundary_id)
    boundary = transition["boundary"]
    shots = {s["id"]: s for s in config["dialogue"]}
    cache, sources = {}, []

    def decode(path: str, expected: str) -> np.ndarray:
        if path not in cache:
            actual = sha(Path(path))
            if actual != expected:
                raise ValueError(f"source hash changed: {path}")
            vf = (f"fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
                  f"crop={width}:{height},format=rgb24")
            raw = run([ffmpeg, "-v", "error", "-i", path, "-an", "-vf", vf, "-f", "rawvideo", "-"])
            cache[path] = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3)
            sources.append({"path": path, "sha256": actual, "decoded_frames_30fps": len(cache[path])})
        return cache[path]

    def picture(shot_id: str, frame: int) -> np.ndarray:
        shot = shots[shot_id]
        local = frame - shot["start_frame"]
        segment = next(s for s in shot["segments"]
                       if s["relative_start_frame"] <= local < s["relative_start_frame"] + s["delivery_frames"])
        frames = decode(segment["path"], segment["sha256"])
        return frames[local - segment["relative_start_frame"]].astype(np.float64)

    def tail(frame: int) -> np.ndarray:
        binding = transition["outgoing_tail"]
        frames = decode(binding["native_path"], binding["native_sha256"])
        return frames[binding["start_from_frame"] + frame - boundary].astype(np.float64)

    frames = []
    for frame in range(first, first + count):
        image = picture(transition["from"] if frame < boundary else transition["to"], frame)
        if transition["type"] == "dip":
            entry = next((e for e in transition["schedule"] if e["t"] == frame - boundary), None)
            if entry:
                white = entry["white"]
                if entry["shot"] == "out_tail":
                    image = tail(frame)
                elif entry["shot"] == "none":
                    image = np.zeros_like(image)
                image = np.clip(image * (1 + 0.4 * white), 0, 255).round().astype(np.uint8)
                image = np.array(Image.fromarray(image).filter(ImageFilter.GaussianBlur(white * 2.5 * width / 1920)))
                image = image * (1 - white) + np.array([255, 248, 236]) * white
        elif transition["type"] == "dissolve" and boundary <= frame < transition["end_exclusive"]:
            assert transition["curve"] == "out"
            alpha = 1 - (1 - (frame - boundary) / transition["frames"]) ** 3
            image = tail(frame) * (1 - alpha) + image * alpha
        shot = shots[transition["from"] if frame < boundary else transition["to"]]
        image = caption(image, shot, frame, fonts)
        frames.append(np.clip(image, 0, 255).round().astype(np.uint8))
    return np.stack(frames), sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editorial", type=Path, required=True)
    parser.add_argument("--font-regular", type=Path, required=True)
    parser.add_argument("--font-bold", type=Path, required=True)
    args = parser.parse_args()
    out = Path(__file__).resolve().parent
    if (out / "MANIFEST.json").exists():
        raise FileExistsError("fixtures already exist; rebuild into a fresh staging copy")
    ffmpeg = find_ffmpeg()
    ffprobe = media.find_ffprobe(ffmpeg)
    manifest = {
        "schema": "jjv/ep04-negative-controls/v1",
        "provenance": "CPU reconstruction from retained source footage, historical transition configs and approximate captions",
        "historical_export_recovered": False,
        "limitations": ["Pillow approximates the original caption panel, text, colours and fades; line layout/shadow are not exact.",
                        "Icons, review labels, word-pop transforms and sparkle overlays omitted.",
                        "FFmpeg fps conversion and Pillow blur replace Chromium video sampling and CSS blur.",
                        "Rebuilt clips are not claimed pixel-identical to the deleted exports."],
        "generator": {"file": Path(__file__).name, "sha256": sha(Path(__file__)),
                      "command": ["python", "tests/fixtures/ep04-negative-controls/rebuild.py", "--editorial", str(args.editorial),
                                  "--font-regular", str(args.font_regular), "--font-bold", str(args.font_bold)],
                      "fonts": [{"path": str(path), "sha256": sha(path)} for path in (args.font_regular, args.font_bold)],
                      "ffmpeg_version": run([ffmpeg, "-version"]).decode().splitlines()[0],
                      "gpu_used": False, "comfyui_called": False},
        "configs": {}, "clips": [],
    }
    fonts = {"plain": ImageFont.truetype(str(args.font_bold), 42), "keyword": ImageFont.truetype(str(args.font_bold), 45),
             "vi": ImageFont.truetype(str(args.font_regular), 29)}
    for version in ("005", "012"):
        source = args.editorial / f"review-hd-v{version}" / "config" / f"review-config-v{version}.json"
        target = out / source.name
        write_new(target, source.read_bytes())
        compositor = source.parent.parent / "src" / "transitions.jsx"
        constants = compositor.with_name("constants.js")
        manifest["configs"][version] = {
            "file": target.name, "sha256": sha(target), "source_path": str(source),
            "compositor_reference": {"path": str(compositor), "sha256": sha(compositor)},
            "constants_reference": {"path": str(constants), "sha256": sha(constants)},
        }
    for version, first, count, boundary, gate in WINDOWS:
        config = json.loads((out / manifest["configs"][version]["file"]).read_text("utf-8"))
        frames, sources = reconstruct(config, first, count, boundary, ffmpeg, fonts)
        target = out / f"v{version}-f{first}-{first + count - 1}-{gate.lower()}.mp4"
        run([ffmpeg, "-v", "error", "-n", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{SIZE[0]}x{SIZE[1]}",
             "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-crf", "10", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", str(target)], input=frames.tobytes())
        info = media.probe(target, ffprobe)
        assert info.frames == count and float(info.fps) == FPS
        manifest["clips"].append({"file": target.name, "sha256": sha(target), "version": version,
                                  "first_frame": first, "end_frame_exclusive": first + count, "frame_count": count,
                                  "fps": FPS, "size": list(SIZE), "boundary": boundary, "gate": gate,
                                  "expected_status": "FAIL", "sources": sources})
        print(target.name, count, sha(target), flush=True)
    write_new(out / "MANIFEST.json", (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
