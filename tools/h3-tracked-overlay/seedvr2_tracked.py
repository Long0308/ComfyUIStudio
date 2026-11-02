#!/usr/bin/env python3
"""SeedVR2 2K (aspect-kept) cho clip H3 đã tracked-overlay — chạy đúng recipe seedvr2-ep05-aspect-v002.

Recipe (từ production-local/engine/staging/newtecons-30s/seedvr2-ep05-aspect-v002/S02_A/receipt.json):
  lanczos 1280x704 → 2640x1452, ImageCrop 2560x1440 tại x=40,y=6, SeedVR2 7B int8 convrot,
  VAE fp16, tile 768 / overlap 64 / temporal 32+4, 17 frame/chunk, KSampler 1 step euler simple cfg 1,
  colour-fix lab, SaveVideo h264 crf 16, seed 2026101806. Chia chunk như run_2k_r2.py:
  lõi 13 khung, lề 4 khung hai bên, ghép lõi rồi mux audio gốc (copy).

Bảo vệ GPU dùng chung: KHÔNG submit khi /queue có ≥ --max-queue (mặc định 2) job; mặc định thoát mã 3
và in trạng thái. --wait: chờ tới khi queue rảnh. Không bao giờ xoá/huỷ job của lane khác.
Ghi mới, không đè.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TEMPLATE = ROOT / "docs/media-stage/H3-BENCHMARK-BASE-VS-FLEX/seedvr2_2k_aspect_TEMPLATE.api.json"
BASE = "http://127.0.0.1:8188"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def api(path: str):
    r = requests.get(BASE + path, timeout=30)
    r.raise_for_status()
    return r.json()


def queue_len() -> int:
    q = api("/queue")
    return len(q["queue_running"]) + len(q["queue_pending"])


def await_job(pid: str, run: Path, label: str):
    while True:
        hist = api("/history/" + pid)
        if pid in hist:
            h = hist[pid]
            save(run / f"{label}.history.json", h)
            if h.get("status", {}).get("status_str") != "success":
                raise RuntimeError(f"ComfyUI job thất bại; history đã lưu: {label}")
            return h
        time.sleep(5)


def elapsed(h) -> float:
    msg = h["status"]["messages"]
    start = next(x[1]["timestamp"] for x in msg if x[0] == "execution_start")
    end = next(x[1]["timestamp"] for x in msg if x[0] == "execution_success")
    return (end - start) / 1000


def download(h, dest: Path) -> None:
    cands = []
    for node in h["outputs"].values():
        for values in node.values():
            if isinstance(values, list):
                cands += [x for x in values if isinstance(x, dict) and x.get("type") == "output" and x.get("filename", "").endswith(".mp4")]
    if len(cands) != 1:
        raise RuntimeError("cần đúng một mp4 output: " + str(cands))
    r = requests.get(BASE + "/view", params=cands[0], timeout=300)
    r.raise_for_status()
    with dest.open("xb") as f:
        f.write(r.content)


def extract(src: Path, dest: Path, start: int, end: int) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-i", str(src), "-vf",
                    f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS", "-an",
                    "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p", str(dest)], check=True)


def upload(path: Path, subfolder: str) -> str:
    with path.open("rb") as f:
        r = requests.post(BASE + "/upload/image", files={"image": (path.name, f, "video/mp4")},
                          data={"type": "input", "subfolder": subfolder}, timeout=180)
    r.raise_for_status()
    d = r.json()
    return (d.get("subfolder", "") + "/" + d["name"]).lstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="S07A_TRACKED")
    ap.add_argument("--max-queue", type=int, default=2)
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="chỉ chuẩn bị chunk + graph, không submit")
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(f"từ chối ghi đè: {args.out}")
    run = args.run_dir
    run.mkdir(parents=True, exist_ok=True)
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    nframes = int(json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                                      "-show_entries", "stream=nb_read_frames", "-of", "json", str(args.video)]))["streams"][0]["nb_read_frames"])
    progress = {"video": str(args.video), "video_sha256": sha(args.video), "template_sha256": sha(TEMPLATE),
                "frames": nframes, "chunks": [], "recipe": "seedvr2-ep05-aspect-v002 (lanczos 2640x1452 → crop 2560x1440 @40,6; 7B int8; tile768/ov64; 17f/chunk; crf16)"}
    save(run / "progress.json", progress)
    chunks = []
    for i, start in enumerate(range(0, nframes, 13)):
        end = min(nframes, start + 13)
        low, high = max(0, start - 4), min(nframes, end + 4)
        label = f"{args.label}_chunk{i:02d}"
        raw = run / f"{label}_input.mp4"
        result = run / f"{label}_output.mp4"
        core = run / f"{label}_core.mp4"
        if not raw.exists():
            extract(args.video, raw, low, high)
        graph = copy.deepcopy(template)
        graph["15"]["inputs"]["filename_prefix"] = f"newtecons_live_action/h3-tracked-overlay-v001/{args.label}/chunk{i:02d}"
        rec = {"chunk": i, "raw": [low, high], "core": [start, end], "input": str(raw), "input_sha256": sha(raw)}
        if args.dry_run:
            graph["1"]["inputs"]["file"] = f"(dry-run) {raw.name}"
            save(run / f"{label}.api.json", graph)
            rec["status"] = "prepared_not_submitted"
            chunks.append(rec)
            continue
        submission = run / f"{label}.submission.json"
        if submission.exists():
            pid = json.loads(submission.read_text(encoding="utf-8"))["prompt_id"]
        else:
            while queue_len() >= args.max_queue:
                print(f"QUEUE_BUSY {queue_len()} job(s) >= {args.max_queue}; không submit để không chen lane GPT", flush=True)
                if not args.wait:
                    progress["chunks"] = chunks
                    progress["aborted"] = f"queue busy at chunk {i}"
                    save(run / "progress.json", progress)
                    return 3
                time.sleep(30)
            graph["1"]["inputs"]["file"] = upload(raw, "newtecons_live_action/h3_tracked_overlay_v001")
            save(run / f"{label}.api.json", graph)
            r = requests.post(BASE + "/prompt", json={"prompt": graph, "client_id": "h3-tracked-seedvr2-" + uuid.uuid4().hex}, timeout=60)
            r.raise_for_status()
            save(submission, r.json())
            pid = r.json()["prompt_id"]
        h = await_job(pid, run, label)
        if not result.exists():
            download(h, result)
        if not core.exists():
            extract(result, core, start - low, start - low + (end - start))
        rec.update({"prompt_id": pid, "server_s": elapsed(h), "output_sha256": sha(result), "status": "done"})
        chunks.append(rec)
        progress["chunks"] = chunks
        save(run / "progress.json", progress)
        print(f"{label} server_s={rec['server_s']}", flush=True)
    if args.dry_run:
        progress["chunks"] = chunks
        save(run / "progress.json", progress)
        print(json.dumps({"dry_run": True, "chunks": len(chunks), "run_dir": str(run)}))
        return 0
    manifest = run / "concat.txt"
    manifest.write_text("".join("file '" + (run / f"{args.label}_chunk{c['chunk']:02d}_core.mp4").as_posix().replace("'", "'\\''") + "'\n" for c in chunks), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-f", "concat", "-safe", "0", "-i", str(manifest), "-i", str(args.video),
                    "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-movflags", "+faststart", str(args.out)], check=True)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(args.out)]))
    progress.update({"final": str(args.out), "final_sha256": sha(args.out),
                     "seedvr2_server_seconds_total": sum(c["server_s"] for c in chunks),
                     "final_probe": [{k: s.get(k) for k in ("codec_type", "width", "height", "nb_read_frames", "r_frame_rate")} for s in probe["streams"]]})
    save(run / "progress.json", progress)
    print(json.dumps({"final": str(args.out), "sha256": progress["final_sha256"], "server_s": progress["seedvr2_server_seconds_total"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
