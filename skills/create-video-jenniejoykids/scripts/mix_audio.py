"""Mix hash-bound WAV sources and measured Foley cues; never generate speech.

Requires NumPy and an existing FFmpeg executable. Paths are relative to the JSON
config unless absolute. Output directories must be new; source files are read only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any
import wave

import numpy as np
from numpy.typing import NDArray

Audio = NDArray[np.float64]
Json = dict[str, Any]
STEMS = ("voice", "music", "ambience", "footsteps", "animal", "props")


def _number(value: Any, label: str, low: float, high: float) -> float:
    try:
        result = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else math.nan
    except OverflowError:
        result = math.nan
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{label}: expected finite number in [{low}, {high}]")
    return result


def _integer(value: Any, label: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f"{label}: expected integer in [{low}, {high}]")
    return value


def _path(value: Any, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty path")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _run(argv: list[str], payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(argv, input=payload, capture_output=True, timeout=600)
    if result.returncode:
        raise ValueError(f"FFmpeg failed ({result.returncode}): {result.stderr.decode('utf-8', errors='replace')[-4000:]}")
    return result


def _json(path: Path, value: Json) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


@dataclass(frozen=True)
class Source:
    path: Path
    digest: str
    rate: int
    frames: int
    channels: int

    @property
    def duration(self) -> float:
        return self.frames / self.rate


class Sources:
    """Read-only hash-bound source registry; recheck all inputs before publication."""

    def __init__(self, base: Path, ffmpeg: str, rate: int) -> None:
        self.base, self.ffmpeg, self.rate = base, ffmpeg, rate
        self.files: dict[Path, Source] = {}

    def bind(self, spec: Json) -> Source:
        path = _path(spec["file"], self.base)
        digest = spec["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("Every source requires its actual SHA256")
        if path in self.files:
            source = self.files[path]
            if digest.lower() != source.digest:
                raise ValueError("Conflicting hashes for one source")
            return source
        if _sha(path) != digest.lower():
            raise ValueError(f"Source hash mismatch: {path.name}")
        with wave.open(str(path), "rb") as stream:
            if stream.getcomptype() != "NONE" or stream.getnchannels() not in (1, 2) or stream.getsampwidth() not in (2, 3, 4):
                raise ValueError("Input must be mono/stereo integer PCM16/24/32 WAV")
            source = Source(path, digest.lower(), stream.getframerate(), stream.getnframes(), stream.getnchannels())
        if source.frames <= 0 or source.rate <= 0:
            raise ValueError("Empty or invalid source WAV")
        self.files[path] = source
        return source

    def decode(self, source: Source, offset: float, duration: float) -> Audio:
        if offset < 0 or duration <= 0 or offset + duration > source.duration + 1 / source.rate:
            raise ValueError("Source slice outside WAV")
        result = _run([self.ffmpeg, "-v", "error", "-xerror", "-i", str(source.path), "-ss", f"{offset:.12f}",
                       "-t", f"{duration:.12f}", "-map", "0:a:0", "-ac", "2", "-ar", str(self.rate), "-f", "f64le", "-"])
        samples = np.frombuffer(result.stdout, dtype="<f8")
        if len(samples) % 2 or not np.isfinite(samples).all():
            raise ValueError("Invalid decoded audio")
        samples = samples.reshape(-1, 2).copy()
        expected = round(duration * self.rate)
        if abs(len(samples) - expected) > 1:
            raise ValueError("Truncated source or decoded duration mismatch")
        return samples[:expected] if len(samples) >= expected else np.pad(samples, ((0, 1), (0, 0)))

    def verify(self) -> None:
        for source in self.files.values():
            if _sha(source.path) != source.digest:
                raise ValueError("Source changed during mix; output is unaccepted")


def _gain(spec: Json, samples: Audio) -> Audio:
    gain = 10 ** (_number(spec.get("gain_db", 0), "gain_db", -120, 24) / 20)
    pan = _number(spec.get("pan", 0), "pan", -1, 1)
    angle = (pan + 1) * math.pi / 4
    return samples * np.array([math.cos(angle), math.sin(angle)]) * math.sqrt(2) * gain


def _speech(config: Json, duration: float) -> list[tuple[float, float]]:
    guards = config.get("speech_guard", {})
    before = _number(guards.get("before_seconds", .15), "speech guard", 0, 1)
    after = _number(guards.get("after_seconds", .20), "speech guard", 0, 1)
    intervals: list[tuple[float, float]] = []
    previous = 0.0
    lines = config["speech"]
    if not isinstance(lines, list) or not lines:
        raise ValueError("Explicit speech intervals are required")
    for line in lines:
        start = _number(line["start_seconds"], "speech start", 0, duration)
        end = _number(line["end_seconds"], "speech end", 0, duration)
        if start >= end or start < previous:
            raise ValueError("Speech must be positive, ordered and nonoverlapping")
        intervals.append((max(0, start - before), min(duration, end + after)))
        previous = end
    return intervals


def _duck(length: int, rate: int, intervals: list[tuple[float, float]], db: float, fade: float) -> Audio:
    envelope = np.ones(length)
    for start, end in intervals:
        envelope[round(start * rate):round(end * rate)] = 10 ** (db / 20)
    radius = round(fade * rate)
    if radius:
        padded = np.pad(envelope, (radius, radius), mode="edge")
        cumulative = np.concatenate(([0.0], np.cumsum(padded)))
        envelope = (cumulative[2 * radius + 1:] - cumulative[:-(2 * radius + 1)]) / (2 * radius + 1)
    return envelope[:, None]


def _event_frame(cue: Json, total: int) -> int:
    if cue.get("placement_status") != "measured":
        raise ValueError("Event placement must be explicitly measured")
    global_frame = cue.get("measured_global_frame")
    local_frame = cue.get("measured_local_frame")
    if global_frame is None and local_frame is None:
        raise ValueError("Missing measured contact/event frame; placeholders are prohibited")
    derived = None
    if local_frame is not None:
        derived = _integer(local_frame, "local frame", 0, total - 1) + _integer(cue.get("scene_start_global_frame"), "scene start", 0, total - 1)
    frame = _integer(global_frame if global_frame is not None else derived, "global frame", 0, total - 1)
    if derived is not None and frame != derived:
        raise ValueError("Local/global contact frames disagree")
    return frame


def _slice(spec: Json, sources: Sources) -> tuple[Source, float, float, Audio]:
    source = sources.bind(spec)
    offset = _number(spec.get("offset_seconds", 0), "source offset", 0, source.duration)
    duration = _number(spec.get("duration_seconds", source.duration - offset), "source duration", 1 / sources.rate, 600)
    return source, offset, duration, sources.decode(source, offset, duration)


def _add_cues(config: Json, sources: Sources, stems: dict[str, Audio], guards: list[tuple[float, float]]) -> list[Json]:
    clock: list[Json] = []
    rate, fps, duration = sources.rate, config["fps"], config["duration_seconds"]
    total = round(duration * fps)
    ids: set[str] = set()
    for cue in config.get("cues", []):
        label, category = cue["id"], cue["category"]
        if not isinstance(label, str) or not label or label in ids or category not in STEMS[3:]:
            raise ValueError("Cue IDs must be unique and category footsteps/animal/props")
        ids.add(label)
        frame = _event_frame(cue, total)
        source, offset, seconds, samples = _slice(cue, sources)
        transient = _number(cue["transient_seconds"], "source transient", offset, offset + seconds)
        if transient >= offset + seconds:
            raise ValueError("Transient must fall inside selected source slice")
        hit_sample = round(frame / fps * rate)
        begin = hit_sample - round((transient - offset) * rate)
        end = begin + len(samples)
        if begin < 0 or end > len(stems[category]):
            raise ValueError("Whole event cue must fit timeline; no silent truncation")
        conflicts = any(begin / rate < stop and end / rate > start for start, stop in guards)
        policy = cue.get("speech_policy", "attenuate" if category == "footsteps" else "avoid")
        if policy not in ("avoid", "attenuate") or category != "footsteps" and policy != "avoid":
            raise ValueError("Only footsteps may attenuate under speech")
        if conflicts and policy == "avoid":
            raise ValueError(f"Cue {label}: speech guard conflict")
        stems[category][begin:end] += _gain(cue, samples)
        clock.append({"id": label, "category": category, "file": str(source.path), "sha256": source.digest,
                      "global_event_frame": frame, "event_seconds": frame / fps, "source_transient_seconds": transient,
                      "source_offset_seconds": offset, "start_sample": begin, "end_sample_exclusive": end,
                      "aligned_hit_sample": hit_sample, "speech_conflict": conflicts, "speech_policy": policy,
                      "evidence": cue.get("evidence", {}), "gain_db": cue.get("gain_db", 0), "pan": cue.get("pan", 0)})
    return clock


def _ambient_samples(samples: Audio, target: int, crossfade: int) -> Audio:
    if len(samples) >= target:
        return samples[:target]
    if crossfade < 1 or crossfade * 2 >= len(samples):
        raise ValueError("Loop requires positive crossfade shorter than half source")
    result = np.zeros((target, 2))
    result[:len(samples)] = samples
    filled = len(samples)
    weights = np.linspace(0, 1, crossfade)[:, None]
    while filled < target:
        overlap = min(crossfade, filled, target - (filled - crossfade))
        start = filled - overlap
        result[start:filled] = result[start:filled] * (1 - weights[:overlap]) + samples[:overlap] * weights[:overlap]
        count = min(len(samples) - overlap, target - filled)
        result[filled:filled + count] = samples[overlap:overlap + count]
        filled += count
    return result


def _add_ambience(config: Json, sources: Sources, stem: Audio) -> list[Json]:
    records: list[Json] = []
    seen: set[str] = set()
    for spec in config.get("ambience", []):
        label = spec["id"]
        if not isinstance(label, str) or not label or label in seen or spec.get("placement_status") != "ambient_no_contact":
            raise ValueError("Ambience needs unique ID and ambient_no_contact declaration")
        seen.add(label)
        source = sources.bind(spec)
        start = _number(spec["start_seconds"], "ambience start", 0, config["duration_seconds"])
        duration = _number(spec["duration_seconds"], "ambience duration", 1 / sources.rate, config["duration_seconds"])
        offset = _number(spec.get("offset_seconds", 0), "ambience source offset", 0, source.duration)
        if start + duration > config["duration_seconds"] + 1e-9:
            raise ValueError("Ambience exceeds timeline")
        available = source.duration - offset
        looping = spec.get("loop", False)
        if not isinstance(looping, bool) or available < duration and not looping:
            raise ValueError("Short ambience requires explicit loop=true")
        samples = sources.decode(source, offset, min(available, duration))
        crossfade = round(_number(spec.get("loop_crossfade_seconds", .1), "loop crossfade", .001, 5) * sources.rate)
        samples = _ambient_samples(samples, round(duration * sources.rate), crossfade)
        fade = min(round(.03 * sources.rate), len(samples) // 2)
        if fade > 0:
            samples[:fade] *= np.linspace(0, 1, fade)[:, None]
            samples[-fade:] *= np.linspace(1, 0, fade)[:, None]
        begin = round(start * sources.rate)
        stem[begin:begin + len(samples)] += _gain(spec, samples)
        records.append({"id": label, "file": str(source.path), "sha256": source.digest, "start_sample": begin,
                        "end_sample_exclusive": begin + len(samples), "placement_status": "ambient_no_contact", "loop": looping})
    return records


def _wav(ffmpeg: str, path: Path, samples: Audio, rate: int) -> None:
    if not np.isfinite(samples).all():
        raise ValueError("Nonfinite mix rejected")
    _run([ffmpeg, "-v", "error", "-n", "-f", "f64le", "-ar", str(rate), "-ac", "2", "-i", "-",
          "-c:a", "pcm_f32le", str(path)], samples.astype("<f8").tobytes())


def _loudness(ffmpeg: str, path: Path) -> Json:
    result = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    log = result.stderr.decode("utf-8", errors="replace")
    summary = log.rsplit("Summary:", 1)[-1]
    def read(pattern: str) -> float | None:
        match = re.search(pattern, summary)
        value = float(match[1]) if match else math.nan
        return value if math.isfinite(value) else None
    return {"integrated_lufs": read(r"I:\s*(-?[\d.]+) LUFS"), "true_peak_dbfs": read(r"Peak:\s*(-?[\d.]+) dBFS"), "log": log}


def _master(config: Json, ffmpeg: str, output: Path, rate: int, length: int) -> Json:
    settings = config.get("mastering", {})
    enabled = settings.get("normalize", False)
    if not isinstance(enabled, bool):
        raise ValueError("mastering.normalize must be boolean")
    ceiling = _number(settings.get("true_peak_db", -1), "true peak ceiling", -12, -1)
    target = _number(settings.get("integrated_lufs", -16), "LUFS target", -30, -12)
    source, final = output / "premaster.wav", output / "final-mix.wav"
    report: Json = {"normalization_applied": enabled, "time_stretch": False, "target_lufs": target, "true_peak_ceiling_db": ceiling}
    if enabled:
        first = _run([ffmpeg, "-hide_banner", "-i", str(source), "-af", f"loudnorm=I={target}:TP={ceiling}:LRA=7:print_format=json", "-f", "null", "-"])
        log = first.stderr.decode("utf-8", errors="replace")
        stats, _ = json.JSONDecoder().raw_decode(log[log.rfind("{"):])
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            _number(float(stats[key]), "loudnorm measurement", -200, 200)
        effect = (f"loudnorm=I={target}:TP={ceiling}:LRA=7:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
                  f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true")
        report["first_pass"] = stats
    else:
        measured = _loudness(ffmpeg, source)
        peak = measured["true_peak_dbfs"]
        attenuation = min(0.0, ceiling - peak - .1) if peak is not None else 0.0
        effect = f"volume={attenuation}dB"
        report["static_headroom_attenuation_db"] = attenuation
    filters = f"{effect},aresample={rate},apad=whole_len={length},atrim=end_sample={length}"
    command = [ffmpeg, "-v", "error", "-n", "-i", str(source), "-af", filters, "-ar", str(rate), "-c:a", "pcm_s16le", str(final)]
    _run(command)
    report["command"] = command
    return report


def _check_outputs(output: Path, ffmpeg: str, rate: int, length: int) -> Json:
    report: Json = {}
    for path in sorted(output.glob("*.wav")):
        _run([ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])
        decoded = _run([ffmpeg, "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(rate), "-f", "f64le", "-"])
        data = np.frombuffer(decoded.stdout, dtype="<f8")
        if len(data) != length * 2 or not np.isfinite(data).all():
            raise ValueError("Output PCM duration/nonfinite check failed")
        loudness = _loudness(ffmpeg, path)
        (output / "qa" / (path.stem + "-ebur128.txt")).write_text(loudness.pop("log"), encoding="utf-8")
        report[path.name] = {"sha256": _sha(path), "strict_decode": "passed", "frames": length, "sample_rate": rate,
                             "channels": 2, "sample_peak": float(np.max(np.abs(data))), **loudness}
    return report


def _settings(config: Json, config_path: Path) -> tuple[Path, str, int, int]:
    if not isinstance(config, dict) or config.get("schema_version") != "1.0":
        raise ValueError("Expected mixer JSON object with schema_version 1.0")
    duration = _number(config["duration_seconds"], "duration", 1, 600)
    fps = _integer(config["fps"], "fps", 1, 120)
    if abs(duration * fps - round(duration * fps)) > 1e-6:
        raise ValueError("Duration must fill whole delivery frames")
    rate = _integer(config.get("sample_rate", 48000), "sample rate", 8000, 192000)
    output = _path(config["output_dir"], config_path.parent)
    executable = config.get("ffmpeg", "ffmpeg")
    if not isinstance(executable, str) or not executable:
        raise ValueError("ffmpeg must name an existing executable")
    ffmpeg = str(_path(executable, config_path.parent)) if "/" in executable or "\\" in executable else executable
    if output.exists():
        raise ValueError("Output directory already exists; use a new version")
    return output, ffmpeg, rate, round(duration * rate)


def _build_stems(config: Json, sources: Sources, length: int) -> tuple[dict[str, Audio], Json]:
    stems = {name: np.zeros((length, 2)) for name in STEMS}
    duration = config["duration_seconds"]
    guards = _speech(config, duration)
    for name in ("voice", "music"):
        source = sources.bind(config[name])
        if name == "voice" and abs(source.duration - duration) > 1 / sources.rate:
            raise ValueError("Canonical voice must span complete timeline including silence")
        stems[name][:] = _gain(config[name], sources.decode(source, 0, duration))
    clock = {"speech_guard_seconds": guards, "events": _add_cues(config, sources, stems, guards),
             "ambience": _add_ambience(config, sources, stems["ambience"])}
    duck = config.get("ducking", {})
    fade = _number(duck.get("fade_seconds", .06), "duck fade", 0, .5)
    for name, default in (("music", -12), ("ambience", -9), ("footsteps", -12)):
        db = _number(duck.get(name + "_db", default), "ducking dB", -60, -3)
        stems[name] *= _duck(length, sources.rate, guards, db, fade)
    return stems, clock


def mix(config_path: Path) -> Json:
    """Render a fresh offline mix; publish provenance only after verified outputs."""
    config_path = config_path.resolve()
    config_digest = _sha(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    output, ffmpeg, rate, length = _settings(config, config_path)
    sources = Sources(config_path.parent, ffmpeg, rate)
    stems, clock = _build_stems(config, sources, length)
    sources.verify()
    output.mkdir(parents=True, exist_ok=False)
    (output / "qa").mkdir()
    for name, samples in stems.items():
        _wav(ffmpeg, output / (name + ".wav"), samples, rate)
    _wav(ffmpeg, output / "premaster.wav", sum(stems.values()), rate)
    mastering = _master(config, ffmpeg, output, rate, length)
    checks = _check_outputs(output, ffmpeg, rate, length)
    peak = checks["final-mix.wav"]["true_peak_dbfs"]
    if checks["final-mix.wav"]["sample_peak"] >= 1 or peak is not None and peak > mastering["true_peak_ceiling_db"] + .1:
        raise ValueError("Final true peak exceeds ceiling; output unaccepted")
    sources.verify()
    if _sha(config_path) != config_digest:
        raise ValueError("Configuration changed during mix; output unaccepted")
    clock.update({"fps": config["fps"], "sample_rate": rate, "duration_seconds": length / rate, "frame_count": round(config["duration_seconds"] * config["fps"])})
    _json(output / "actual-clock.json", clock)
    receipt = {"schema_version": "1.0", "status": "technical_pass_listening_pending", "config_sha256": config_digest,
               "config_file": str(config_path), "requested_settings": config,
               "script_sha256": _sha(Path(__file__)), "source_sha256": {str(p): s.digest for p, s in sources.files.items()},
               "source_formats": [{"file": str(s.path), "sample_rate": s.rate, "channels": s.channels} for s in sources.files.values()],
               "resampling": f"FFmpeg decoded all inputs to stereo {rate}Hz; no time-stretch, no word edits; original WAVs unchanged",
               "mastering": mastering, "checks": checks, "listening_and_lip_sync": "pending", "numpy_version": np.__version__}
    _json(output / "provenance.json", receipt)
    return {"output_dir": str(output), "final_mix": str(output / "final-mix.wav"), "status": receipt["status"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(mix(args.config), indent=2))
    except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Audio mix failed: {exc}\n")


if __name__ == "__main__":
    main()
