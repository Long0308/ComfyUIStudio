"""Stdlib PCM16 WAV generators for the voice tests (no numpy, no ffmpeg)."""

from __future__ import annotations

import io
import math
import struct
import wave


def pcm16(samples: list[int], channels: int) -> bytes:
    clipped = [max(-32768, min(32767, int(v))) for v in samples]
    frames = [v for v in clipped for _ in range(channels)]
    return struct.pack(f"<{len(frames)}h", *frames)


def wav_from_pcm(pcm: bytes, rate: int, channels: int) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return stream.getvalue()


def tone(seconds: float, rate: int, *, amplitude: float = 0.5, frequency: float = 220.0) -> list[int]:
    count = int(round(seconds * rate))
    return [int(32767 * amplitude * math.sin(2 * math.pi * frequency * i / rate)) for i in range(count)]


def square_full_scale(seconds: float, rate: int, *, period: int = 50) -> list[int]:
    """A full-scale square wave: resampling rings past +-32767, so the converter clips it."""
    count = int(round(seconds * rate))
    return [32767 if (i // period) % 2 else -32767 for i in range(count)]


def silence(seconds: float, rate: int) -> list[int]:
    return [0] * int(round(seconds * rate))


def noise_burst(seconds: float, rate: int, *, amplitude: float = 0.02) -> list[int]:
    """A deterministic, low-level unvoiced-like burst (above -40 dBFS RMS for amplitude >= 0.02)."""
    count = int(round(seconds * rate))
    return [int(32767 * amplitude * (1 if (i * 7919) % 3 else -1)) for i in range(count)]


def segments_wav_bytes(parts: list[list[int]], rate: int = 48_000, channels: int = 2) -> bytes:
    samples = [v for part in parts for v in part]
    return wav_from_pcm(pcm16(samples, channels), rate, channels)


def tone_wav_bytes(seconds: float = 0.5, rate: int = 48_000, channels: int = 2, *, lead_silence: float = 0.2,
                   tail_silence: float = 0.3, amplitude: float = 0.5) -> bytes:
    return segments_wav_bytes([silence(lead_silence, rate), tone(seconds, rate, amplitude=amplitude),
                               silence(tail_silence, rate)], rate, channels)


def silent_wav_bytes(seconds: float = 0.5, rate: int = 48_000, channels: int = 2) -> bytes:
    return segments_wav_bytes([silence(seconds, rate)], rate, channels)
