"""Dependency slices (T-E45 spec 3.3) on the review-config shape: the parts of the inputs a node's output can depend on.

``video_parts`` mirrors ``remotion-kit/lib/segdeps.cjs`` ``videoSlice`` (same part names, so a stale reason reads the
same) but works on the review config.  ``audio_parts`` follows ``audioSlice`` except that word windows are opt-in
(``policy.audio_slice.include_word_windows``).  Both are conservative: they only drop keys named in the policy.
"""

from __future__ import annotations

from typing import Any, Mapping

from . import shape
from .model import Bind, sha, strip

_ENDING_NOT_DISC = ("end_plate", "audio_tail")


def _drop(policy: Mapping[str, Any], block: str) -> frozenset[str]:
    return frozenset(policy[block]["drop_keys"])


def _shot_record(config: dict, shot_id: str, drop: frozenset[str], bind: Bind = None) -> Any:
    return strip(next(d for d in config["dialogue"] if d["id"] == shot_id), drop, bind)


def _transition_span(t: dict, join: int | None) -> tuple[int, int]:
    """Frames the effect can touch; an iris is cut short at the join frame (after it no shot video is drawn)."""
    start = t.get("start", t["boundary"])
    end = max(t.get("end_exclusive", t["boundary"]), t["boundary"] + 1)
    if join is not None and (t.get("renders_as") or t.get("type")) == "iris":
        end = max(min(end, join), start + 1)
    return start, end


def video_parts(config: dict, seg: Mapping[str, Any], policy: Mapping[str, Any], bind: Bind = None) -> dict[str, Any]:
    """The video slice of one segment: global + range + what intersects it + the sha of the files it mounts.

    ``bind`` (``graph.FileBinder``) gives a file reference that carries no sha its content identity."""
    drop = _drop(policy, "video_slice")
    s, e = seg["start"], seg["end_exclusive"]
    parts: dict[str, Any] = {"range": [s, e], "global.fps": shape.fps(config),
                             "global.size": [config.get("width"), config.get("height")],
                             "global.label": config.get("label"), "global.main_frames": shape.main_frames(config),
                             "global.end_hold_frames": config.get("end_hold_frames", 0)}
    join = shape.join_frame(config)
    transitions = [t for t in shape.transitions(config) if shape.overlap(*_transition_span(t, join), s, e)]
    # a window with frames mounts BOTH pictures; a hard cut / carry (empty window) mounts only the shot on screen
    visible = {x for t in transitions if t.get("end_exclusive", 0) > t.get("start", 0)
               for x in (t.get("from"), t.get("to"))} | set(seg.get("shots_visible") or [])
    for shot in shape.shots(config):
        if shape.overlap(*shape.shot_window(config, shot), s, e) or shot["id"] in visible:
            parts[f"shot:{shot['id']}"] = _shot_record(config, shot["id"], drop, bind)
            parts[f"file:picture:{shot['id']}"] = shot["clips"]
    for t in transitions:
        parts[f"transition:{t['id']}"] = strip(t, drop, bind)
    for ev in shape.icons(config):
        if shape.overlap(ev["frame"], ev["frame"] + ev["total_frames"], s, e):
            parts[f"icon:{ev['id']}"] = strip(ev, drop, bind)
    if s < min((x["start"] for x in shape.shots(config)), default=0):
        parts["file:opening"] = (config.get("opening") or {}).get("sha256")
        parts["file:logo"] = (config.get("logo") or {}).get("sha256")
    touched = shape.card_of(config, seg)
    if touched:
        cards = shape.cards(config)
        parts["cards.meta"] = {"count": len(cards), "windows": [[x["start_frame"], x["duration_frames"]] for x in cards]}
        for i in touched:
            parts[f"card:{i}"] = strip(cards[i], drop, bind)
    end = shape.ending(config)
    disc = (end.get("logo_disc") or {}).get("in")
    plate = (end.get("end_plate") or {}).get("start")
    if (isinstance(disc, int) and e > disc) or (isinstance(plate, int) and e > plate) or e > shape.main_frames(config):
        parts["ending.disc"] = strip({k: v for k, v in end.items() if k not in _ENDING_NOT_DISC}, drop, bind)
        parts["file:logo"] = (config.get("logo") or {}).get("sha256")
    if isinstance(plate, int) and e > plate:
        parts["ending.plate"] = strip(end.get("end_plate"), drop, bind)
    return parts


def audio_parts(inputs: Any, policy: Mapping[str, Any], bind: Bind = None) -> dict[str, Any]:
    """Everything the one whole-film mix can depend on; no caption leaf unless the policy says the mix ducks under words."""
    config = inputs.config
    drop = _drop(policy, "audio_slice")
    parts: dict[str, Any] = {"global.fps": shape.fps(config), "global.main_frames": shape.main_frames(config),
                             "global.end_hold_frames": config.get("end_hold_frames", 0),
                             "layout.shots": [[x["id"], x["start"], x["end"]] for x in shape.shots(config)],
                             "layout.cards": [[x["start_frame"], x["duration_frames"]] for x in shape.cards(config)]}
    for shot in shape.shots(config):
        parts[f"file:dialogue:{shot['id']}"] = [shot["wav_sha256"], shot["wav_offset_frames"]]
    for i, card in enumerate(shape.cards(config)):
        parts[f"file:card:{i}"] = (card.get("audio") or {}).get("sha256")
    end_line = config.get("end_line") or {}
    parts["end_line"] = [end_line.get("start_frame"), end_line.get("duration_frames"),
                         (end_line.get("audio") or {}).get("sha256")]
    parts["config.mix"] = strip(config.get("mix") or {}, drop, bind)
    if inputs.mix_plan is not None:
        parts["plan"] = strip(inputs.mix_plan, drop, bind)
    parts["output:mix_wav.sha256"] = inputs.mix_wav_sha256
    if policy["audio_slice"]["include_word_windows"]:
        parts["words"] = [[x["id"], [[w["startF"], w["endF"]] for w in x["words"]]] for x in shape.shots(config)]
    return parts


def words_output(config: dict) -> str:
    """Content hash of what ``timing.words`` produced: every shot's words (text, startF, endF)."""
    return sha([[x["id"], [[w.get("w"), w.get("startF"), w.get("endF")] for w in x["words"]]]
                for x in shape.shots(config)])


def timing_parts(config: dict) -> dict[str, Any]:
    wt = config.get("word_timing") or {}
    parts: dict[str, Any] = {"word_timing.sha256": wt.get("sha256"), "word_timing.schema": wt.get("schema")}
    for shot in shape.shots(config):
        parts[f"file:dialogue:{shot['id']}"] = shot["wav_sha256"]
    return parts


def editorial_parts(config: dict, policy: Mapping[str, Any], bind: Bind = None) -> dict[str, Any]:
    """The blocks ``editorial.build`` writes into the config (its output; the new config already carries them)."""
    drop = _drop(policy, "video_slice")
    return {"words": [[x["id"], strip(x["words"], drop, bind)] for x in shape.shots(config)],
            "transitions": strip(shape.transitions(config), drop, bind), "icon_events": strip(shape.icons(config), drop, bind),
            "cards": strip(shape.cards(config), drop, bind), "ending": strip(shape.ending(config), drop, bind),
            "timeline": [shape.fps(config), shape.main_frames(config), config.get("end_hold_frames", 0)]}
