"""Multitrack mux (``remux.tracks``): 4 titled streams, default flag, sample-exact stems, named refusals, legacy path intact."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from audio_fixtures import tone, wav_bytes

from engine.audio import remux, remux_multi
from engine.audio.recipe import load_recipe
from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.seedvr2.seam_media import find_ffmpeg
from engine.voice.wavio import read_wav

FPS = 30
TRACKS = [
    {"stem": "final", "title": "Mix", "codec": "flac", "language": "vie", "default": True},
    {"stem": "dialogue", "title": "Dialogue", "codec": "flac", "language": "vie", "verify_exact": True},
    {"stem": "music", "title": "Music", "codec": "flac", "language": "zxx", "verify_exact": True},
    {"stem": "sfx", "title": "SFX", "codec": "flac", "language": "zxx", "verify_exact": True},
]
CFG = {"audio_codec": "aac", "audio_bitrate": "128k", "tracks": TRACKS}


def tools() -> tuple[str, str]:
    try:
        ff = find_ffmpeg()
    except Exception:
        pytest.skip("ffmpeg not available")
    return ff, str(Path(ff).with_name("ffprobe" + Path(ff).suffix))


@pytest.fixture
def world(tmp_path):
    ff, fp = tools()
    picture = tmp_path / "pic.mp4"
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=30:duration=2", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", str(picture)], check=True)
    stems = {}
    for i, name in enumerate(("final", "dialogue", "music", "sfx")):
        stems[name] = tmp_path / f"{name}.wav"
        stems[name].write_bytes(wav_bytes(tone(2.0, 0.1 + 0.05 * i, freq=220.0 * (i + 1))))
    return ff, fp, picture, stems, tmp_path


def probe(fp: str, path: Path) -> list[dict]:
    done = subprocess.run([fp, "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)["streams"]


def test_four_streams_titles_default_and_dialogue_bit_exact(world) -> None:
    ff, fp, picture, stems, tmp = world
    out = tmp / "film.mkv"
    record = remux_multi.mux_multitrack(ff, fp, picture, stems, out, CFG, FPS)
    audio = [s for s in probe(fp, out) if s["codec_type"] == "audio"]
    assert [s["tags"]["title"] for s in audio] == ["Mix", "Dialogue", "Music", "SFX"]
    assert [bool(s["disposition"]["default"]) for s in audio] == [True, False, False, False]
    assert record["video_untouched"] and len(record["output"]["audio_streams"]) == 4
    dialogue = record["output"]["audio_streams"][1]
    assert dialogue["sample_exact"] and dialogue["decoded_pcm_sha256"] == hashlib.sha256(read_wav(stems["dialogue"]).pcm).hexdigest()
    assert all(r["sample_exact"] for r in record["output"]["audio_streams"])


def test_mp4_container_also_carries_four_streams(world) -> None:
    ff, fp, picture, stems, tmp = world
    out = tmp / "film.mp4"
    remux_multi.mux_multitrack(ff, fp, picture, stems, out, CFG, FPS)
    assert sum(1 for s in probe(fp, out) if s["codec_type"] == "audio") == 4


def test_lossy_track_cannot_claim_exact(world) -> None:
    ff, fp, picture, stems, tmp = world
    lossy = {**CFG, "tracks": [TRACKS[0], {**TRACKS[1], "codec": "aac", "bitrate": "96k"}]}
    with pytest.raises(Refused, match="not sample-exact"):
        remux_multi.mux_multitrack(ff, fp, picture, stems, tmp / "x.mp4", lossy, FPS)
    assert not (tmp / "x.mp4").exists() and not list(tmp.glob(".*tmp*"))


def test_missing_stem_refused(world) -> None:
    ff, fp, picture, stems, tmp = world
    stems["music"].unlink()
    with pytest.raises(Refused, match="stem 'music' is missing"):
        remux_multi.mux_multitrack(ff, fp, picture, stems, tmp / "x.mkv", CFG, FPS)
    assert not (tmp / "x.mkv").exists()


def test_stem_longer_than_picture_refused(world) -> None:
    ff, fp, picture, stems, tmp = world
    stems["sfx"].write_bytes(wav_bytes(tone(3.0, 0.1)))
    with pytest.raises(Refused, match="outrun the picture"):
        remux_multi.mux_multitrack(ff, fp, picture, stems, tmp / "x.mkv", CFG, FPS)


def test_count_mismatch_refused_and_output_removed(world, monkeypatch) -> None:
    ff, fp, picture, stems, tmp = world
    real = remux_multi.probe_streams

    def one_missing(ffprobe, path, runner=subprocess.run):
        data = real(ffprobe, path, runner)
        if Path(path).name.startswith(".") and sum(s["codec_type"] == "audio" for s in data["streams"]) == 4:
            data["streams"] = [s for s in data["streams"] if s["codec_type"] != "audio"][:1] + \
                [s for s in data["streams"] if s["codec_type"] == "audio"][:3]
        return data

    monkeypatch.setattr(remux_multi, "probe_streams", one_missing)
    with pytest.raises(Refused, match="declared 4 audio streams but the film holds 3"):
        remux_multi.mux_multitrack(ff, fp, picture, stems, tmp / "x.mkv", CFG, FPS)
    assert not (tmp / "x.mkv").exists()


def test_exactly_one_default_and_no_overwrite(world) -> None:
    ff, fp, picture, stems, tmp = world
    with pytest.raises(Refused, match="exactly one"):
        remux_multi.mux_multitrack(ff, fp, picture, stems, tmp / "x.mkv", {**CFG, "tracks": TRACKS[1:]}, FPS)
    out = tmp / "film.mkv"
    remux_multi.mux_multitrack(ff, fp, picture, stems, out, CFG, FPS)
    with pytest.raises(Refused, match="refusing to overwrite"):
        remux_multi.mux_multitrack(ff, fp, picture, stems, out, CFG, FPS)


def test_legacy_single_stream_path_unchanged(world) -> None:
    ff, fp, picture, stems, tmp = world
    out = tmp / "legacy.mp4"
    record = remux.mux(ff, fp, picture, stems["final"], out, {"audio_codec": "aac", "audio_bitrate": "128k"}, FPS)
    audio = [s for s in probe(fp, out) if s["codec_type"] == "audio"]
    assert len(audio) == 1 and audio[0]["codec_name"] == "aac" and record["output"]["audio_codec"] == "aac"
    assert "audio_streams" not in record["output"]


def test_ntc_recipe_declares_four_tracks_from_recipe_not_code() -> None:
    data = load_recipe("audio/ntc-mix-cinema-multitrack-v001", "audio-mix", domain=read_json(SKILL_ROOT / "domains" / "newtecons_live_action.json")).data
    assert [t["title"] for t in data["remux"]["tracks"]] == ["Mix", "Dialogue", "Music", "SFX"]
    assert [t["stem"] for t in data["remux"]["tracks"] if t.get("default")] == ["final"]
    legacy = load_recipe("audio/mix-cinema-v001", "audio-mix").data
    assert "tracks" not in legacy["remux"]
