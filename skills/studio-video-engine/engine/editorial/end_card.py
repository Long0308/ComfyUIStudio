"""The ending block: end-logo frames come from the engine timeline, the end plate is measured.

``timeline.end_card_frames`` is the only source of the end-logo length.  When an end plate is
declared, its start frame follows its ``placement``: ``speech_end`` (default) = ``ceil`` of the measured
end of the last card's pronunciation (10 ms RMS windows above 2 % of the peak); ``card_end`` = the first
frame after the last card window, never earlier than that measurement.  Either way the plate never
covers a word that is still playing.
"""

from __future__ import annotations

import array
import math
import sys
import wave
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain

RMS_WINDOW_S = 0.01
RMS_FLOOR = 0.02  # fraction of the peak window RMS that still counts as speech


def speech_end_seconds(path: Path) -> float:
    """End of the last window whose RMS exceeds ``RMS_FLOOR`` of the peak (16-bit PCM WAV)."""
    try:
        with wave.open(str(path)) as stream:
            rate, count, channels, width = (stream.getframerate(), stream.getnframes(),
                                            stream.getnchannels(), stream.getsampwidth())
            frames = stream.readframes(count)
    except (OSError, wave.Error, EOFError) as error:
        raise Uncertain(f"cannot read WAV {path}: {error}") from error
    if width != 2:
        raise Uncertain(f"{path}: only 16-bit PCM WAV can be measured, got {8 * width}-bit")
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder == "big":
        samples.byteswap()
    values = [sum(samples[i:i + channels]) / channels / 32768 for i in range(0, len(samples), channels)]
    window = int(rate * RMS_WINDOW_S)
    if window < 1 or len(values) <= window:
        raise Uncertain(f"{path}: WAV too short to measure")
    rms = [math.sqrt(sum(v * v for v in values[i:i + window]) / window)
           for i in range(0, len(values) - window, window)]
    loud = [i for i, level in enumerate(rms) if level > max(rms) * RMS_FLOOR]
    if not loud:
        raise Uncertain(f"{path}: no speech found")
    return (loud[-1] + 1) * RMS_WINDOW_S


PLATE_PLACEMENTS = ("card_end", "speech_end")


def check_end_plate(declared_start: int, last_card_start: int, last_card_wav: Path, fps: int, *,
                    placement: str = "speech_end", last_card_end: int | None = None) -> dict:
    measured_s = speech_end_seconds(last_card_wav)
    measured_frame = last_card_start + measured_s * fps
    spoken = math.ceil(measured_frame)
    if placement == "card_end":
        if last_card_end is None:
            raise Refused("end plate placement card_end needs the end of the last card window")
        expected = max(last_card_end, spoken)
        why = (f"placement card_end puts it at the end of the last card window (f{last_card_end}); the last "
               f"card's speech ends at f{measured_frame:.2f}")
    else:
        expected = spoken
        why = f"the last card's speech ends at f{measured_frame:.2f}"
    if declared_start != expected:
        raise Refused(f"end plate starts at f{declared_start} but {why}: the plate must start at f{expected}")
    return {"speech_end_frame": round(measured_frame, 2), "speech_end_s": round(measured_s, 3)}


def build_ending(declared: dict | None, *, main_frames: int, end_card_frames: int,
                 plate_check: dict | None) -> dict:
    """Declared render parameters + the timeline-derived end logo (+ the measured plate fields)."""
    ending: dict[str, Any] = dict(declared or {})
    end_logo = dict(ending.get("end_logo") or {})
    forced = {"frames", "from_frame", "total_frames"} & set(end_logo)
    if forced:
        raise Refused(f"ending.end_logo may not declare {sorted(forced)}: they come from timeline.end_card_frames")
    if end_card_frames > 0:
        end_logo.update({"frames": end_card_frames, "from_frame": main_frames,
                         "total_frames": main_frames + end_card_frames})
        ending["end_logo"] = end_logo
    elif end_logo:
        raise Refused("ending.end_logo is declared but the episode timeline has no end card (end_card_frames 0)")
    if plate_check is not None and "end_plate" in ending:
        plate = dict(ending["end_plate"])
        plate.update({"speech_end_frame": plate_check["speech_end_frame"],
                      "speech_end_s": plate_check["speech_end_s"]})
        ending["end_plate"] = plate
    return ending


# ---- ending parameters (T-E42) -----------------------------------------------------------------------
# The floors are the DOMAIN's (delivery.sections.logo_hold.min / vocab_card.min, delivery.end_card.frames_min):
# no literal lives here (M9a / Q-8).
FLOOR_SOURCES = {"logo_hold_frames": ("sections", "logo_hold", "min"), "card_min_frames": ("sections", "vocab_card", "min"),
                 "end_card_frames": ("end_card", "frames_min")}
MUSIC_EXTEND = ("loop_phrase_crossfade", "none")


def domain_floor(domain: dict, key: str) -> int:
    """The floor of one ending parameter from ``domain.delivery``; a domain that grants none is a named Refused."""
    node: Any = domain.get("delivery") or {}
    for step in FLOOR_SOURCES[key]:
        node = node.get(step) if isinstance(node, dict) else None
    if not _is_int(node):
        raise Refused(f"domain {domain.get('domain_id')} delivery grants no floor for ending.{key} "
                      f"(delivery.{'.'.join(FLOOR_SOURCES[key])}); that parameter cannot be used with this domain")
    return node


def wav_samples(path: Path) -> tuple[int, int]:
    """(sample frames, sample rate) of a PCM WAV; unreadable files are ``Uncertain``."""
    try:
        with wave.open(str(path)) as stream:
            return stream.getnframes(), stream.getframerate()
    except (OSError, wave.Error, EOFError) as error:
        raise Uncertain(f"cannot read WAV {path}: {error}") from error


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_music_bed(bed: Any) -> None:
    """The declared music-bed policy: only what the kit needs to extend and duck the bed."""
    if not isinstance(bed, dict):
        raise Refused("ending.music_bed must be an object")
    known = {"extend", "loop_start_s", "loop_end_s", "crossfade_frames", "duck_db", "duck_attack_frames",
             "duck_release_frames", "duck_under"}
    for key in bed:
        if key not in known:
            raise Refused(f"ending.music_bed: unknown key {key!r} (allowed: {', '.join(sorted(known))})")
    if bed.get("extend") not in MUSIC_EXTEND:
        raise Refused(f"ending.music_bed.extend must be one of {list(MUSIC_EXTEND)}, got {bed.get('extend')!r}")
    for key in ("loop_start_s", "loop_end_s"):
        if key in bed and not (_is_number(bed[key]) and bed[key] >= 0):
            raise Refused(f"ending.music_bed.{key} must be a number >= 0, got {bed[key]!r}")
    for key in ("crossfade_frames", "duck_attack_frames", "duck_release_frames"):
        if key in bed and not (_is_int(bed[key]) and bed[key] >= 0):
            raise Refused(f"ending.music_bed.{key} must be an integer >= 0, got {bed[key]!r}")
    if "duck_db" in bed and not (_is_number(bed["duck_db"]) and bed["duck_db"] > 0):
        raise Refused(f"ending.music_bed.duck_db must be a number > 0 (dB of ducking), got {bed['duck_db']!r}")
    if "duck_under" in bed and bed["duck_under"] != "words":
        raise Refused(f"ending.music_bed.duck_under must be 'words', got {bed['duck_under']!r}")
    if bed["extend"] == "loop_phrase_crossfade":
        if "loop_start_s" not in bed or "loop_end_s" not in bed:
            raise Refused("ending.music_bed: extend loop_phrase_crossfade needs loop_start_s and loop_end_s")
        if bed["loop_end_s"] <= bed["loop_start_s"]:
            raise Refused("ending.music_bed: loop_end_s must be greater than loop_start_s")


def check_params(declared: dict | None, domain: dict) -> None:
    """Validate the optional ending parameters (the schema checks types; this is the engine's own gate).
    The floors are read from ``domain``."""
    ending = declared or {}
    flag = ending.get("derive_timeline")
    if flag is not None and not isinstance(flag, bool):
        raise Refused(f"ending.derive_timeline must be true or false, got {flag!r}")
    for key in FLOOR_SOURCES:
        if key not in ending:
            continue
        floor = domain_floor(domain, key)
        if not (_is_int(ending[key]) and ending[key] >= floor):
            raise Refused(f"ending.{key} must be an integer >= {floor}, got {ending[key]!r}")
    plate = ending.get("end_plate")
    if plate is not None:
        if "placement" in plate and plate["placement"] not in PLATE_PLACEMENTS:
            raise Refused(f"ending.end_plate.placement must be one of {list(PLATE_PLACEMENTS)}, got {plate['placement']!r}")
        after = plate.get("frames_after_card_window")
        if after is not None and not (_is_int(after) and after >= 1):
            raise Refused(f"ending.end_plate.frames_after_card_window must be an integer >= 1, got {after!r}")
    layout = ending.get("logo_disc_layout")
    if layout is not None:
        if not isinstance(layout, dict) or not all(_is_number(v) for v in layout.values()):
            raise Refused("ending.logo_disc_layout must be an object of numbers")
    if "music_bed" in ending:
        check_music_bed(ending["music_bed"])
