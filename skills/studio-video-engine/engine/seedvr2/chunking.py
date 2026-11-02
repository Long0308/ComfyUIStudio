"""Chunk planning for SeedVR2: core windows with context, bounded by the qualified envelope.

Port of the v004 planner's behaviour (core/context windows, the overlap policy checks, the
padded-frame envelope check).  The historical 40-frame cap of the old chunk helper is NOT
ported: the limit is ``geometry.max_raw_segment_frames`` of the recipe.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import Refused
from .recipe import padded_frame_count

OVERLAP_POLICY = "core {core} frames; up to {context} context frames per side"


def build_chunk_plan(total_frames: int, core_frames: int, context_frames: int) -> list[dict]:
    """Consecutive core windows of ``core_frames`` with up to ``context_frames`` either side."""
    if total_frames < 1:
        raise Refused("source has no frames")
    if core_frames < 1:
        raise Refused("core_frames must be positive")
    if context_frames < 0:
        raise Refused("context_frames cannot be negative")
    chunks = []
    for index, core_start in enumerate(range(0, total_frames, core_frames)):
        core_end = min(total_frames, core_start + core_frames)
        before = min(context_frames, core_start)
        after = min(context_frames, total_frames - core_end)
        start, end = core_start - before, core_end + after
        chunks.append({
            "index": index,
            "core_start_frame": core_start,
            "core_end_frame_exclusive": core_end,
            "core_frames": core_end - core_start,
            "context_before_frames": before,
            "context_after_frames": after,
            "segment_start_frame": start,
            "segment_end_frame_exclusive": end,
            "segment_frames": end - start,
            "core_offset_in_segment": core_start - start,
        })
    return chunks


def segment_overlap(left: dict, right: dict) -> dict:
    start = max(left["segment_start_frame"], right["segment_start_frame"])
    end = min(left["segment_end_frame_exclusive"], right["segment_end_frame_exclusive"])
    return {"frames": max(0, end - start), "source_start_frame": start,
            "source_end_frame_exclusive": end}


def plan_chunks(total_frames: int, geometry: dict[str, Any]) -> list[dict]:
    """Chunk records for one source, validated against the recipe geometry."""
    core, context = geometry["core_frames"], geometry["context_frames_each_side"]
    limit, alignment = geometry["max_raw_segment_frames"], geometry["padding_alignment"]
    chunks = build_chunk_plan(total_frames, core, context)
    cursor = 0
    for chunk in chunks:
        if chunk["core_start_frame"] != cursor:
            raise Refused("chunk core plan contains a gap or overlap")
        if chunk["segment_frames"] > limit:
            raise Refused(f"chunk {chunk['index']} exceeds {limit} raw frames: {chunk['segment_frames']}")
        padded = padded_frame_count(chunk["segment_frames"], alignment)
        if padded > limit:
            raise Refused(f"chunk {chunk['index']} exceeds the qualified {limit}-frame envelope")
        chunk["seedvr2_padded_frames"] = padded  # informational: what SeedVR2 pads to
        cursor = chunk["core_end_frame_exclusive"]
    if cursor != total_frames:
        raise Refused("chunk core plan does not cover the complete source")
    _attach_overlaps(chunks, core, context)
    return chunks


def _attach_overlaps(chunks: list[dict], core: int, context: int) -> None:
    for index, chunk in enumerate(chunks):
        previous = segment_overlap(chunks[index - 1], chunk) if index else None
        following = segment_overlap(chunk, chunks[index + 1]) if index + 1 < len(chunks) else None
        if previous and previous["frames"] != (
                chunks[index - 1]["context_after_frames"] + chunk["context_before_frames"]):
            raise Refused("adjacent chunk overlap differs from the context policy")
        if following and following["frames"] != (
                chunk["context_after_frames"] + chunks[index + 1]["context_before_frames"]):
            raise Refused("following chunk overlap differs from the context policy")
        chunk["overlap"] = {
            "policy": OVERLAP_POLICY.format(core=core, context=context),
            "adjacent_cached_overlap_frames": 2 * context if len(chunks) > 1 else 0,
            "with_previous": previous,
            "with_next": following,
        }


def seam_pairs(chunks: list[dict]) -> list[dict]:
    """Adjacent chunk pairs whose restored seam a human or QA stage must inspect."""
    return [{
        "left_chunk": left["chunk_name"],
        "right_chunk": right["chunk_name"],
        "left_core_last_source_frame": left["core_end_frame_exclusive"] - 1,
        "right_core_first_source_frame": right["core_start_frame"],
        "left_expected_core_output_frame_index": left["core_frames"] - 1,
        "right_expected_core_output_frame_index": 0,
        "shared_source_overlap": segment_overlap(left, right),
        "inspection": ("compare the last restored core frame on the left with the first restored "
                       "core frame on the right, plus adjacent frames"),
    } for left, right in zip(chunks, chunks[1:])]


def shot_source_range(shot: dict) -> tuple[int, int] | None:
    """``(start, end_exclusive)`` of a tails plan shot's ``source_range`` (None for a whole-clip shot).

    The chunk windows of such a shot are relative to ``start``; the source file has
    ``source_range.source_frames_total`` frames."""
    rng = shot.get("source_range")
    if rng is None:
        return None
    label = f"{shot.get('shot_id')}: source_range"
    values = [rng.get(k) for k in ("start_frame", "end_frame_exclusive", "source_frames_total")]
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        raise Refused(f"{label} needs integer start_frame, end_frame_exclusive, source_frames_total")
    start, end, total = values
    if not 0 <= start < end <= total:
        raise Refused(f"{label} [{start}, {end}) is not inside the source (0..{total})")
    return start, end
