"""Helpers shared by the timing tests: synthetic sounds, WAV files, word rows, a fake recognizer (no tests here)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from engine.core.io import sha256_file
from engine.timing.recipe import load_timing_recipe
from engine.timing.recognise import Heard, Recognition
from engine.timing.sound import Sound, frame_of

RATE = 48_000
FPS = 30
RECIPE = load_timing_recipe("timing/words-onset-v001")
ALL, FIRST, Q1 = RECIPE.block("all_words"), RECIPE.block("first_word"), RECIPE.block("q1")


def sound(*parts: tuple) -> Sound:
    """Mono sound from ``("sil", s)``, ``("tone", s)`` (-10 dBFS, 220 Hz), ``("noise", s)`` (about -25 dBFS,
    unvoiced) or ``("soft", s)`` (about -42 dBFS noise: audible but below the voiced level)."""
    rng = np.random.RandomState(7)
    chunks = []
    for kind, seconds in parts:
        n = int(round(seconds * RATE))
        t = np.arange(n) / RATE
        if kind == "sil":
            chunks.append(np.zeros(n))
        elif kind == "tone":
            chunks.append(0.45 * np.sin(2 * np.pi * 220 * t))
        elif kind == "noise":
            chunks.append(rng.uniform(-0.1, 0.1, n))
        elif kind == "soft":
            chunks.append(rng.uniform(-0.0125, 0.0125, n))
        else:
            raise ValueError(kind)
    return Sound(np.concatenate(chunks), RATE)


def write_wav(path: Path, snd: Sound) -> str:
    """Write a mono PCM16 WAV and return its sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(snd.rate)
        handle.writeframes((np.clip(snd.samples, -1, 1) * 32767).astype("<i2").tobytes())
    return sha256_file(path)


def word(index: int, text: str, start_s: float, end_s: float, entry_start: int = 0) -> dict:
    return {"index": index, "text": text, "raw_text": text, "start_s": start_s, "end_s": end_s,
            "start_frame": entry_start + frame_of(start_s, FPS), "end_frame": entry_start + frame_of(end_s, FPS),
            "end_frame_exclusive": entry_start + frame_of(end_s, FPS)}


def fake_recognizer(table: dict[str, list[tuple[str, float, float]]]):
    """Recognizer answering from ``{prompt: [(raw, start, end)]}`` (no Whisper)."""
    def recognise(wav: Path, prompt: str) -> Recognition:
        heard = tuple(Heard(raw, raw.strip(" ,.!?").lower(), start, end, 0.9) for raw, start, end in table[prompt])
        return Recognition(heard, prompt, {"versions": {"fake": "1"}})
    return recognise
