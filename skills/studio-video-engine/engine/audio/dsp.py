"""Sample-level DSP of the mix stage (numpy, float32 like the first episode's builder).

The operations and their ORDER follow the first episode's ``build_mix_plan_v003`` exactly (loop with an
equal-power crossfade, dB gain, duck envelope built from linspace ramps, sin^2/cos^2 fades), so a recipe
with the same numbers reproduces its stems sample for sample.  New here: duck-window merging (``hold``)
and the per-section bed gain envelope.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from ..core.errors import Refused


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def gain_to_db(gain: float) -> float:
    return 20.0 * math.log10(max(gain, 1e-12))


def pan_gains(pan: float) -> tuple[float, float]:
    clamped = min(1.0, max(-1.0, float(pan)))
    theta = (clamped + 1.0) * math.pi / 4.0
    return math.cos(theta), math.sin(theta)


def smooth_fades(length: int, fade_in_s: float, fade_out_s: float, rate: int) -> np.ndarray:
    """(length, 1) envelope: sin^2 fade in, cos^2 fade out."""
    envelope = np.ones(length, dtype=np.float32)
    fade_in = min(length, max(0, int(round(fade_in_s * rate))))
    fade_out = min(length, max(0, int(round(fade_out_s * rate))))
    if fade_in:
        envelope[:fade_in] *= np.sin(np.linspace(0.0, math.pi / 2.0, fade_in, dtype=np.float32)) ** 2
    if fade_out:
        envelope[-fade_out:] *= np.cos(np.linspace(0.0, math.pi / 2.0, fade_out, dtype=np.float32)) ** 2
    return envelope[:, None]


def to_stereo_float(pcm: np.ndarray) -> np.ndarray:
    """int16 (n, c) -> float32 stereo in [-1, 1); mono is duplicated (the first episode's rule)."""
    audio = pcm.astype(np.float32) / 32768.0
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    if audio.shape[1] != 2:
        raise Refused(f"audio must be mono or stereo, got {audio.shape[1]} channels")
    return audio


def to_pcm16(audio: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")


def layer_segment(destination: np.ndarray, source: np.ndarray, *, start: int, offset: int, duration: int,
                  gain_db: float, fade_in_s: float, fade_out_s: float, rate: int, pan: float = 0.0) -> dict:
    """Add ``source[offset:offset+duration]`` into ``destination`` at ``start`` (in place, float32)."""
    source_start = max(0, int(offset))
    wanted = max(0, min(int(duration), max(0, source.shape[0] - source_start)))
    dest_start = max(0, int(start))
    writable = max(0, min(wanted, destination.shape[0] - dest_start))
    if writable:
        segment = source[source_start:source_start + writable].copy()
        segment *= smooth_fades(writable, fade_in_s, fade_out_s, rate)
        left, right = pan_gains(pan)
        segment[:, 0] *= db_to_gain(gain_db) * left
        segment[:, 1] *= db_to_gain(gain_db) * right
        destination[dest_start:dest_start + writable] += segment
    return {"source_offset_sample": source_start, "mapped_samples": writable, "timeline_clipped": writable < wanted}


def loop_to_length(source: np.ndarray, total: int, crossfade_s: float, rate: int) -> np.ndarray:
    """Repeat ``source`` to ``total`` samples, each seam an equal-power crossfade (cos^2 / sin^2)."""
    if source.shape[0] >= total:
        return source[:total].copy()
    overlap = int(crossfade_s * rate)
    if overlap <= 0 or overlap >= source.shape[0]:
        raise Refused("invalid music-loop crossfade for this source length")
    output = np.zeros((total, source.shape[1]), dtype=np.float32)
    output[:source.shape[0]] = source
    position = source.shape[0]
    while position < total:
        second = source[:total - (position - overlap)].copy()
        if second.shape[0] <= overlap:
            raise Refused("music source too short for the requested loop")
        weights = np.linspace(0.0, 1.0, overlap, endpoint=False, dtype=np.float32)
        left_mix = np.cos(weights * math.pi / 2.0) ** 2
        right_mix = np.sin(weights * math.pi / 2.0) ** 2
        start = position - overlap
        output[start:position] = output[start:position] * left_mix[:, None] + second[:overlap] * right_mix[:, None]
        continuation = second[overlap:]
        end = min(total, position + continuation.shape[0])
        output[position:end] = continuation[:end - position]
        position = end
    return output


def merge_windows(windows: Sequence[dict], gap_samples: int) -> list[dict]:
    """Sorted windows; a gap shorter than ``gap_samples`` is bridged (the bed stays down, the ``hold``)."""
    merged: list[dict] = []
    for window in sorted(windows, key=lambda w: (w["start_sample"], w["end_sample"])):
        if merged and window["start_sample"] - merged[-1]["end_sample"] < gap_samples:
            last = merged[-1]
            last["end_sample"] = max(last["end_sample"], window["end_sample"])
            last["members"].append(window["id"])
        else:
            merged.append({**window, "members": [window["id"]]})
    return merged


def duck_envelope(windows: Sequence[dict], total: int, *, depth_db: float, attack_s: float, release_s: float,
                  rate: int, merge_gap_s: float = 0.0) -> tuple[np.ndarray, list[dict]]:
    """(total, 1) float32 envelope: linear attack to ``depth_db``, hold, linear release; minimum over windows."""
    envelope = np.ones(total, dtype=np.float32)
    attack, release = int(round(attack_s * rate)), int(round(release_s * rate))
    duck = db_to_gain(depth_db)
    clamped = [{**w, "start_sample": min(total, max(0, w["start_sample"])),
                "end_sample": min(total, max(w["start_sample"], w["end_sample"]))} for w in windows]
    used = merge_windows(clamped, int(round(merge_gap_s * rate))) if merge_gap_s > 0 else [
        {**w, "members": [w["id"]]} for w in sorted(clamped, key=lambda w: (w["start_sample"], w["end_sample"]))]
    rows = []
    for window in used:
        start, end = window["start_sample"], window["end_sample"]
        attack_start = max(0, start - attack)
        release_end = min(total, end + release)
        local = np.ones(release_end - attack_start, dtype=np.float32)
        if start > attack_start:
            local[:start - attack_start] = np.linspace(1.0, duck, start - attack_start, dtype=np.float32)
        local[start - attack_start:end - attack_start] = duck
        if release_end > end:
            local[end - attack_start:] = np.linspace(duck, 1.0, release_end - end, dtype=np.float32)
        np.minimum(envelope[attack_start:release_end], local, out=envelope[attack_start:release_end])
        rows.append({"id": window["id"], "kind": window.get("kind"), "members": window["members"],
                     "start_sample": start, "end_sample_exclusive": end, "duck_db": depth_db})
    return envelope[:, None], rows


def section_gain_envelope(total: int, sections: Sequence[dict], gains_db: Sequence[float], ramp_s: float,
                          rate: int) -> np.ndarray:
    """(total, 1) linear gain: constant per section, cosine-shaped ramp of ``ramp_s`` centred on each seam."""
    if not sections:
        return np.ones((total, 1), dtype=np.float32)
    xs, ys = [0.0], [db_to_gain(gains_db[0])]
    for left, right, g_left, g_right in zip(sections, sections[1:], gains_db, gains_db[1:]):
        seam = float(right["start_sample"])
        # the ramp is centred on the seam and may use at most half of each neighbouring section
        half = min(ramp_s * rate / 2.0, (seam - left["start_sample"]) / 2.0, (right["end_sample"] - seam) / 2.0)
        xs += [seam - half, seam + half]
        ys += [db_to_gain(g_left), db_to_gain(g_right)]
    xs.append(float(total))
    ys.append(ys[-1])
    index = np.arange(total, dtype=np.float64)
    linear = np.interp(index, xs, ys)
    return linear.astype(np.float32)[:, None]


def rms_dbfs(audio: np.ndarray) -> float:
    """RMS of float audio in dBFS (-120 for silence)."""
    if audio.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
    return round(20.0 * math.log10(max(rms, 1e-6)), 3)
