"""``jjv audio mix``: dialogue (sample-exact) + music (ducked) + SFX -> stems, final mix, receipt, gate.

The ONLY place a film gets its audio: pictures are rendered silent and ``audio.remux`` stream-copies them
under the final mix.  Order of the music bed (identical to the first episode's builder, so a ``legacy``
recipe reproduces its stem): loop to length -> gain -> duck envelope -> music fades -> per-section gain.
The speech WAV samples are never filtered, resampled or re-timed (the dialogue stem is written exact); only the
beds move per section (never above the recipe gain), plus ONE recorded scalar per speech CLASS bus (dialogue,
vocabulary, end_line, ...; ``speech_buses`` in the receipt): samples and relative timing inside a class stay exact.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..core.errors import Refused
from ..core.io import canonical_sha256, sha256_file, write_json_once
from ..voice.wavio import metrics, read_wav, write_wav_once
from . import bedsolve, dsp, loudness, mixgate
from .recipe import AudioRecipe
from .sfxplace import avoid_speech
from .windows import PlacedWav, class_stems, dialogue_stem

RECEIPT_FILE = "mix-receipt.json"
RECEIPT_SCHEMA = "jjv/audio-mix/v1"
STEMS = {"dialogue": "dialogue-stem.wav", "brand_voice": "brand-voice-stem.wav", "music": "music-stem.wav",
         "sfx": "sfx-stem.wav", "final": "final-mix.wav"}


@dataclass(frozen=True)
class Source:
    path: Path
    sha256: str
    audio: np.ndarray  # float32 stereo


def load_source(path: Path, expected_sha: str | None, rate: int, label: str) -> Source:
    path = Path(path)
    if not path.is_file():
        raise Refused(f"{label}: file not found: {path}")
    digest = sha256_file(path)
    if expected_sha is not None and digest != expected_sha.lower():
        raise Refused(f"{label}: {path} hashes to {digest}, expected {expected_sha}")
    wav = read_wav(path)
    if wav.rate != rate:
        raise Refused(f"{label}: {wav.rate} Hz, the mix needs {rate} Hz")
    return Source(path, digest, dsp.to_stereo_float(np.frombuffer(wav.pcm, dtype="<i2").reshape(-1, wav.channels)))


def music_bed(recipe: dict, music: np.ndarray, duck: np.ndarray, total: int, rate: int, start: int = 0) -> np.ndarray:
    """Float32 bed in the exact order of the first episode's builder (loop, gain, duck, fades).  ``start`` > 0: the
    music starts there (after the brand voice) with the recipe's after-brand-voice fade-in, silence before."""
    usable = total - start
    bed = dsp.loop_to_length(music, usable, recipe["music"]["loop_crossfade_s"], rate)
    bed *= dsp.db_to_gain(recipe["music"]["gain_db"])
    bed *= duck[start:]
    fade_in = recipe["music"]["after_brand_voice_fade_in_s"] if start else recipe["music"]["fade_in_s"]
    bed *= dsp.smooth_fades(usable, fade_in, recipe["music"]["fade_out_s"], rate)
    if not start:
        return bed
    out = np.zeros((total, 2), dtype=np.float32)
    out[start:] = bed
    return out


def sfx_bed(recipe: dict, placements: list[dict], clips: dict[str, np.ndarray], total: int, rate: int, fps: int,
            duck: np.ndarray | None) -> np.ndarray:
    bed = np.zeros((total, 2), dtype=np.float32)
    for row in placements:
        clip = clips[row["clip_id"]]
        start = row["frame"] * rate // fps
        length = int(round(row["duration_s"] * rate))
        source = (dsp.loop_to_length(clip, length, min(1.0, clip.shape[0] / rate / 4.0), rate)
                  if row.get("loop") and clip.shape[0] < length else clip)
        fade = 1.0 if row.get("loop") else 0.03
        dsp.layer_segment(bed, source, start=start, offset=0, duration=length, gain_db=row["gain_db"], fade_in_s=fade,
                          fade_out_s=fade if row.get("loop") else 0.08, rate=rate, pan=row.get("pan", 0.0))
    if duck is not None:
        bed *= duck
    return bed


def sfx_from_stem(stem: np.ndarray, total: int) -> np.ndarray:
    if stem.shape[0] < total:
        raise Refused(f"the SFX stem has {stem.shape[0]} samples, the film needs {total}")
    return stem[:total].copy()


def compose(recipe: dict, stems_by_class: dict[str, np.ndarray], music: np.ndarray, sfx: np.ndarray, sections: list[dict],
            gains_db: list[float], rate: int, buses: dict[str, float], brand: np.ndarray | None = None) -> dict:
    """Apply the per-section bed gains and the class bus gains, sum in the integer domain.
    A class at 0 dB adds its WAV samples exactly as bound."""
    total = music.shape[0]
    envelope = dsp.section_gain_envelope(total, sections, gains_db, recipe["loudness"]["ramp_s"], rate) \
        if any(abs(g) > 1e-9 for g in gains_db) else None
    music_g = music * envelope if envelope is not None else music
    sfx_g = sfx * envelope if envelope is not None else sfx
    music_pcm, sfx_pcm = dsp.to_pcm16(music_g), dsp.to_pcm16(sfx_g)
    bus = np.zeros((total, 2), dtype=np.int32)
    for name, stem in stems_by_class.items():
        gain = buses.get(name, 0.0)
        bus += stem.astype(np.int32) if gain == 0 else np.rint(stem.astype(np.float64) * dsp.db_to_gain(gain)).astype(np.int32)
    mix = bus + music_pcm.astype(np.int32) + sfx_pcm.astype(np.int32)
    if brand is not None:
        mix = mix + brand.astype(np.int32)
    return {"music_pcm": music_pcm, "sfx_pcm": sfx_pcm, "music_float": music_g, "buses": dict(buses),
            "speech_bus": np.clip(bus, -32768, 32767).astype("<i2"),
            "clipped": int(np.count_nonzero((mix > 32767) | (mix < -32768))),
            "final": np.clip(mix, -32768, 32767).astype("<i2")}


def wav_row(path: Path, rate: int) -> dict:
    return {"path": path.name, "sha256": sha256_file(path), "samples": read_wav(path).frames,
            "metrics": metrics(read_wav(path))}


def write_stems(out: Path, dialogue: np.ndarray, bundle: dict, rate: int, brand: np.ndarray | None = None) -> dict:
    rows = {}
    layers = [("dialogue", dialogue), ("music", bundle["music_pcm"]), ("sfx", bundle["sfx_pcm"]), ("final", bundle["final"])]
    if brand is not None:
        layers.insert(1, ("brand_voice", brand))
    for key, pcm in layers:
        path = Path(out) / STEMS[key]
        write_wav_once(path, rate, 2, 2, np.ascontiguousarray(pcm).tobytes())
        rows[key] = wav_row(path, rate)
    return rows


def _overlaps_other(wav: PlacedWav, placed: list[PlacedWav]) -> bool:
    return any(o is not wav and o.start_sample < wav.end_sample and wav.start_sample < o.end_sample and np.any(o.pcm())
               and np.any(wav.pcm()) for o in placed)


def render(recipe: AudioRecipe, *, timeline: dict, placed: list[PlacedWav], windows: list[dict], sections: list[dict],
           music_src: Source, sfx_parts: dict, out: Path, ffmpeg: str, runner=subprocess.run,
           emit: Callable[[str], None] = lambda m: None, brand: PlacedWav | None = None, brand_gain_db: float = 0.0) -> dict:
    """Build beds, target loudness, write stems and return the receipt body (without picture/mux)."""
    data, rate, total = recipe.data, timeline["sample_rate"], timeline["total_samples"]
    dialogue = dialogue_stem(placed, total)
    by_class = class_stems(placed, total)
    duck_cfg = data["duck"]
    duck, duck_rows = dsp.duck_envelope(windows, total, depth_db=duck_cfg["depth_db"], attack_s=duck_cfg["attack_s"],
                                        release_s=duck_cfg["release_s"], rate=rate, merge_gap_s=duck_cfg["merge_gap_s"])
    sfx_moves: list[dict] = []
    bed_start = brand.end_sample if brand is not None else 0
    music = music_bed(data, music_src.audio, duck, total, rate, bed_start)
    brand_pcm = None
    if brand is not None:
        brand_pcm = np.zeros((total, 2), dtype=np.int16)
        voice = brand.pcm() if brand_gain_db == 0 else np.rint(brand.pcm().astype(np.float64) * dsp.db_to_gain(brand_gain_db)).astype("<i2")
        brand_pcm[brand.start_sample:brand.end_sample] = voice
    if not sfx_parts.get("enabled", True):
        sfx = np.zeros((total, 2), dtype=np.float32)  # SFX/ambience are opt-in per episode on this channel
    elif sfx_parts.get("stem") is not None:
        sfx = sfx_from_stem(sfx_parts["stem"].audio, total)
    elif sfx_parts.get("placements"):
        sfx_parts = {**sfx_parts}
        sfx_parts["placements"], sfx_moves = avoid_speech(sfx_parts["placements"], windows, timeline["fps"], rate, total,
                                                          data["sfx"]["avoid_speech_s"])
        sduck = None
        if data["sfx"]["duck_db"] < 0:
            sduck, _ = dsp.duck_envelope(windows, total, depth_db=data["sfx"]["duck_db"], attack_s=duck_cfg["attack_s"],
                                         release_s=duck_cfg["release_s"], rate=rate, merge_gap_s=duck_cfg["merge_gap_s"])
        sfx = sfx_bed(data, sfx_parts["placements"], sfx_parts["clips"], total, rate, timeline["fps"], sduck)
        sfx *= dsp.smooth_fades(total, data["music"]["fade_in_s"], data["music"]["fade_out_s"], rate)
    else:
        sfx = np.zeros((total, 2), dtype=np.float32)
    loud_cfg = data["loudness"]
    cinema = data["profile"] == "cinema" and loud_cfg["enabled"]

    def compose_with(gains: list[float], buses: dict[str, float]) -> dict:
        return compose(data, by_class, music, sfx, sections, gains, rate, buses, brand_pcm)

    roles = mixgate.roles_of(sections, windows)
    base = data["music"]["gain_db"]
    schedule = [data["music"]["section_gains_db"].get(s["name"], base) - base for s in sections]  # the recipe gain, re base
    classes_in = [{w.bus for w in placed if w.start_sample < s["end_sample"] and w.end_sample > s["start_sample"]}
                  for s in sections]
    buses_cfg = data["speech_buses"]
    if cinema:
        gains, buses, history, bundle = mixgate.target_gains(compose_with, sections, roles, schedule, loud_cfg, rate, ffmpeg,
                                                             runner, emit, section_classes=classes_in, buses_cfg=buses_cfg)
    else:
        buses = bedsolve.initial_buses(sorted(by_class), buses_cfg)
        gains, history, bundle = [0.0] * len(sections), [], compose_with([0.0] * len(sections), buses)
    rows = mixgate.measure_sections(bundle["final"], sections, loud_cfg, rate, ffmpeg, runner, roles) if sections else []
    for row, role, group in zip(rows, roles, classes_in):
        row["role"], row["classes"] = role, sorted(group)
    whole = loudness.measure(bundle["final"], rate, ffmpeg, runner=runner).as_dict()
    pump = mixgate.pumping(bundle["music_float"], duck_rows, data["pumping"], rate, sections, duck_cfg)
    bus_rows = {name: {"gain_db": round(buses[name], 4), "mode": bedsolve.bus_spec(buses_cfg, name)["mode"],
                       **{k: v for k, v in bedsolve.bus_spec(buses_cfg, name).items() if k in ("min_db", "max_db")}}
                for name in sorted(by_class)}
    exact = bool(all(np.array_equal(dialogue[w.start_sample:w.end_sample], w.pcm()) for w in placed
                     if not _overlaps_other(w, placed))) and bundle["clipped"] == 0
    verdict = mixgate.evaluate(data["profile"], loud_cfg, data["pumping"], whole, rows, pump, exact, gains, bus_rows, schedule)
    steps = [round(abs(a - b), 4) for a, b in zip(gains, gains[1:])]
    stems = write_stems(out, dialogue, bundle, rate, brand_pcm)
    return {"duck_windows": duck_rows, "section_gains_db": [round(g, 4) for g in gains], "loudness": {
        "target_lufs": loud_cfg["target_lufs"], "tolerance_lu": loud_cfg["tolerance_lu"], "whole": whole,
        "sections": rows, "iterations": history, "sfx_ducked": data["sfx"]["duck_db"]}, "pumping": pump,
        "stems": stems, "roles": roles, "bed_schedule_db": [round(x, 4) for x in schedule], "bed_start_s": bed_start / rate,
        "speech_buses": bus_rows,
        "bed_steps_db": steps, "bed_step_limit_db": loud_cfg["max_bed_step_db"], "sfx_enabled": bool(sfx_parts.get("enabled", True)),
        "sfx_moved_off_speech": sfx_moves, "dialogue_exact": exact, "mix_clipped_samples": bundle["clipped"], **verdict}


def write_receipt(out: Path, receipt: dict) -> str:
    return write_json_once(Path(out) / RECEIPT_FILE, receipt, mode="ascii", stamp=True)


def receipt_sha(receipt: dict) -> str:
    return canonical_sha256(receipt, mode="ascii")
