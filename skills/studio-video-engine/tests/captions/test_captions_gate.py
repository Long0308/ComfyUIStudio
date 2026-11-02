"""Receipt/recipe and audio preservation regression tests; no GPU or real production assets."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.captions import burn as burn_mod, cli as cli_mod, gate as gate_mod
from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file

RECIPE = "timing/ntc-vi-words-v001"
REAL_FACTS, REAL_PACKETS = burn_mod.media_facts, burn_mod.audio_packets


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def make_timing(folder):
    recipe = {"id": RECIPE, "sha256": sha256_file(SKILL_ROOT / "recipes" / (RECIPE + ".json"))}
    words = [{"index": i, "text": t, "raw_text": t, "start_s": a, "end_s": b}
             for i, t, a, b in [(1, "Tie\u0302\u0301n", .2, .5), (2, "độ", .55, .8),
                                (3, "gấp", .85, 1.1), (4, "nhé", 1.6, 1.9)]]
    timing = dump(folder / "WORD-TIMING.json", {"episode_id": "TEST", "fps": 24, "recipe": recipe,
                 "entries": [{"id": "SHOT_X", "start_frame": 0, "audio": {"offset_seconds": 0},
                              "word_count": len(words), "words": words}]})
    dump(folder / "timing-receipt.json", {"schema": "jjv/timing-words-receipt/v1", "ok": True,
         "verdict": "PASS", "inputs": {"recipe": recipe, "wavs": []},
         "outputs": {"WORD-TIMING.json": sha256_file(timing)}})
    return timing


@pytest.fixture
def qualified_config(monkeypatch):
    domain = read_json(SKILL_ROOT / "domains/newtecons_live_action.json")
    config = SimpleNamespace(domain=domain, episode={"episode_id": "TEST"})
    monkeypatch.setattr(gate_mod, "resolve_episode", lambda episode: config)
    return config


def prepare_burn(folder, monkeypatch):
    timing = make_timing(folder)
    assert cli_mod.main(["build", "--episode", "TEST", "--timing", str(timing),
                         "--out", str(folder / "c")]) == 0
    video, wav = folder / "v.mp4", folder / "a.wav"
    video.write_bytes(b"V")
    wav.write_bytes(b"W")
    fonts = folder / "fonts"
    fonts.mkdir()
    font = fonts / "arial.ttf"
    font.write_bytes(b"font-fixture")
    mix = dump(folder / "mix-receipt.json", {"schema": "jjv/audio-mix/v1", "episode_id": "TEST", "verdict": "PASS",
               "stems": {"final": {"sha256": sha256_file(wav)}},
               "mux": {"output": {"sha256": sha256_file(video)}, "mix_sha256": sha256_file(wav)}})
    monkeypatch.setattr(burn_mod, "media_facts", lambda *a: {"frames": 48, "duration_s": 2., "audio_streams": 2})
    monkeypatch.setattr(burn_mod, "audio_packets", lambda *a: [
        {"stream": 0, "packets": 20, "sha256": "a" * 64}, {"stream": 1, "packets": 21, "sha256": "b" * 64}])

    def render(argv):
        Path(argv[-1]).write_bytes(b"RENDER")
        return 0, ""

    return dict(video=video, wav=wav, ass=folder / "c.ass", out=folder / "final.mp4", fontsdir=fonts,
                ffmpeg="ffmpeg", fps=24, episode="TEST", timing=timing, subtitles=folder / "c.captions-receipt.json",
                font=font, audio_receipt=mix, runner=render)


def test_build_allowed_recipe_is_bound_and_write_once(tmp_path, qualified_config):
    timing = make_timing(tmp_path)
    argv = ["build", "--episode", "TEST", "--timing", str(timing), "--out", str(tmp_path / "c")]
    assert cli_mod.main(argv) == 0
    original = (tmp_path / "c.ass").read_bytes()
    assert cli_mod.main(argv) == 0
    receipt = read_json(tmp_path / "c.captions-receipt.json")
    assert receipt["inputs"]["timing"]["recipe"]["id"] == RECIPE
    assert receipt["inputs"]["timing"]["receipt_sha256"] == sha256_file(tmp_path / "timing-receipt.json")
    assert b"&H00D94F0B" in original
    assert cli_mod.main(argv + ["--highlight", "FFCC00"]) == 1
    assert (tmp_path / "c.ass").read_bytes() == original


@pytest.mark.parametrize("mode", ["empty", "missing", "cartoon", "recipe_hash", "receipt_hash", "failed", "episode", "recipe_missing"])
def test_build_refuses_unqualified_before_writing(tmp_path, qualified_config, mode):
    timing = make_timing(tmp_path)
    doc, receipt = read_json(timing), read_json(tmp_path / "timing-receipt.json")
    if mode == "empty":
        qualified_config.domain["timing"]["allowed_recipes"] = []
    elif mode == "missing":
        qualified_config.domain.pop("timing")
    elif mode == "cartoon":
        doc["recipe"]["id"] = "timing/cartoon-preview"
    elif mode == "recipe_hash":
        doc["recipe"]["sha256"] = "0" * 64
    elif mode == "receipt_hash":
        receipt["outputs"]["WORD-TIMING.json"] = "0" * 64
    elif mode == "failed":
        receipt["ok"] = False
    elif mode == "episode":
        doc["episode_id"] = "OTHER"
    else:
        doc.pop("recipe")
    dump(timing, doc)
    dump(tmp_path / "timing-receipt.json", receipt)
    assert cli_mod.main(["build", "--episode", "TEST", "--timing", str(timing), "--out", str(tmp_path / "c")]) == 1
    assert not (tmp_path / "c.ass").exists()


def test_burn_copies_all_audio_and_records_hashes(tmp_path, monkeypatch, qualified_config):
    args = prepare_burn(tmp_path, monkeypatch)
    receipt = burn_mod.burn(**args)
    argv = receipt["argv"]
    assert argv[argv.index("-c:a") + 1] == "copy"
    assert "0:a" in argv and "-af" not in argv and "-shortest" not in argv and argv.count("-i") == 1
    assert receipt["audio_packet_hash_pre"] == receipt["audio_packet_hash_post"]
    assert len(receipt["audio_packet_hash_pre"]) == 2
    for key, path in [("subtitle_sha256", args["subtitles"]), ("ass_sha256", args["ass"]),
                      ("font_sha256", args["font"]), ("word_timing_sha256", args["timing"])]:
        assert receipt[key] == sha256_file(path)
    assert receipt["video_after"]["frames"] == 48 and receipt["final_ready"] is False
    assert read_json(tmp_path / "final.burn-receipt.json")["audio"]["mode"] == "copy"
    with pytest.raises(Refused, match="overwrite"):
        burn_mod.burn(**args)


@pytest.mark.parametrize("mode", ["domain", "ass", "mix", "missing_mix", "packet", "frames"])
def test_burn_refuses_bad_evidence(tmp_path, monkeypatch, qualified_config, mode):
    args = prepare_burn(tmp_path, monkeypatch)
    if mode == "domain":
        qualified_config.domain["timing"]["allowed_recipes"] = []
    elif mode == "ass":
        args["ass"].write_bytes(b"tampered")
    elif mode == "mix":
        args["video"].write_bytes(b"tampered")
    elif mode == "missing_mix":
        args["audio_receipt"] = None
    elif mode == "packet":
        monkeypatch.setattr(burn_mod, "audio_packets", lambda ff, path: [{"sha256": str(path)}])
        monkeypatch.setattr(burn_mod, "media_facts", lambda *a: {"frames": 48, "duration_s": 2., "audio_streams": 1})
    elif mode == "frames":
        monkeypatch.setattr(burn_mod, "media_facts", lambda ff, path: {"frames": 48 if path == args["video"] else 47,
                                                                   "duration_s": 2., "audio_streams": 2})
    with pytest.raises(Refused):
        burn_mod.burn(**args)
    assert not args["out"].exists() and not (tmp_path / "final.burn-receipt.json").exists()
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_silent_candidate_needs_explicit_aac_and_timing_wav(tmp_path, monkeypatch, qualified_config):
    args = prepare_burn(tmp_path, monkeypatch)
    monkeypatch.setattr(burn_mod, "media_facts", lambda ff, p: {"frames": 48, "duration_s": 2.,
                                                             "audio_streams": 0 if p == args["video"] else 1})
    monkeypatch.setattr(burn_mod, "audio_packets", lambda ff, p: [{"stream": 0, "packets": 1, "sha256": "a" * 64}])
    with pytest.raises(Refused, match="explicit"):
        burn_mod.burn(**args)
    args["allow_aac_from_wav"] = True
    with pytest.raises(Refused, match="not bound"):
        burn_mod.burn(**args)
    path = tmp_path / "timing-receipt.json"
    receipt = read_json(path)
    receipt["inputs"]["wavs"] = [{"sha256": sha256_file(args["wav"])}]
    dump(path, receipt)
    # Rebuild to bind the new timing receipt hash; ASS/SRT bytes stay identical.
    subtitle = read_json(args["subtitles"])
    subtitle["inputs"]["timing"]["receipt_sha256"] = sha256_file(path)
    dump(args["subtitles"], subtitle)
    result = burn_mod.burn(**args)
    assert result["audio"]["mode"] == "aac" and "silent-picture" in result["audio"]["reason"]
    assert result["final_ready"] is False and "apad" in result["argv"]


def test_packet_hash_reader_keeps_streams_separate(monkeypatch):
    monkeypatch.setattr(burn_mod, "_capture", lambda a: "#header\n0, 0, 0, 1, 9, " + "a" * 64 + ", S=1, 10, " + "d" * 64 +
                        "\n1, 0, 0, 1, 9, " + "b" * 64 + "\n0, 1, 1, 1, 9, " + "c" * 64)
    rows = burn_mod.audio_packets("ffmpeg", Path("x.mp4"))
    assert [r["packets"] for r in rows] == [2, 1]
    assert rows[0]["sha256"] != rows[1]["sha256"]


@pytest.mark.parametrize("fps", [0, -1])
def test_invalid_fps_refused_before_render(tmp_path, monkeypatch, qualified_config, fps):
    args = prepare_burn(tmp_path, monkeypatch)
    args["fps"] = fps
    with pytest.raises(Refused, match="fps"):
        burn_mod.burn(**args)


@pytest.mark.parametrize("target,key", [("timing-receipt.json", "inputs"),
                                       ("c.captions-receipt.json", "outputs"), ("mix-receipt.json", "mux")])
def test_malformed_nested_receipts_refused(tmp_path, monkeypatch, qualified_config, target, key):
    args = prepare_burn(tmp_path, monkeypatch)
    path = tmp_path / target
    doc = read_json(path)
    doc[key] = None
    dump(path, doc)
    with pytest.raises(Refused, match="object"):
        burn_mod.burn(**args)


def test_real_ffmpeg_two_audio_streams(tmp_path, monkeypatch, qualified_config):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    font_source = Path("C:/Windows/Fonts/arial.ttf")
    if not ffmpeg or not ffprobe or not font_source.is_file():
        pytest.skip("CPU integration needs ffmpeg/ffprobe and Arial font")
    args = prepare_burn(tmp_path, monkeypatch)
    # All media are synthetic; no production clip or GPU is touched.
    with wave.open(str(args["wav"]), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 24000)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=size=160x90:rate=24:duration=0.5",
                    "-i", str(args["wav"]), "-map", "0:v:0", "-map", "1:a:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-c:a", "aac", "-t", "0.5", str(args["video"])], check=True,
                   capture_output=True, timeout=60)
    args["font"].write_bytes(font_source.read_bytes())
    mix = read_json(args["audio_receipt"])
    mix["mux"]["output"]["sha256"] = sha256_file(args["video"])
    mix["mux"]["mix_sha256"] = mix["stems"]["final"]["sha256"] = sha256_file(args["wav"])
    dump(args["audio_receipt"], mix)
    monkeypatch.setattr(burn_mod, "media_facts", REAL_FACTS)
    monkeypatch.setattr(burn_mod, "audio_packets", REAL_PACKETS)
    args.update(ffmpeg=ffmpeg, ffprobe=ffprobe, runner=burn_mod.default_runner)
    result = burn_mod.burn(**args)
    assert result["video_after"]["frames"] == 12
    assert len(result["audio_packet_hash_post"]) == 2
    assert result["audio_packet_hash_post"] == result["audio_packet_hash_pre"]
