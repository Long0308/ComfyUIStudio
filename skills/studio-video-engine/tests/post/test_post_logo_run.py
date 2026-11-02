"""Chạy thật trên clip tổng hợp (ffmpeg + OpenCV, CPU): render đối chứng; từ chối domain cartoon, sha sai,
mất bám cuối clip, cổng mép; không có file mp4 khi từ chối; CLI. Không chạm asset sản xuất."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.post.logo import cli as cli_mod
from engine.post.logo import detect as detect_mod
from engine.post.logo import render as render_mod
from engine.post.logo import run as run_mod
from engine.post.logo.edgecheck import EDGE_FAIL
from engine.post.logo.policy import NOT_ENABLED, SHA_MISMATCH
from engine.post.logo.video_io import FrameWriter, VideoInfo

FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="CPU integration needs ffmpeg/ffprobe on PATH")

SIZE, PATCH, N_FRAMES = 256, 150, 24
PATCH_XY = (40, 40)
SEED_BOX = (40 + PATCH // 2 - 15, 40 + PATCH // 2 - 18, 30, 36)   # inside the patch at frame 0
LINE_DY = SEED_BOX[1] + SEED_BOX[3] + 20 - PATCH_XY[1]           # dark horizontal line 20 px below the box
CARTOON = read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json")


def frames(lost: set[int] = frozenset(), *, bright: bool = False, mark: bool = False) -> list[np.ndarray]:
    rng = np.random.default_rng(7)
    lo, hi = (165, 240) if bright else (40, 220)
    noise = rng.integers(lo, hi, size=(PATCH, PATCH), dtype=np.uint8)
    # Smoothed blobs: still plenty of corners for KLT, but the x264 error is even across the crop (raw per-pixel noise
    # makes the band around strong gradients lossier than the rest, which is not what shirt fabric looks like).
    texture = np.repeat(cv2.GaussianBlur(noise, (0, 0), 1.2)[..., None], 3, axis=2)
    texture[LINE_DY:LINE_DY + 2, :] = 20                           # long edge the edge gate watches
    if mark:                                                       # hollow navy mark where SEED_BOX sits at frame 0
        x, y = SEED_BOX[0] - PATCH_XY[0] + 5, SEED_BOX[1] - PATCH_XY[1] + 5
        texture[y:y + 26, x:x + 20] = (103, 55, 50)
        texture[y + 6:y + 20, x + 6:x + 14] = (235, 230, 225)
    out = []
    for i in range(N_FRAMES):
        img = np.full((SIZE, SIZE, 3), 128, dtype=np.uint8)
        if i not in lost:
            img[PATCH_XY[1]:PATCH_XY[1] + PATCH, PATCH_XY[0] + i:PATCH_XY[0] + i + PATCH] = texture
        out.append(img)
    return out


def write_clip(path: Path, lost: set[int] = frozenset(), *, audio: bool = False, **kw) -> Path:
    info = VideoInfo(SIZE, SIZE, 24, 1, N_FRAMES, "h264", "yuv420p", None, None, None, None, None, 0)
    silent = path.with_name("silent-" + path.name) if audio else path
    writer = FrameWriter(silent, silent, info, 10, FFMPEG, preset="ultrafast")
    for img in frames(lost, **kw):
        writer.write(img)
    writer.close()
    if audio:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(silent), "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(path)],
                       check=True, capture_output=True, timeout=120)
    return path


def write_logo(path: Path) -> Path:
    img = np.zeros((80, 64, 4), dtype=np.uint8)
    img[10:70, 12:52] = (30, 30, 200, 255)        # red icon (BGRA)
    img[22:58, 24:40] = (0, 0, 0, 0)               # hollow centre, like an N
    assert cv2.imwrite(str(path), img)
    return path


def domain_for(logo: Path, *, detect: bool = False, sha: str | None = None) -> dict:
    block = {"enabled": True, "asset": {"path": "assets/logo.png", "sha256": sha or sha256_file(logo)}}
    if detect:
        block["detect"] = {"search_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                           "mark_height_frac": {"min": 0.06, "max": 0.16}, "aspect_tolerance": 0.4,
                           "mark_rgb": [50, 55, 103], "dark_threshold": 50, "fill_range": [0.2, 0.95],
                           "color_min_similarity": 0.5, "box_pad_frac": 0.2, "search_frames": 6,
                           "min_score": 0.15, "min_margin": 0.05, "min_agreement": 0.5}
    return {"domain_id": "test_live", "post": {"logo_composite": block}}


def request(tmp_path: Path, video: Path, logo: Path, **kw) -> run_mod.LogoRequest:
    base = dict(video=video, logo=logo, out=tmp_path / "out" / "syn.mp4", ffmpeg=FFMPEG, ffprobe=FFPROBE,
                seed_frame=0, seed_box=SEED_BOX, track_window=256, thread_rgb=(50, 55, 103),
                strip_frames=(2, 12, 20))
    base.update(kw)
    return run_mod.LogoRequest(**base)


def nothing_published(tmp_path: Path) -> bool:
    out = tmp_path / "out"
    return not out.exists() or not any(out.iterdir())


def test_control_render_copies_audio_and_writes_receipt_once(tmp_path: Path) -> None:
    video = write_clip(tmp_path / "clip.mp4", audio=True)
    logo = write_logo(tmp_path / "logo.png")
    receipt = run_mod.composite_logo(domain_for(logo), request(tmp_path, video, logo))
    out = tmp_path / "out" / "syn.mp4"
    assert out.is_file() and receipt["outputs"]["video"]["sha256"] == sha256_file(out)
    assert receipt["gates"]["track"]["pass"] is True and receipt["gates"]["edge"]["pass"] is True
    assert receipt["gates"]["audio"]["mode"] == "copy" and receipt["gates"]["audio"]["packets_equal"] is True
    assert receipt["gates"]["audio"]["packets_pre"] == receipt["gates"]["audio"]["packets_post"]
    assert receipt["seed"]["source"] == "cli" and receipt["seed"]["box_xywh"] == list(SEED_BOX)
    assert receipt["inputs"]["video"]["sha256"] == sha256_file(video)
    assert receipt["inputs"]["logo"]["sha256"] == sha256_file(logo) == receipt["inputs"]["logo"]["domain_declared_sha256"]
    assert receipt["render"]["params"]["thread_rgb"] == [50, 55, 103] and receipt["render"]["rng_seed"] == 20261031
    assert receipt["outputs"]["video"]["probe"]["nb_frames"] == N_FRAMES
    stored = read_json(tmp_path / "out" / "syn.logo-receipt.json")
    assert stored["outputs"]["video"]["sha256"] == receipt["outputs"]["video"]["sha256"]
    for name in ("syn_track_preview.png", "syn_strip_4x.png", "syn_strip_1to1.png", "syn_edgecheck_6x.png"):
        assert (tmp_path / "out" / name).is_file()
    assert not list((tmp_path / "out").glob(".*.partial.mp4"))
    with pytest.raises(Refused, match="overwrite"):
        run_mod.composite_logo(domain_for(logo), request(tmp_path, video, logo))


def test_cartoon_domain_and_wrong_sha_refuse_before_touching_the_video(tmp_path: Path) -> None:
    logo = write_logo(tmp_path / "logo.png")
    missing = tmp_path / "does-not-exist.mp4"       # never probed: the refusal must come first
    with pytest.raises(Refused, match=NOT_ENABLED):
        run_mod.composite_logo(CARTOON, request(tmp_path, missing, logo))
    with pytest.raises(Refused, match=SHA_MISMATCH):
        run_mod.composite_logo(domain_for(logo, sha="b" * 64), request(tmp_path, missing, logo))
    with pytest.raises(Refused, match=SHA_MISMATCH):
        run_mod.composite_logo(domain_for(logo), request(tmp_path, missing, logo, logo_sha256="c" * 64))
    assert nothing_published(tmp_path)


def test_trailing_loss_refuses_before_any_encode(tmp_path: Path, monkeypatch) -> None:
    video = write_clip(tmp_path / "clip.mp4", lost=set(range(N_FRAMES - 4, N_FRAMES)))
    logo = write_logo(tmp_path / "logo.png")

    def never(*args, **kwargs):
        raise AssertionError("FrameWriter must not start when the track gate is red")

    monkeypatch.setattr(run_mod, "FrameWriter", never)
    with pytest.raises(Refused) as caught:
        run_mod.composite_logo(domain_for(logo), request(tmp_path, video, logo))
    assert caught.value.evidence["code"] == "TRAILING_LOSS"
    assert caught.value.evidence["trailing_loss"] == list(range(N_FRAMES - 4, N_FRAMES))
    assert nothing_published(tmp_path)


def test_edge_band_damage_refuses_and_publishes_nothing(tmp_path: Path) -> None:
    video = write_clip(tmp_path / "clip.mp4")
    logo = write_logo(tmp_path / "logo.png")

    def vandal(frame, box_quad, logo_quad, alpha, params, rng):
        out, dbg = render_mod.composite_frame(frame, box_quad, logo_quad, alpha, params, rng)
        y = PATCH_XY[1] + LINE_DY                      # paint the long collar edge white: the band must catch it
        out[y - 2:y + 4, :] = 255
        return out, dbg

    with pytest.raises(Refused) as caught:
        run_mod.composite_logo(domain_for(logo), request(tmp_path, video, logo), compositor=vandal)
    assert caught.value.evidence["code"] == EDGE_FAIL and str(caught.value).startswith(EDGE_FAIL)
    assert caught.value.evidence["failing_frames"] == [2, 12, 20]
    assert nothing_published(tmp_path)


def test_auto_detection_finds_the_synthetic_mark_and_absence_refuses(tmp_path: Path) -> None:
    logo = write_logo(tmp_path / "logo.png")
    video = write_clip(tmp_path / "clip.mp4", bright=True, mark=True)
    receipt = run_mod.composite_logo(domain_for(logo, detect=True),
                                     request(tmp_path, video, logo, seed_frame=None, seed_box=None))
    seed = receipt["seed"]
    assert seed["source"] == "auto" and seed["detection"]["agreement"] >= 0.5
    rect = seed["logo_rect_xywh"]
    assert detect_mod.iou(tuple(rect), (SEED_BOX[0] + 5 + seed["frame"], SEED_BOX[1] + 5, 20, 26)) > 0.6
    assert seed["detect_config"]["min_score"] == 0.15
    plain = write_clip(tmp_path / "plain.mp4", bright=True)
    with pytest.raises(detect_mod.SeedBoxError) as caught:
        run_mod.composite_logo(domain_for(logo, detect=True),
                               request(tmp_path, plain, logo, out=tmp_path / "out2" / "x.mp4", seed_frame=None, seed_box=None))
    assert caught.value.code == detect_mod.NOT_FOUND and not (tmp_path / "out2").exists()
    with pytest.raises(Refused, match="SEED_BOX_REQUIRED"):
        run_mod.composite_logo(domain_for(logo), request(tmp_path, plain, logo, out=tmp_path / "out3" / "x.mp4",
                                                          seed_frame=None, seed_box=None))


def test_cli_runs_and_reports_refusals_with_exit_1(tmp_path: Path, monkeypatch, capsys) -> None:
    video = write_clip(tmp_path / "clip.mp4")
    logo = write_logo(tmp_path / "logo.png")
    monkeypatch.setattr(cli_mod, "load_domain", lambda name: domain_for(logo) if name == "test_live" else CARTOON)
    argv = ["logo", "--domain", "test_live", "--video", str(video), "--logo", str(logo), "--out", str(tmp_path / "o" / "c.mp4"),
            "--seed-box", ",".join(map(str, SEED_BOX)), "--track-window", "256", "--thread-rgb", "50,55,103",
            "--strip-frames", "2,12,20"]
    assert cli_mod.main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True and summary["gates"] == {"track": True, "edge": True, "audio": "none"}
    assert summary["outputs"]["video"] == sha256_file(tmp_path / "o" / "c.mp4")
    assert cli_mod.main([*argv[:2], "jenniejoy_cartoon_3d", *argv[3:]]) == 1
    err = json.loads(capsys.readouterr().err)
    assert err["ok"] is False and NOT_ENABLED in err["error"]
    fresh_out = [*argv[:8], str(tmp_path / "o2" / "c.mp4"), *argv[9:]]   # write-once would fire first on the old --out
    assert cli_mod.main(fresh_out + ["--logo-sha256", "d" * 64]) == 1
    assert SHA_MISMATCH in json.loads(capsys.readouterr().err)["error"] and not (tmp_path / "o2").exists()
    assert cli_mod.main([*argv, "--seed-frame", "3"]) == 1  # second run: write-once refusal (output exists)
    assert hashlib.sha256((tmp_path / "o" / "c.mp4").read_bytes()).hexdigest() == summary["outputs"]["video"]
