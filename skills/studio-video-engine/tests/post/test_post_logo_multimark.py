"""Nhiều mark mỗi shot trên clip tổng hợp (ffmpeg + OpenCV, CPU): áp riêng từng mark, mark hỏng cổng bị bỏ và ghi,
cổng domain/sha, audio copy, write-once. Không chạm asset sản xuất."""
from __future__ import annotations

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
from engine.post.logo import multimark as mm
from engine.post.logo.edgecheck import EdgeGateError
from engine.post.logo.marks import MANIFEST_INVALID, load_variant
from engine.post.logo.policy import ASSET_INVALID, NOT_ENABLED, SHA_MISMATCH, logo_policy
from engine.post.logo.video_io import FrameWriter, VideoInfo, iter_frames, probe

FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="CPU integration needs ffmpeg/ffprobe on PATH")

SIZE, PATCH, N_FRAMES, PATCH_XY = 256, 150, 24, (40, 40)
BOX_A = [100, 97, 30, 36]      # on the textured patch
BOX_C = [135, 110, 24, 24]     # on the textured patch, apart from A
BOX_B = [110, 215, 24, 24]     # flat grey background, ring clear of the patch (rows > 190): nothing to track
CARTOON = read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json")


def clip(path: Path, *, audio: bool = False) -> Path:
    rng = np.random.default_rng(7)
    noise = rng.integers(40, 220, size=(PATCH, PATCH), dtype=np.uint8)
    tex = np.repeat(cv2.GaussianBlur(noise, (0, 0), 1.2)[..., None], 3, axis=2)
    info = VideoInfo(SIZE, SIZE, 24, 1, N_FRAMES, "h264", "yuv420p", None, None, None, None, None, 0)
    silent = path.with_name("silent-" + path.name) if audio else path
    writer = FrameWriter(silent, silent, info, 10, FFMPEG, preset="ultrafast")
    for i in range(N_FRAMES):
        img = np.full((SIZE, SIZE, 3), 128, np.uint8)
        img[PATCH_XY[1]:PATCH_XY[1] + PATCH, PATCH_XY[0] + i:PATCH_XY[0] + i + PATCH] = tex
        writer.write(img)
    writer.close()
    if audio:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(silent), "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(path)],
                       check=True, capture_output=True, timeout=120)
    return path


def logo_png(path: Path, rgb: tuple[int, int, int]) -> Path:
    img = np.zeros((90, 64, 4), np.uint8)
    img[5:50, 12:52] = (*rgb[::-1], 255)         # icon block
    img[18:37, 24:40] = 0                         # hollow centre
    img[62:76, 2:62] = (200, 90, 20, 255)         # wordmark bar, separated from the icon by a transparent gap
    assert cv2.imwrite(str(path), img)
    return path


def domain(tmp: Path, *, white: bool = True, white_sha: str | None = None) -> dict:
    color, wht = logo_png(tmp / "color.png", (200, 30, 30)), logo_png(tmp / "white.png", (250, 250, 250))
    block = {"enabled": True, "asset": {"path": str(color), "sha256": sha256_file(color)}}
    if white:
        block["assets"] = {"white": {"path": str(wht), "sha256": white_sha or sha256_file(wht)}}
    return {"domain_id": "test_live", "post": {"logo_composite": block}}


def manifest(tmp: Path, marks: list[dict]) -> Path:
    path = tmp / "marks.json"
    path.write_text(json.dumps({"schema": "jjv/post-logo-marks/v1", "marks": marks}), encoding="utf-8")
    return path


def mark(mid: str, box: list[int], **kw) -> dict:
    return {"id": mid, "type": "custom", "asset": "color", "seed_frame": 0, "seed_box": box, **kw}


def req(tmp: Path, video: Path, marks: Path, **kw) -> mm.MarksRequest:
    base = dict(video=video, marks=marks, out=tmp / "out" / "multi.mp4", ffmpeg=FFMPEG, ffprobe=FFPROBE, repo_root=tmp,
                preset="ultrafast", track_window=256, strip_frames=(2, 10, 14, 20), strip_size=96)
    base.update(kw)
    return mm.MarksRequest(**base)


def frame_at(path: Path, idx: int) -> np.ndarray:
    info = probe(path, FFPROBE)
    return list(iter_frames(path, info, FFMPEG, idx + 1))[idx]


def roi_change(src: Path, dst: Path, idx: int, box: list[int], dx: int = 0) -> float:
    x, y, w, h = box
    a, b = frame_at(src, idx)[y:y + h, x + dx:x + dx + w], frame_at(dst, idx)[y:y + h, x + dx:x + dx + w]
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def test_two_good_marks_are_both_applied_with_real_colour_and_audio_copy(tmp_path: Path) -> None:
    video = clip(tmp_path / "clip.mp4", audio=True)
    receipt = mm.composite_marks(domain(tmp_path), req(tmp_path, video, manifest(
        tmp_path, [mark("a", BOX_A), mark("c", BOX_C, asset="n-only")])))
    out = tmp_path / "out" / "multi.mp4"
    assert receipt["marks_applied"] == ["a", "c"] and receipt["marks_skipped"] == []
    assert receipt["gates"]["audio"]["packets_equal"] is True
    assert receipt["outputs"]["video"]["sha256"] == sha256_file(out)
    assert roi_change(video, out, 10, BOX_A, dx=10) > 4 and roi_change(video, out, 10, BOX_C, dx=10) > 4
    red = frame_at(out, 10)[BOX_A[1] + 9:BOX_A[1] + 16, BOX_A[0] + 10 + 6:BOX_A[0] + 10 + 10].reshape(-1, 3).mean(axis=0)
    assert red[2] > red[0] + 40, red     # the composited icon is red (BGR), not the old thread colour
    for name in ("multi_strip_1to1.png", "multi_strip_1to1_a.png", "multi_strip_1to1_c.png"):
        assert (tmp_path / "out" / name).is_file()
    with pytest.raises(Refused, match="overwrite"):
        mm.composite_marks(domain(tmp_path), req(tmp_path, video, manifest(tmp_path, [mark("a", BOX_A)])))


def test_a_mark_that_fails_its_gate_is_skipped_and_the_others_still_apply(tmp_path: Path) -> None:
    video = clip(tmp_path / "clip.mp4")
    receipt = mm.composite_marks(domain(tmp_path), req(tmp_path, video, manifest(
        tmp_path, [mark("a", BOX_A), mark("flat", BOX_B)])))
    out = tmp_path / "out" / "multi.mp4"
    assert receipt["marks_applied"] == ["a"]
    assert [s["id"] for s in receipt["marks_skipped"]] == ["flat"]
    assert receipt["marks_skipped"][0]["code"] == "TRAILING_LOSS"
    skipped = [m for m in receipt["marks"] if m["status"] == "skipped"][0]
    assert skipped["id"] == "flat" and skipped["message"]
    assert roi_change(video, out, 10, BOX_A, dx=10) > 4
    assert roi_change(video, out, 10, BOX_B) < 8          # the skipped mark left its area alone (compression noise only)


def test_every_mark_failing_publishes_nothing(tmp_path: Path) -> None:
    video = clip(tmp_path / "clip.mp4")
    with pytest.raises(Refused, match=mm.NO_MARK_APPLIED):
        mm.composite_marks(domain(tmp_path), req(tmp_path, video, manifest(tmp_path, [mark("flat", BOX_B)])))
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_edge_band_failure_is_per_mark_and_re_encodes_without_it(tmp_path: Path, monkeypatch) -> None:
    video = clip(tmp_path / "clip.mp4")
    real, calls = mm.edge_gate, {"n": 0}

    def flaky(results, slack):
        calls["n"] += 1
        if calls["n"] == 1:                                # the first mark evaluated in the first pass fails
            raise EdgeGateError("synthetic edge failure", {"failing_frames": [2]})
        return real(results, slack)

    monkeypatch.setattr(mm, "edge_gate", flaky)
    receipt = mm.composite_marks(domain(tmp_path), req(tmp_path, video, manifest(
        tmp_path, [mark("a", BOX_A), mark("c", BOX_C)])))
    assert receipt["marks_applied"] == ["c"] and receipt["marks_skipped"] == [{"id": "a", "code": "EDGE_BAND_FAIL"}]
    out = tmp_path / "out" / "multi.mp4"
    assert roi_change(video, out, 10, BOX_C, dx=10) > 4 and roi_change(video, out, 10, BOX_A, dx=10) < 8


def test_gates_refuse_before_the_video_is_touched(tmp_path: Path) -> None:
    missing = tmp_path / "nope.mp4"
    ok = manifest(tmp_path, [mark("a", BOX_A)])
    with pytest.raises(Refused, match=NOT_ENABLED):
        mm.composite_marks(CARTOON, req(tmp_path, missing, ok))
    white = manifest(tmp_path, [mark("a", BOX_A, asset="white")])
    with pytest.raises(Refused, match=ASSET_INVALID):                    # variant the domain does not declare
        mm.composite_marks(domain(tmp_path, white=False), req(tmp_path, missing, white))
    with pytest.raises(Refused, match=SHA_MISMATCH):
        mm.composite_marks(domain(tmp_path, white_sha="d" * 64), req(tmp_path, missing, white))
    bad = manifest(tmp_path, [{"id": "a", "type": "custom", "asset": "color"}])   # no measured seed_box
    with pytest.raises(Refused, match=MANIFEST_INVALID):
        mm.composite_marks(domain(tmp_path), req(tmp_path, missing, bad))
    dup = manifest(tmp_path, [mark("a", BOX_A), mark("a", BOX_C)])
    with pytest.raises(Refused, match=MANIFEST_INVALID):
        mm.composite_marks(domain(tmp_path), req(tmp_path, missing, dup))
    assert not (tmp_path / "out").exists()


def test_variants_resolve_and_white_asset_is_pinned(tmp_path: Path) -> None:
    pol = logo_policy(domain(tmp_path))
    color, n_only, white = (load_variant(pol, v, tmp_path) for v in ("color", "n-only", "white"))
    assert n_only.alpha.shape[0] < color.alpha.shape[0] and color.alpha.shape[0] == 71   # icon rows only vs icon+wordmark
    assert float(np.median(white.bgr[white.alpha > 0.9])) > 200 and color.sha256 != white.sha256


def test_real_domain_declares_the_white_variant_and_it_hashes() -> None:
    live = read_json(SKILL_ROOT / "domains" / "newtecons_live_action.json")
    pol = logo_policy(live)
    root = SKILL_ROOT.parents[2]
    for variant in ("color", "n-only", "white"):
        asset = load_variant(pol, variant, root)
        assert asset.alpha.shape[0] > 50 and asset.sha256 in (pol.asset_sha256, pol.variants["white"]["sha256"])


def test_cli_refuses_marks_mixed_with_a_single_seed(tmp_path: Path, capsys) -> None:
    code = cli_mod.main(["logo", "--domain", "newtecons_live_action", "--video", str(tmp_path / "x.mp4"), "--out",
                         str(tmp_path / "o.mp4"), "--marks", str(tmp_path / "m.json"), "--seed-box", "1,2,30,30"])
    assert code != 0 and "--marks takes seeds" in capsys.readouterr().err


def test_perspective_quad_in_the_manifest_is_parsed_and_bad_quads_refused(tmp_path: Path) -> None:
    from engine.post.logo.marks import load_manifest
    good = [[100, 97], [130, 100], [128, 133], [101, 131]]
    marks, _ = load_manifest(manifest(tmp_path, [mark("a", BOX_A, quad=good)]))
    assert marks[0].quad is not None and len(marks[0].quad) == 4
    for bad in ([[0, 0], [10, 0], [0, 10], [10, 10]], [[0, 0], [10, 0], [10, 10]], [[0, 0], [1, 0], [2, 0], [3, 0]]):
        with pytest.raises(Refused, match=MANIFEST_INVALID):
            load_manifest(manifest(tmp_path, [mark("a", BOX_A, quad=bad)]))


def test_quad_mark_is_applied_end_to_end(tmp_path: Path) -> None:
    video = clip(tmp_path / "clip.mp4")
    quad = [[101, 99], [129, 97], [131, 131], [100, 133]]
    receipt = mm.composite_marks(domain(tmp_path), req(tmp_path, video, manifest(tmp_path, [mark("a", BOX_A, quad=quad)])))
    assert receipt["marks_applied"] == ["a"] and receipt["marks"][0]["seed_logo_quad"][0] == [101.0, 99.0]


def _fake_tracks(n: int, held: set[int]):
    from engine.post.logo.tracker import FrameTrack
    return [FrameTrack(i, np.eye(3), "held" if i in held else "tracked", 1.0, 20, 20, 0, 1.0) for i in range(n)]


def _info() -> VideoInfo:
    return VideoInfo(256, 256, 24, 1, 40, "h264", "yuv420p", None, None, None, None, None, 0)


def test_partial_mark_draws_only_on_the_valid_run_and_fades_at_the_ends() -> None:
    from engine.post.logo.marks import parse_mark
    mk = parse_mark({"id": "c", "type": "collar", "seed_box": BOX_C, "seed_frame": 10, "partial": True,
                     "fade_frames": 4, "min_run": 8}, 0)
    quads = [np.array([[100, 100], [120, 100], [120, 120], [100, 120]], float)] * 40
    w = mm._run_weights(_fake_tracks(40, held=set(range(25, 40)) | {3}), [], quads, _info(), mk)
    assert w[:4] == [0.0] * 4 and w[3] == 0.0                    # held frame 3 is outside the run containing the seed
    assert w[10] == 1.0 and w[16] == 1.0
    assert 0 < w[24] < w[22] < 1.0 and w[25] == 0.0 and w[39] == 0.0   # fades out toward the first bad frame, then nothing
    assert w[4] > 0 and w[4] < 1.0                              # run starts after the held frame: fade-in at the left end
    off = [np.array([[-5, 100], [20, 100], [20, 120], [-5, 120]], float)] * 12 + quads[12:]   # logo leaves the frame at f0-11
    from dataclasses import replace
    w2 = mm._run_weights(_fake_tracks(40, set()), [], off, _info(), replace(mk, seed_frame=20))
    assert w2[:12] == [0.0] * 12 and 0 < w2[12] < 1.0 and w2[20] == 1.0


def test_partial_mark_with_too_short_a_run_is_refused_by_its_own_gate() -> None:
    from engine.post.logo.marks import parse_mark
    from engine.post.logo.tracker import TrackGateError
    mk = parse_mark({"id": "c", "type": "collar", "seed_box": BOX_C, "seed_frame": 10, "partial": True, "min_run": 12}, 0)
    quads = [np.array([[100, 100], [120, 100], [120, 120], [100, 120]], float)] * 40
    with pytest.raises(TrackGateError) as err:
        mm._run_weights(_fake_tracks(40, held=set(range(0, 40)) - set(range(8, 14))), [], quads, _info(), mk)
    assert err.value.code == "TRACK_RUN_TOO_SHORT"
