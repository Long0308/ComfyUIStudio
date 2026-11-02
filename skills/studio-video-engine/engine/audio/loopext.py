"""Extend a naturally ending song to a bed of at least ``target_s`` by looping at a bar boundary (CPU).

Port of the first episode's ``loop_extend.py`` (audio lane T-A10): the loop point is the place in the
second half of the song whose RMS-envelope window best matches the window right after the intro; the bed is
``song[0:t] + (song[a:t] ...) + song[a:end]`` with an equal-power crossfade at every seam, so the NATURAL
ending of the song is kept.  The seam list is returned for the receipt (audit).  Input is float32 stereo.
"""

from __future__ import annotations

import numpy as np

from ..core.errors import Refused

HOP_S = 0.01  # envelope hop: 480 samples at 48 kHz in the original


def envelope(audio: np.ndarray, hop: int) -> np.ndarray:
    mono = audio.mean(axis=1)
    count = len(mono) // hop
    return np.sqrt((mono[:count * hop].reshape(count, hop) ** 2).mean(axis=1))


def best_loop(audio: np.ndarray, bpm: float, rate: int, beats_per_bar: int = 4, intro_bars: int = 2,
              window_bars: int = 4) -> tuple[int, int, float]:
    """(a, t, score): ``a`` = start of the reference window after the intro, ``t`` = best match in the second half."""
    bar = int(round(60.0 / bpm * beats_per_bar * rate))
    hop = int(round(HOP_S * rate))
    env = envelope(audio, hop)
    a, width = intro_bars * bar, window_bars * bar
    length = width // hop
    ref = env[a // hop:a // hop + length]
    if len(ref) != length:
        raise Refused("the song is shorter than intro + reference window: nothing to loop")
    ref = (ref - ref.mean()) / (ref.std() + 1e-9)
    best = (a, a, -1.0)
    for t in range(len(audio) // 2, len(audio) - width - bar, hop):
        segment = env[t // hop:t // hop + length]
        if len(segment) != length:
            break
        segment = (segment - segment.mean()) / (segment.std() + 1e-9)
        score = float((ref * segment).mean())
        if score > best[2]:
            best = (a, t, score)
    if best[1] <= a + bar:
        raise Refused("no loop point found after the intro; the song is too short or the envelope search failed")
    return best


def refine_zero_phase(audio: np.ndarray, a: int, t: int, radius: int = 2400) -> int:
    """Shift ``t`` within +-radius samples so the waveform at ``t`` best matches the one at ``a`` (no click)."""
    ref = audio[a:a + 4800].mean(axis=1)
    best_t, best_score = t, -1e9
    for delta in range(-radius, radius + 1, 8):
        segment = audio[t + delta:t + delta + 4800].mean(axis=1)
        if len(segment) != len(ref):
            continue
        score = float(np.dot(ref, segment))
        if score > best_score:
            best_score, best_t = score, t + delta
    return best_t


def extend(audio: np.ndarray, bpm: float, target_s: float, rate: int, *, crossfade_s: float = 0.25,
           beats_per_bar: int = 4, intro_bars: int = 2, window_bars: int = 4) -> tuple[np.ndarray, dict]:
    """The bed (>= ``target_s`` unless the song already is longer) and the seam record."""
    audio = audio.astype(np.float32, copy=False)
    target = int(round(target_s * rate))
    if audio.shape[0] >= target:
        return audio.copy(), {"loop": False, "reason": "the song is already long enough", "joins": [],
                              "source_duration_s": audio.shape[0] / rate, "output_duration_s": audio.shape[0] / rate}
    a, t, score = best_loop(audio, bpm, rate, beats_per_bar, intro_bars, window_bars)
    t = refine_zero_phase(audio, a, t)
    xf = int(crossfade_s * rate)
    body, tail, loop_part = audio[:t], audio[a:], audio[a:t]
    pieces, joins, total = [body], [], body.shape[0]
    while total + tail.shape[0] < target:
        pieces.append(loop_part)
        joins.append({"at_s": round(total / rate, 3), "kind": "loop [a,t)"})
        total += loop_part.shape[0]
    pieces.append(tail)
    joins.append({"at_s": round(total / rate, 3), "kind": "tail [a,end)"})
    out = pieces[0].copy()
    fade = np.linspace(0, 1, xf, dtype=np.float32)[:, None]
    for piece in pieces[1:]:
        head, rest = piece[:xf], piece[xf:]
        out[-xf:] = out[-xf:] * np.sqrt(1 - fade) + head * np.sqrt(fade)
        out = np.concatenate([out, rest])
    return out, {"loop": True, "bpm": bpm, "ref_start_s": round(a / rate, 3), "loop_point_s": round(t / rate, 3),
                 "envelope_match_score": round(score, 4), "crossfade_s": crossfade_s, "joins": joins,
                 "source_duration_s": round(audio.shape[0] / rate, 3), "output_duration_s": round(out.shape[0] / rate, 3)}
