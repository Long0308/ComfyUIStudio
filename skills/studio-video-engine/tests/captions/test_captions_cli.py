"""jjv captions build/burn: receipt, write-once, argv chinh xac (ffmpeg gia), GENERATOR_SPLIT_MISMATCH."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_captions_gate import qualified_config, make_timing, prepare_burn

pytestmark = pytest.mark.usefixtures("qualified_config")

from engine.captions import burn as burn_mod
from engine.captions import cli as cli_mod
from engine.captions.ass import cues_to_ass, cues_to_srt, words_to_cues
from engine.captions.split import SPLIT_MISMATCH, check_split, layout_of
from engine.core.errors import Refused
from engine.core.io import sha256_bytes, sha256_file


def _word(i: int, start: float, end: float, text: str) -> dict:
    return {"index": i, "start_s": start, "end_s": end, "text": text, "raw_text": text}


def timing_doc() -> dict:
    # gap giua tu 3 va 4 = 0.50 s >= 0.40 -> 2 cue; "Tien" o dang NFD de thu chuan hoa NFC
    words = [_word(1, 0.20, 0.50, "Ti\u0065\u0302\u0301n"), _word(2, 0.55, 0.80, "độ"), _word(3, 0.85, 1.10, "gấp"),
             _word(4, 1.60, 1.90, "nhé")]
    return {"fps": 24, "entries": [{"id": "SHOT_X", "start_frame": 0, "audio": {"offset_seconds": 0.0}, "words": words}]}


def write_timing(tmp_path: Path) -> Path:
    return make_timing(tmp_path)


def test_build_writes_ass_srt_receipt_with_hashes(tmp_path: Path) -> None:
    timing = write_timing(tmp_path)
    stem = tmp_path / "out" / "x"
    assert cli_mod.main(["build", "--episode", "TEST", "--timing", str(timing), "--out", str(stem), "--title", "SHOT_X review"]) == 0
    cues = words_to_cues(timing_doc())
    ass_bytes = cues_to_ass(cues, title="SHOT_X review").encode("utf-8")
    assert stem.with_suffix(".ass").read_bytes() == ass_bytes
    assert stem.with_suffix(".srt").read_bytes() == cues_to_srt(cues).encode("utf-8")
    assert b"\r" not in ass_bytes and b"Title: SHOT_X review\n" in ass_bytes
    receipt = json.loads((tmp_path / "out" / "x.captions-receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == "jjv/captions-build-receipt/v1"
    assert receipt["inputs"]["timing"]["sha256"] == sha256_file(timing)
    assert receipt["outputs"]["ass"]["sha256"] == sha256_bytes(ass_bytes)
    assert receipt["outputs"]["srt"]["sha256"] == sha256_file(stem.with_suffix(".srt"))
    assert receipt["highlight"] == "#0B4FD9" and receipt["cue_count"] == 2 and receipt["title_source"] == "explicit"


def test_build_is_write_once(tmp_path: Path) -> None:
    timing = write_timing(tmp_path)
    stem = tmp_path / "x"
    argv = ["build", "--episode", "TEST", "--timing", str(timing), "--out", str(stem)]
    assert cli_mod.main(argv) == 0
    assert cli_mod.main(argv) == 0  # cung byte -> idempotent
    assert cli_mod.main(argv + ["--highlight", "FFCC00"]) == 1  # byte khac -> tu choi, khong ghi de
    assert b"&H00D94F0B" in stem.with_suffix(".ass").read_bytes()


def test_build_refuses_split_mismatch(tmp_path: Path) -> None:
    timing = write_timing(tmp_path)
    cues = words_to_cues(timing_doc())
    layout = layout_of(cues)
    layout["cues"][0]["words"].append(layout["cues"][1]["words"].pop(0))  # cue da luu doi diem tach
    layout_path = tmp_path / "layout.json"
    layout_path.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    assert check_split(cues, layout_of(cues)) is None
    with pytest.raises(Refused, match=SPLIT_MISMATCH):
        check_split(cues, layout)
    assert cli_mod.main(["build", "--episode", "TEST", "--timing", str(timing), "--out", str(tmp_path / "y"), "--layout", str(layout_path)]) == 1
    assert not tmp_path.joinpath("y.ass").exists()


def _inputs(tmp_path: Path):
    video, wav, ass = tmp_path / "v.mp4", tmp_path / "a.wav", tmp_path / "c.ass"
    for path, payload in ((video, b"V"), (wav, b"W"), (ass, b"A")):
        path.write_bytes(payload)
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    return video, wav, ass, fonts


def test_burn_argv_is_exact_and_uses_mock_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    args = prepare_burn(tmp_path, monkeypatch)
    calls = []
    def render(argv):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"RENDER")
        return 0, ""
    args["runner"] = render
    receipt = burn_mod.burn(**args)
    esc = burn_mod.filter_path
    vf = ("scale=1920:-2:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
          f"ass={esc(args['ass'])}:fontsdir={esc(args['fontsdir'])}")
    argv = calls[0]
    assert argv[:-1] == ["ffmpeg", "-hide_banner", "-nostdin", "-n", "-i", str(args["video"]),
                        "-map", "0:v:0", "-map", "0:a", "-vf", vf, "-c:v", "libx264", "-crf", "16",
                        "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart"]
    assert receipt["outputs"]["video"]["sha256"] == sha256_bytes(b"RENDER")
    assert not Path(argv[-1]).exists()


def test_filter_path_escapes_windows_drive_and_quotes() -> None:
    assert burn_mod.filter_path(Path("J:/a b/it's.ass")) == "'J\\:/a b/it\\'s.ass'"


def test_burn_refuses_existing_output_and_missing_inputs(tmp_path: Path) -> None:
    video, wav, ass, fonts = _inputs(tmp_path)
    out = tmp_path / "o.mp4"
    out.write_bytes(b"x")

    def never(argv):
        raise AssertionError("ffmpeg must not run")

    with pytest.raises(Refused, match="exists"):
        burn_mod.burn(video=video, ass=ass, wav=wav, out=out, fontsdir=fonts, ffmpeg="FF", fps=24, runner=never)
    with pytest.raises(Refused, match="not found"):
        burn_mod.burn(video=tmp_path / "nope.mp4", ass=ass, wav=wav, out=tmp_path / "n.mp4", fontsdir=fonts, ffmpeg="FF",
                      fps=24, runner=never)
    with pytest.raises(Refused, match="fontsdir"):
        burn_mod.burn(video=video, ass=ass, wav=wav, out=tmp_path / "m.mp4", fontsdir=tmp_path / "nofonts", ffmpeg="FF",
                      fps=24, runner=never)


def test_burn_failed_ffmpeg_leaves_no_output(tmp_path: Path, monkeypatch) -> None:
    args = prepare_burn(tmp_path, monkeypatch)
    def failing(argv):
        Path(argv[-1]).write_bytes(b"half")
        return 1, "boom"
    args["runner"] = failing
    with pytest.raises(Exception, match="boom"):
        burn_mod.burn(**args)
    assert not args["out"].exists() and not list(tmp_path.glob("*.partial.mp4"))
