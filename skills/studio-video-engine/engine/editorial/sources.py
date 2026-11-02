"""Audio-bound sources of the review config: dialogue rows, WAV bindings, cards, silence, ending.

Rule violations are ``Refused``; an input that cannot be found or read is ``Uncertain``.  Every file
must live inside the episode root unless the caller allow-lists it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file
from ..qa.scope import require_scoped
from . import captions, end_card, wavs
from .timeline import Timeline


@dataclass(frozen=True)
class Context:
    root: Path
    allow: tuple
    rel: Callable[[Path], str]

    def file(self, relative: str, label: str) -> Path:
        """A scoped, existing file; a missing one is an unreadable input (Uncertain)."""
        path = require_scoped(self.root / relative, self.root, self.allow, label)
        if not path.is_file():
            raise Uncertain(f"{label} not found: {path.name}")
        return path


def _verify_binding(ctx: Context, shot) -> tuple[dict, Path]:
    """Receipt-WAV rule: the file on disk must hash to the sha256 shots.json binds."""
    binding = shot.wav_binding
    path = ctx.file(binding["path"], f"{shot.shot} bound WAV")
    actual = sha256_file(path)
    if actual != binding["sha256"]:
        raise Refused(f"{shot.shot}: WAV {binding['path']} hashes to {actual}, shots.json binds {binding['sha256']}")
    return {"path": binding["path"], "sha256": actual}, path


OFFSET_TOLERANCE = 1e-6  # frames; offset_s x fps must be integral within this


def offset_frames(shot, fps: int) -> int:
    """shots.json ``wav_binding.offset_s`` in whole frames; a sub-frame remainder is refused (it would
    be silently dropped by rounding, moving the WAV binding away from what the file declares)."""
    seconds = shot.wav_binding["offset_s"]
    exact = seconds * fps
    if not math.isfinite(exact) or abs(exact - round(exact)) > OFFSET_TOLERANCE:
        raise Refused(f"{shot.shot}: wav_binding.offset_s {seconds} is not a whole number of frames at {fps} fps "
                      f"({exact:.4f} frames); a sub-frame offset cannot be placed")
    return int(round(exact))


def _segment(shot, fps: int, binding: dict) -> dict:
    audio = {**binding, "offset_frames": offset_frames(shot, fps)}
    return {"shot": shot.shot, "start_frame": shot.start, "duration_frames": shot.delivery_frames,
            "native_frames": shot.editorial_frames,
            "clip": {"path": shot.clip["path"], "sha256": shot.clip["sha256"]}, "audio": audio}


def _silence_spec(shot, specs: dict) -> dict | None:
    spec = specs.get(shot.shot)
    if spec is not None and (spec["start_frame"], spec["end_frame_exclusive"]) != (shot.start, shot.end):
        raise Refused(f"expect_silent for {shot.shot}: window f{spec['start_frame']}-f{spec['end_frame_exclusive']} "
                      f"is not the shot's window f{shot.start}-f{shot.end}")
    return spec


def _check_silence(shot, wav_path: Path, spec: dict | None, words: list[dict]) -> dict | None:
    """Silent <=> declared <=> no words in the window; speaking <=> words in the window."""
    inside = [w for w in words if shot.start <= w["startF"] < shot.end]
    if wavs.is_silent(wav_path):
        if spec is None:
            raise Refused(f"{shot.shot}: its bound WAV is silent but no expect_silent window is declared for it")
        if inside:
            raise Refused(f"{shot.shot}: silent WAV but the word timing has {len(inside)} word(s) inside its window")
        return {"start_frame": spec["start_frame"], "end_frame_exclusive": spec["end_frame_exclusive"],
                "max_rms": spec["max_rms"]}
    if spec is not None:
        raise Refused(f"{shot.shot}: expect_silent is declared but its bound WAV carries signal")
    if not inside:
        raise Refused(f"{shot.shot}: its bound WAV is audible but the word timing has no word inside its window")
    return None


def check_offset(logical: str, entry: dict, segments: list[dict]) -> None:
    """One source of truth for where the WAV sits in its window: shots.json ``wav_binding.offset_s``
    (it is the one bound to the receipt WAV and it places the WAV binding qa av verifies).  The word
    timing's ``audio.offset_frames`` (default 0) must agree with it, otherwise the icons would pop
    at a different time than the audio they are anchored to."""
    declared = (entry.get("audio") or {}).get("offset_frames", 0)
    if isinstance(declared, bool) or not isinstance(declared, int):
        raise Refused(f"{logical}: word timing audio.offset_frames must be an integer, got {declared!r}")
    bound = segments[0]["audio"]["offset_frames"]
    if declared != bound:
        raise Refused(f"{logical}: word timing audio.offset_frames is {declared} but shots.json wav_binding.offset_s "
                      f"of {segments[0]['shot']} is {bound} frame(s); shots.json is the source of truth, "
                      "make the two agree")


def _check_timing_audio(ctx: Context, logical: str, entry: dict, shots: list, paths: list[Path],
                        segments: list[dict]) -> None:
    """The WAV the words were timed on must be (or be provably made of) the receipt WAVs."""
    audio = entry.get("audio") or {}
    if len(shots) == 1:
        timed = audio.get("sha256")
        if timed is None:
            raise Refused(f"{logical}: a one-shot dialogue's word timing must carry audio.sha256 (the WAV it was "
                          f"measured on), equal to its receipt WAV {segments[0]['audio']['sha256']}")
        if timed != segments[0]["audio"]["sha256"]:
            raise Refused(f"{logical}: word timing was measured on WAV {timed}, "
                          f"but the receipt binds {segments[0]['audio']['sha256']}")
        return
    if not audio.get("path") or not audio.get("sha256"):
        raise Refused(f"{logical}: a multi-segment dialogue needs audio.path and audio.sha256 in the word timing")
    full = ctx.file(audio["path"], f"{logical} timing WAV")
    if sha256_file(full) != audio["sha256"]:
        raise Refused(f"{logical}: the timing WAV {audio['path']} does not hash to its declared sha256")
    full_params, full_pcm = wavs.read_pcm(full)
    parts = [wavs.read_pcm(path) for path in paths]
    if any(params != full_params for params, _ in parts) or b"".join(data for _, data in parts) != full_pcm:
        raise Refused(f"{logical}: the timing WAV is not the concatenation of its bound segment WAVs "
                      f"({', '.join(shot.shot for shot in shots)})")


def dialogue(ctx: Context, timeline: Timeline, entries: dict, fps: int,
             silent_specs: dict) -> tuple[list[dict], list[dict]]:
    """Dialogue rows (validated words) and the WAV bindings of every physical shot."""
    rows: list[dict] = []
    bindings: list[dict] = []
    declared_seen: set[str] = set()
    for logical in dict.fromkeys(s.logical for s in timeline.shots):
        entry = entries[logical]
        words = captions.caption_words(entry)
        shots = [s for s in timeline.shots if s.logical == logical]
        segments, paths = [], []
        for position, shot in enumerate(shots):
            audio, path = _verify_binding(ctx, shot)
            segments.append(_segment(shot, fps, audio))
            paths.append(path)
            spec = _silence_spec(shot, silent_specs)
            silent = _check_silence(shot, path, spec, words)
            if silent is not None and segments[-1]["audio"]["offset_frames"] != 0:
                raise Refused(f"{shot.shot}: a silent WAV cannot have a nonzero offset (its placement is unprovable, "
                              "so its binding must start exactly at its expect_silent window)")
            if position > 0 and segments[-1]["audio"]["offset_frames"] != 0:
                raise Refused(f"{shot.shot}: a non-first segment of the multi-segment dialogue {logical!r} may not "
                              "have a nonzero wav_binding.offset_s: the word timing carries one offset per dialogue "
                              "(its first segment), so the captions and icons could not follow a later segment's WAV")
            if spec is not None:
                declared_seen.add(shot.shot)
            start = shot.start + segments[-1]["audio"]["offset_frames"]
            bindings.append({"name": f"dlg {shot.shot}", "kind": "dialogue", "path": audio["path"],
                             "sha256": audio["sha256"], "start_frame": start,
                             **({"expect_silent": silent} if silent else {})})
        check_offset(logical, entry, segments)
        _check_timing_audio(ctx, logical, entry, shots, paths, segments)
        rows.append({"id": logical, "speaker": entry["speaker"], "start_frame": entry["start_frame"],
                     "duration_frames": entry["end_frame_exclusive"] - entry["start_frame"],
                     "end_frame_exclusive": entry["end_frame_exclusive"], "speech_text": entry["speech_text"],
                     "timing_audio": ({"path": entry["audio"]["path"], "sha256": entry["audio"]["sha256"]}
                                      if (entry.get("audio") or {}).get("sha256") else None),
                     "segments": segments, "words": words})
    unknown = sorted(set(silent_specs) - declared_seen)
    if unknown:
        raise Refused(f"expect_silent names shot(s) that are not in the timeline: {unknown}")
    return rows, bindings


def cards(ctx: Context, declared: list[dict]) -> tuple[list[dict], list[dict]]:
    rows, bindings = [], []
    for card in declared:
        path = ctx.file(card["audio"]["path"], f"card {card['term']!r} WAV")
        if sha256_file(path) != card["audio"]["sha256"]:
            raise Refused(f"card {card['term']!r}: WAV sha256 differs from the declared one")
        if wavs.is_silent(path):
            raise Refused(f"card {card['term']!r}: its WAV is silent, its start could not be verified")
        rows.append({"term": card["term"], "start_frame": card["start_frame"],
                     "duration_frames": card["duration_frames"], "audio": dict(card["audio"])})
        bindings.append({"name": f"voc {card['term']}", "kind": "card", "path": card["audio"]["path"],
                         "sha256": card["audio"]["sha256"], "start_frame": card["start_frame"]})
    return rows, bindings


def ending(ctx: Context, document: dict, timeline: Timeline, declared_cards: list[dict]) -> dict[str, Any]:
    declared = document.get("ending")
    plate = (declared or {}).get("end_plate")
    check = None
    if plate is not None:
        if not declared_cards:
            raise Refused("ending.end_plate needs declared cards (its start is measured on the last card's WAV)")
        last = declared_cards[-1]
        check = end_card.check_end_plate(plate["start"], last["start_frame"],
                                         ctx.file(last["audio"]["path"], "last card WAV"), timeline.fps,
                                         placement=plate.get("placement", "speech_end"),
                                         last_card_end=last["start_frame"] + last["duration_frames"])
    logo = (declared or {}).get("logo")
    if logo is not None and sha256_file(ctx.file(logo["path"], "ending.logo")) != logo["sha256"]:
        raise Refused(f"ending.logo {logo['path']!r}: sha256 differs from the declared one")
    return end_card.build_ending(declared, main_frames=timeline.main_frames,
                                 end_card_frames=timeline.end_card_frames, plate_check=check)
