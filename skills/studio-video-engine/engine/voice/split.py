"""Data-driven, sample-exact split of one finalized WAV into chained H3 segments.

A split plan is data on the dialogue row (never a code constant)::

    {"pad_tail_silence": true,
     "segments": [{"label": "seg1", "samples": 240000, "speech_conditioning": true},
                  {"label": "seg3", "samples": 80000, "speech_conditioning": false}]}

Segments are consecutive slices of the trimmed source starting at its first sample.  When the
declared total exceeds the source, only the tail may be zero-padded and only when the plan
says ``pad_tail_silence``; a segment declared ``speech_conditioning: false`` must contain no
speech window (checked by the caller with the trim params).  The receipt carries a
concatenation proof: segment samples sum to the declared total, and the real part equals the
source bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import Refused

_LABEL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


@dataclass(frozen=True)
class SplitSegment:
    label: str
    samples: int
    speech_conditioning: bool


@dataclass(frozen=True)
class SplitPlan:
    segments: tuple[SplitSegment, ...]
    pad_tail_silence: bool

    @property
    def total_samples(self) -> int:
        return sum(segment.samples for segment in self.segments)


@dataclass(frozen=True)
class SplitPart:
    segment: SplitSegment
    pcm: bytes
    start_sample: int
    real_samples: int
    padded_samples: int


def parse_split_plan(document: object, label: str) -> SplitPlan:
    if not isinstance(document, dict):
        raise Refused(f"{label}: split must be an object")
    unknown = set(document) - {"segments", "pad_tail_silence"}
    if unknown:
        raise Refused(f"{label}: split has unknown keys {sorted(unknown)}")
    pad = document.get("pad_tail_silence", False)
    if not isinstance(pad, bool):
        raise Refused(f"{label}: split.pad_tail_silence must be a boolean")
    rows = document.get("segments")
    if not isinstance(rows, list) or not rows:
        raise Refused(f"{label}: split.segments must be a non-empty list")
    segments: list[SplitSegment] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"label", "samples", "speech_conditioning"}:
            raise Refused(f"{label}: each split segment needs exactly label, samples, speech_conditioning")
        name, samples, speech = row["label"], row["samples"], row["speech_conditioning"]
        if not isinstance(name, str) or not name or not set(name) <= _LABEL_CHARS:
            raise Refused(f"{label}: split segment label {name!r} is not a plain token")
        if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
            raise Refused(f"{label}: split segment {name!r} samples must be a positive integer")
        if not isinstance(speech, bool):
            raise Refused(f"{label}: split segment {name!r} speech_conditioning must be a boolean")
        segments.append(SplitSegment(name, samples, speech))
    labels = [segment.label for segment in segments]
    if len(set(labels)) != len(labels):
        raise Refused(f"{label}: duplicate split segment labels")
    return SplitPlan(tuple(segments), pad)


def apply_split(pcm: bytes, frame_bytes: int, plan: SplitPlan) -> list[SplitPart]:
    """Slice ``pcm`` (one trimmed source) into the planned segments."""
    if frame_bytes <= 0 or len(pcm) % frame_bytes:
        raise Refused("split source PCM is not whole frames")
    source_samples = len(pcm) // frame_bytes
    parts: list[SplitPart] = []
    cursor = 0
    for segment in plan.segments:
        available = max(0, min(segment.samples, source_samples - cursor))
        missing = segment.samples - available
        if missing and not plan.pad_tail_silence:
            raise Refused(f"split segment {segment.label!r} needs {missing} samples beyond the source "
                          "and pad_tail_silence is false")
        real = pcm[cursor * frame_bytes:(cursor + available) * frame_bytes]
        parts.append(SplitPart(segment, real + b"\x00" * (missing * frame_bytes), cursor, available, missing))
        cursor += segment.samples
    return parts


def concat_proof(parts: list[SplitPart], source_pcm: bytes, frame_bytes: int, plan: SplitPlan) -> dict:
    """Prove the parts concatenate to the declared total and reproduce the source bytes."""
    joined = b"".join(part.pcm for part in parts)
    total = len(joined) // frame_bytes
    real = sum(part.real_samples for part in parts)
    source_samples = len(source_pcm) // frame_bytes
    covered = min(real, source_samples)
    if total != plan.total_samples:
        raise Refused(f"split proof failed: {total} samples != declared {plan.total_samples}")
    if joined[:covered * frame_bytes] != source_pcm[:covered * frame_bytes]:
        raise Refused("split proof failed: concatenated real samples differ from the source")
    return {"declared_total_samples": plan.total_samples, "concatenated_samples": total,
            "source_samples": source_samples, "source_samples_used": real,
            "source_samples_unused": max(0, source_samples - real),
            "padded_samples": sum(part.padded_samples for part in parts), "ok": True}
