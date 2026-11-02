"""The four stems (dialogue, music, sfx, mix), all exactly the picture length in samples.

Dialogue is NOT filtered: the original PCM16 samples of each row's WAV are copied with numpy at the sample offset
``segment.start_f * rate/fps + round(at_s * rate)`` (no resample, no mixdown, no millisecond rounding) and the receipt
proves, per row, ``stem_slice_equals_wav``.  Music and SFX are measured-gain beds ducked by the dialogue stem.
Refusal ``EDL_AUDIO_FORMAT``: a dialogue file that is not a ``.wav`` PCM16 stereo file at the domain sample rate.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..core.io import sha256_file
from .edl import abs_path, refuse, sfx_offset_samples
from .proc import Runner, run_cmd, volume_mean_db

EDL_AUDIO_FORMAT = "EDL_AUDIO_FORMAT"


def read_pcm16_stereo(path: Path, label: str, rate: int) -> np.ndarray:
    """All samples of a PCM16 stereo WAV at ``rate`` as an (n, 2) int16 array; anything else is EDL_AUDIO_FORMAT."""
    try:
        with wave.open(str(path), "rb") as handle:
            found = (handle.getframerate(), handle.getnchannels(), handle.getsampwidth())
            if found != (rate, 2, 2):
                refuse(EDL_AUDIO_FORMAT, f"{label}: {Path(path).name} must be PCM16 {rate} Hz stereo "
                       f"(got {found[0]} Hz, {found[1]} ch, {found[2] * 8} bit)")
            return np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").reshape(-1, 2)
    except (wave.Error, EOFError) as error:
        refuse(EDL_AUDIO_FORMAT, f"{label}: {Path(path).name} is not a readable PCM WAV ({error})")
    raise AssertionError("unreachable")


def write_pcm16(path: Path, pcm: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(np.ascontiguousarray(pcm, dtype="<i2").tobytes())


def fit_wav(path: Path, samples: int, rate: int) -> None:
    """Pad with silence / trim a PCM16 stem to exactly ``samples`` (= picture length)."""
    pcm = read_pcm16_stereo(path, path.name, rate)
    if len(pcm) != samples:
        fitted = np.zeros((samples, 2), dtype="<i2")
        kept = min(samples, len(pcm))
        fitted[:kept] = pcm[:kept]
        write_pcm16(path, fitted, rate)


def _silence(path: Path, total_s: float, rate: int, ffmpeg: str, runner: Runner) -> None:
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=stereo",
             "-t", f"{total_s:.4f}", "-c:a", "pcm_s16le", path], runner)


def dialogue_stem(edl: Mapping[str, Any], validation: Mapping[str, Any], path: Path, rate: int, fps: int,
                  base: Path) -> list[dict]:
    """Write the dialogue stem by sample copy; return the per-row report with the sample-exact proof."""
    per_frame = rate // fps
    n_total = validation["total_frames"] * per_frame
    starts = {row["id"]: row["start_f"] for row in validation["segments"]}
    buffer = np.zeros((n_total, 2), dtype=np.int32)
    report: list[dict] = []
    placed: list[tuple[dict, np.ndarray, int]] = []
    for dialogue in edl.get("dialogue", []):
        if not dialogue.get("wav"):
            report.append({"id": dialogue.get("id"), "status": "NO_AUDIO", "placeholder": True})
            continue
        wav = abs_path(dialogue["wav"], base)
        if wav.suffix.lower() != ".wav":
            refuse(EDL_AUDIO_FORMAT, f"{dialogue.get('id')}: dialogue wav must be a .wav file, got {wav.name}")
        pcm = read_pcm16_stereo(wav, str(dialogue.get("id")), rate)
        offset = starts[dialogue["segment"]] * per_frame + int(round(float(dialogue.get("at_s", 0)) * rate))
        count = max(0, min(len(pcm), n_total - offset))
        gain = float(dialogue.get("gain_db", 0))
        chunk = pcm[:count].astype(np.int32) if gain == 0 else np.round(pcm[:count] * 10 ** (gain / 20)).astype(np.int32)
        buffer[offset:offset + count] += chunk
        row = {"id": dialogue.get("id"), "source": wav.name, "sha256": sha256_file(wav), "offset_samples": offset,
               "samples": len(pcm), "tail_trimmed_samples": len(pcm) - count, "gain_db": gain,
               "placeholder": bool(dialogue.get("placeholder"))}
        report.append(row)
        placed.append((row, pcm, count))
    write_pcm16(path, np.clip(buffer, -32768, 32767).astype(np.int16), rate)
    written = read_pcm16_stereo(path, "dialogue stem", rate)
    for row, pcm, count in placed:   # samples shared with a neighbouring WAV's tail are excluded and counted
        low, high = row["offset_samples"], row["offset_samples"] + count
        shared = np.zeros(count, dtype=bool)
        for other, _pcm, other_count in placed:
            if other is not row:
                o_low, o_high = max(low, other["offset_samples"]), min(high, other["offset_samples"] + other_count)
                if o_high > o_low:
                    shared[o_low - low:o_high - low] = True
        same = np.all(written[low:high] == pcm[:count], axis=1)
        row["overlap_samples_excluded"] = int(shared.sum())
        row["stem_slice_equals_wav"] = bool(row["gain_db"] == 0 and np.all(same | shared))
    return report


def build_stems(edl: Mapping[str, Any], validation: Mapping[str, Any], work: Path, policy: Any, base: Path,
                ffmpeg: str, runner: Runner = subprocess.run) -> tuple[dict[str, Path], dict]:
    """The four stems, each fitted to exactly ``total_frames * rate/fps`` samples."""
    rate, fps = policy.sample_rate, policy.fps
    total_s = validation["total_frames"] / fps
    n_total = validation["total_frames"] * (rate // fps)
    starts = {row["id"]: row["start_f"] for row in validation["segments"]}
    audio_format = policy.audio_format()
    ref_db = float(edl.get("dialogue_ref_dbfs", policy.dialogue_ref_dbfs))
    report: dict[str, Any] = {"dialogue": [], "sfx": [], "music": None}

    dialogue_path = work / "stem-dialogue.wav"
    report["dialogue"] = dialogue_stem(edl, validation, dialogue_path, rate, fps, base)

    music_stem = work / "stem-music.wav"
    music = edl.get("music") or {}
    if music.get("source"):
        source = abs_path(music["source"], base)
        offset = float(music.get("source_offset_s", 0))
        mean = volume_mean_db(source, ffmpeg, runner, offset + total_s)
        gain = ref_db + float(music.get("rel_db", -18)) - mean
        graph = (f"[0:a]atrim=start={offset}:duration={total_s:.4f},asetpts=PTS-STARTPTS,{audio_format},"
                 f"volume={gain:.2f}dB,afade=t=in:st=0:d=1.0,afade=t=out:st={total_s - 2.0:.3f}:d=2.0,"
                 f"apad,atrim=0:{total_s:.4f}[m];"
                 "[m][1:a]sidechaincompress=threshold=0.03:ratio=5:attack=150:release=700:makeup=1[o]")
        run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", source, "-i", dialogue_path,
                 "-filter_complex", graph, "-map", "[o]", "-t", f"{total_s:.4f}", "-c:a", "pcm_s16le", music_stem], runner)
        report["music"] = {"source": source.name, "sha256": sha256_file(source), "mean_db": mean,
                           "applied_gain_db": round(gain, 2), "placeholder": bool(music.get("placeholder")),
                           "note": music.get("note")}
    else:
        _silence(music_stem, total_s, rate, ffmpeg, runner)
        report["music"] = {"status": "MISSING"}
    fit_wav(music_stem, n_total, rate)

    inputs, parts, cache = [], [], {}
    for cue in edl.get("sfx", []):
        if not cue.get("source"):
            report["sfx"].append({"cue_id": cue.get("cue_id"), "status": "MISSING"})
            continue
        source = abs_path(cue["source"], base)
        duration = float(cue.get("dur_s", 1.0))
        mean = cache.setdefault(str(source), volume_mean_db(source, ffmpeg, runner))
        gain = ref_db + float(cue.get("gain_vs_dialogue_db", -15)) - mean
        index = len(parts)
        inputs += ["-i", source]
        offset_samples = sfx_offset_samples(cue, starts[cue["segment"]], rate, fps)
        fade_in = float(cue.get("fade_in_s", 0.03))
        fade_out = float(cue.get("fade_out_s", min(duration / 2, 0.6 if cue.get("class") == "ambience" else 0.15)))
        fades: list[str] = []
        if fade_in > 0:
            fades.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if fade_out > 0:
            fades.append(f"afade=t=out:st={max(0.0, duration - fade_out):.6f}:d={fade_out:.6f}")
        fade_chain = ("".join(f"{item}," for item in fades))
        parts.append(f"[{index}:a]atrim=0:{duration},asetpts=PTS-STARTPTS,{audio_format},volume={gain:.2f}dB,"
                     f"{fade_chain}adelay=delays={offset_samples}S:all=1[x{index}]")
        report["sfx"].append({"cue_id": cue.get("cue_id"), "source": source.name, "sha256": sha256_file(source),
                              "position": "at_f" if "at_f" in cue else "at_s",
                              "at_s": offset_samples / rate, "at_f": cue.get("at_f"),
                              "offset_samples": offset_samples, "fade_in_s": fade_in, "fade_out_s": fade_out,
                              "gain_db": round(gain, 2),
                              "placeholder": bool(cue.get("placeholder"))})
    sfx_stem = work / "stem-sfx.wav"
    if parts:
        mix = "".join(f"[x{i}]" for i in range(len(parts)))
        graph = (";".join(parts) + f";{mix}amix=inputs={len(parts)}:normalize=0:duration=longest,"
                 f"apad=whole_dur={total_s:.4f}[s];[s][{len(parts)}:a]sidechaincompress=threshold=0.03:ratio=3:"
                 "attack=100:release=600:makeup=1[o]")
        run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-i", dialogue_path,
                 "-filter_complex", graph, "-map", "[o]", "-t", f"{total_s:.4f}", "-c:a", "pcm_s16le", sfx_stem], runner)
    else:
        _silence(sfx_stem, total_s, rate, ffmpeg, runner)
    fit_wav(sfx_stem, n_total, rate)

    final = work / "stem-mix.wav"
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", dialogue_path, "-i", music_stem, "-i", sfx_stem,
             "-filter_complex", "amix=inputs=3:normalize=0:duration=longest,alimiter=limit=0.89:level=disabled,"
             f"atrim=0:{total_s:.4f}[o]", "-map", "[o]", "-c:a", "pcm_s16le", final], runner)
    fit_wav(final, n_total, rate)
    return {"final": final, "dialogue": dialogue_path, "music": music_stem, "sfx": sfx_stem}, report
