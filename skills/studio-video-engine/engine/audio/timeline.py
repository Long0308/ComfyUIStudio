"""The film length every audio verb derives from (never squeezed to fit a clip).

``--review-config`` (an engine-built or hand-built review config: ``fps`` + ``total_frames``) is the
authoritative length of a cut under review; without it the episode timeline decides (main film + end card).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from ..config.loader import ResolvedConfig
from ..config.rules import timeline_frames
from ..core.errors import Refused
from ..core.io import read_json


class ContractMismatch(Refused):
    """The film length or the section layout contradicts the episode DELIVERY CONTRACT (``episode.contract``)."""


# audio section name -> the contract section kind whose first row starts it
_CONTRACT_KIND = {"dialogue": "dialogue", "logo_hold": "logo_hold", "outro_cards": "vocab_card", "end_plate": "end_plate"}


def _check_total(config: ResolvedConfig, frames: int, source: str) -> None:
    contract = config.episode.get("contract")
    if contract is not None and frames != contract["total_frames"]:
        raise ContractMismatch(f"audio timeline {frames} f ({source}) != the episode contract total_frames "
                               f"{contract['total_frames']} f (main {contract['main_frames']} + end card "
                               f"{contract['end_card_frames']}); fix the cut or change the contract with `jjv config contract`")


def contract_starts(contract: dict) -> dict[str, int]:
    """First start frame of every section kind in the contract (rows are in film order)."""
    starts: dict[str, int] = {}
    cursor = 0
    for row in contract["sections"]:
        starts.setdefault(row["kind"], cursor)
        cursor += row["frames"]
    return starts


def check_sections(config: ResolvedConfig, rows: list[dict]) -> None:
    """Every derived audio section must start where the contract's section of that kind starts."""
    contract = config.episode.get("contract")
    if contract is None:
        return
    starts = contract_starts(contract)
    for row in rows:
        kind = _CONTRACT_KIND.get(row["name"])
        if kind is None:
            continue
        if kind not in starts:
            raise ContractMismatch(f"audio section {row['name']!r} has no {kind} section in the episode contract")
        if row["start_frame"] != starts[kind]:
            raise ContractMismatch(f"audio section {row['name']!r} starts f{row['start_frame']} but the contract's {kind} "
                                   f"starts f{starts[kind]}")


def checked_sections(config: ResolvedConfig, rows: list[dict]) -> list[dict]:
    """``rows`` after :func:`check_sections` (so a call site wraps its derivation in one call)."""
    check_sections(config, rows)
    return rows


def samples_for_frames(frames: int, fps: int | Fraction, rate: int) -> int:
    """Whole samples for ``frames`` at ``fps``; refuses a length that is not a whole sample count."""
    exact = Fraction(frames) * Fraction(rate) / Fraction(fps)
    if exact.denominator != 1:
        raise Refused(f"{frames} frames at {fps} fps is not a whole number of samples at {rate} Hz")
    return int(exact)


def resolve(config: ResolvedConfig, review_config: dict | None, rate: int, total_frames: int | None = None) -> dict:
    """``{fps, total_frames, total_samples, duration_s, source}``.

    Length: ``total_frames`` (an explicit override), else the review config's ``total_frames_with_endlogo`` (the
    picture file including its end-logo tail), else its ``total_frames``, else the episode timeline."""
    if review_config is not None:
        fps, source = review_config.get("fps"), "review-config"
        frames = review_config.get("total_frames_with_endlogo", review_config.get("total_frames"))
        if total_frames is not None:
            frames, source = total_frames, "--total-frames"
    else:
        fps = config.domain["frame_rates"]["delivery_fps"]
        frames = timeline_frames(config.episode, config.domain)["total_frames"]
        source = "episode.timeline"
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        raise Refused(f"timeline fps must be a positive integer, got {fps!r}")
    if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
        raise Refused(f"timeline total_frames must be a positive integer, got {frames!r}")
    if review_config is None and total_frames is not None:
        frames, source = total_frames, "--total-frames"
    _check_total(config, frames, source)
    samples = samples_for_frames(frames, fps, rate)
    return {"fps": fps, "total_frames": frames, "total_samples": samples, "sample_rate": rate,
            "duration_s": samples / rate, "source": source}


def load_review_config(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    document = read_json(Path(path))
    if not isinstance(document, dict):
        raise Refused(f"review config {path} is not a JSON object")
    return document
