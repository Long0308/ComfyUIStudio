"""End-to-end CPU grade: real ffmpeg on a 2 s testsrc clip with a brand patch and a tone track.

Checks: identity LUT keeps frames (PSNR > 45), audio packets unchanged, write-once output + receipt,
before/after stills at the same frame index, domain refusal before any encode.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.post.grade import run as run_mod
from engine.post.grade.cli import load_domain
from engine.post.logo.video_io import iter_frames, probe
from engine.seedvr2.seam_media import find_ffmpeg
import importlib.util


def load_make_lut():
    spec = importlib.util.spec_from_file_location("make_lut_run_test", SKILL_ROOT / "tools" / "make_lut.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FFMPEG = find_ffmpeg(None)
FFPROBE = str(Path(FFMPEG).with_name("ffprobe" + Path(FFMPEG).suffix))
GRADE_DIR = SKILL_ROOT / "recipes" / "grade"


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """2 s, 320x180, 25 fps testsrc, brand-blue and brand-red patches, 440 Hz tone, AAC audio."""
    path = tmp_path_factory.mktemp("clip") / "brand_clip.mp4"
    vf = ("drawbox=x=20:y=20:w=80:h=60:color=0x0B4FD9:t=fill,"
          "drawbox=x=120:y=20:w=80:h=60:color=0xE4302C:t=fill")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-vf", vf,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", "-shortest", str(path)],
                   check=True, capture_output=True)
    return path


def domain_for(name: str, lut: Path) -> dict:
    return {"domain_id": "test_domain",
            "post": {"grade": {"enabled": True, "luts": {name: {
                "path": f"recipes/grade/{name}.cube", "sha256": sha256_file(lut)}}}}}


def request(clip, out, lut, **kw):
    base = dict(video=clip, lut=lut, out=out, ffmpeg=FFMPEG, ffprobe=FFPROBE, crf=18)
    base.update(kw)
    return run_mod.GradeRequest(**base)


def bgr_frames(path):
    info = probe(path, FFPROBE)
    return [f.astype(np.float64) for f in iter_frames(path, info, FFMPEG)]


def yuv_planes(path):
    """Decoded yuv420p frames as (Y, U, V) flat float arrays, one tuple per frame."""
    info = probe(path, FFPROBE)
    w, h = info.width, info.height
    cw, ch = (w + 1) // 2, (h + 1) // 2
    frame = w * h + 2 * cw * ch
    raw = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-i", str(path), "-f", "rawvideo",
                          "-pix_fmt", "yuv420p", "pipe:1"], capture_output=True, check=True).stdout
    planes = []
    for i in range(len(raw) // frame):
        f = np.frombuffer(raw, dtype=np.uint8, count=frame, offset=i * frame).astype(np.float64)
        y_end = w * h
        planes.append((f[:y_end], f[y_end:y_end + cw * ch], f[y_end + cw * ch:]))
    return planes


def psnr(a, b):
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def test_identity_lut_keeps_frames(clip, tmp_path):
    mk = load_make_lut()
    identity = tmp_path / "identity_test.cube"
    mk.write_cube(identity, mk.build_table(
        {"schema": "jjv/grade-look/v1", "name": "identity_test", "domain_id": "test_domain",
         "lift": [0, 0, 0], "gamma": [1, 1, 1], "gain": [1, 1, 1], "warmth": 0.0, "saturation": 1.0,
         "contrast": 1.0, "split": {"shadow_cool": 0.0, "highlight_warm": 0.0}, "brand": [],
         "brand_de_max": 3.0}, 33), 33, "identity_test")
    out = tmp_path / "identity_out.mp4"
    # CRF 0 (lossless x264): a second lossy encode would dominate the measurement; this isolates the colour path.
    receipt = run_mod.grade_video(domain_for("identity_test", identity), request(clip, out, identity, crf=0))
    src, dst = yuv_planes(clip), yuv_planes(out)
    assert len(src) == len(dst) == receipt["inputs"]["video"]["probe"]["nb_frames"]
    # Luma is the gate. U/V are only a regression floor: the source and output both live in 4:2:0, so every
    # chroma sample is an average over a 2x2 luma block; on the hard synthetic edges of testsrc + brand patches
    # that subsampling round trip alone limits U/V PSNR well below luma (measured: luma 45.35 dB, chroma lower).
    y_vals = [psnr(a[0], b[0]) for a, b in zip(src, dst)]
    u_vals = [psnr(a[1], b[1]) for a, b in zip(src, dst)]
    v_vals = [psnr(a[2], b[2]) for a, b in zip(src, dst)]
    assert min(y_vals) > 45.0, f"identity LUT luma (Y) PSNR min {min(y_vals):.2f} dB"
    assert min(u_vals) > 33.0, f"identity LUT U PSNR min {min(u_vals):.2f} dB"
    assert min(v_vals) > 33.0, f"identity LUT V PSNR min {min(v_vals):.2f} dB"


def test_audio_packets_unchanged_and_receipt_complete(clip, tmp_path):
    out = tmp_path / "soft_out.mp4"
    lut = GRADE_DIR / "jenniejoy_soft_v001.cube"
    receipt = run_mod.grade_video(domain_for("jenniejoy_soft_v001", lut), request(clip, out, lut))
    assert receipt["schema"] == run_mod.RECEIPT_SCHEMA
    assert receipt["gates"]["audio"]["mode"] == "copy"
    assert receipt["gates"]["audio"]["packets_equal"] is True
    assert receipt["inputs"]["lut"]["sha256"] == sha256_file(lut)
    assert receipt["outputs"]["video"]["sha256"] == sha256_file(out)
    assert receipt["params"] == {"grain": 0.0, "halation": 0.0, "soften": 0.0}
    assert set(receipt["outputs"]) >= {"video", "before_still", "after_still"}
    for key in ("before_still", "after_still"):
        assert receipt["outputs"][key]["sha256"] == sha256_file(Path(receipt["outputs"][key]["path"]))
    assert receipt["still_frame_index"] == receipt["outputs"]["after_still"]["frame"]
    rec_path = out.with_name(out.stem + ".grade-receipt.json")
    assert json.loads(rec_path.read_text(encoding="utf-8"))["outputs"]["video"]["sha256"] == receipt["outputs"]["video"]["sha256"]


def test_write_once_refuses_second_run(clip, tmp_path):
    out = tmp_path / "once.mp4"
    lut = GRADE_DIR / "jenniejoy_soft_v001.cube"
    run_mod.grade_video(domain_for("jenniejoy_soft_v001", lut), request(clip, out, lut))
    with pytest.raises(Refused, match="refusing to overwrite"):
        run_mod.grade_video(domain_for("jenniejoy_soft_v001", lut), request(clip, out, lut))


def test_refused_before_encode_when_domain_does_not_declare_grade(clip, tmp_path):
    out = tmp_path / "refused.mp4"
    lut = GRADE_DIR / "jenniejoy_soft_v001.cube"
    with pytest.raises(Refused, match="GRADE_NOT_ENABLED"):
        run_mod.grade_video({"domain_id": "test_domain", "post": {}}, request(clip, out, lut))
    assert not out.exists()
    assert not out.with_name(out.stem + ".grade-receipt.json").exists()


def test_refused_for_undeclared_lut(clip, tmp_path):
    out = tmp_path / "undeclared.mp4"
    film = GRADE_DIR / "newtecons_film_v001.cube"
    soft = GRADE_DIR / "jenniejoy_soft_v001.cube"
    with pytest.raises(Refused, match="LUT_NOT_DECLARED"):
        run_mod.grade_video(domain_for("jenniejoy_soft_v001", soft), request(clip, out, film))
    assert not out.exists()


def test_grain_halation_soften_change_pixels_and_are_recorded(clip, tmp_path):
    out = tmp_path / "fx_out.mp4"
    lut = GRADE_DIR / "jenniejoy_soft_v001.cube"
    receipt = run_mod.grade_video(domain_for("jenniejoy_soft_v001", lut),
                                  request(clip, out, lut, grain=0.5, halation=0.3, soften=0.4))
    assert receipt["params"] == {"grain": 0.5, "halation": 0.3, "soften": 0.4}
    chain = receipt["render"]["filter_chain"]
    assert "noise=" in chain and "lut3d=" in chain and "gblur=" in chain
    assert chain.index("noise=") < chain.index("lut3d="), "grain must sit on its own layer BEFORE the LUT"


def test_bad_params_refused(clip, tmp_path):
    lut = GRADE_DIR / "jenniejoy_soft_v001.cube"
    with pytest.raises(Refused):
        run_mod.grade_video(domain_for("jenniejoy_soft_v001", lut),
                            request(clip, tmp_path / "bad.mp4", lut, grain=1.5))


def test_real_domain_files_declare_only_their_own_lut():
    # Each shipped domain enables grade with exactly its own LUT; neither may list the other's.
    from engine.post.grade import policy as p
    expected = {"jenniejoy_cartoon_3d": {"jenniejoy_soft_v001"}, "newtecons_live_action": {"newtecons_film_v001"}}
    for stem, names in expected.items():
        policy = p.grade_policy(load_domain(stem))
        assert set(policy.luts) == names, (stem, set(policy.luts))


def test_relative_out_and_in_are_resolved_and_the_file_is_written(clip, tmp_path, monkeypatch):
    """UAT-R1 fix 2: ffmpeg chạy với cwd=workdir tạm, nên --out/--in tương đối phải được resolve TRƯỚC khi dựng partial."""
    lut = GRADE_DIR / "jenniejoy_soft_v001.cube"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel_in.mp4").write_bytes(Path(clip).read_bytes())
    receipt = run_mod.grade_video(domain_for("jenniejoy_soft_v001", lut),
                                  request(Path("rel_in.mp4"), Path("rel_out.mp4"), lut))
    assert (tmp_path / "rel_out.mp4").is_file() and receipt["outputs"]["video"]["path"] == str((tmp_path / "rel_out.mp4").resolve())
    assert not list(tmp_path.glob(".*.partial.mp4"))
