"""JSON-Schema-subset documents for the three audio recipe families (see ``engine.config.schema``).

``recipes/audio/<name>.json``: ``audio-music`` (YuE2-style graph + sections + style template),
``audio-sfx`` (Stable-Audio-style graph + cue-class table) and ``audio-mix`` (ducking, loudness gate).
Every numeric default of the film-mix standard lives in a recipe; the limits it may not loosen are the
constants of ``engine.audio.limits``.
"""

from __future__ import annotations

SCHEMA_ID = "jjv/audio-recipe/v1"
_SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_STR = {"type": "string", "minLength": 1}
_NUM = {"type": "number"}
_SLOT = {"type": "array", "minItems": 1, "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                                   "items": {"type": "string", "minLength": 1}}}


def _slots(names: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": names,
            "properties": {name: _SLOT for name in names}}


_MODEL = {"type": "object", "additionalProperties": False,
          "required": ["role", "path", "bytes", "sha256", "licence_id", "graph_binding"],
          "properties": {
              "role": _STR, "path": _STR, "bytes": {"type": "integer", "minimum": 1}, "sha256": _SHA,
              "licence_id": _STR,
              "graph_binding": {"type": "object", "additionalProperties": False, "required": ["node", "input", "value"],
                                "properties": {"node": _STR, "input": _STR, "value": _STR}}}}
_LICENCE = {"type": "object", "additionalProperties": False, "required": ["name", "url", "text_sha256", "relied_on"],
            "properties": {"name": _STR, "url": _STR, "text_sha256": _SHA, "relied_on": _STR, "note": _STR}}
_OUTPUT = {"type": "object", "additionalProperties": False, "required": ["node"], "properties": {"node": _STR}}

_COMFY_COMMON = {
    "schema": {"const": SCHEMA_ID}, "recipe_id": {"type": "string", "pattern": "^audio/[a-z0-9][a-z0-9._-]*$"},
    "domain": _STR, "note": {"type": "string"}, "engine": _STR,
    "models": {"type": "array", "minItems": 1, "items": _MODEL},
    "licences": {"type": "object", "minProperties": 1, "additionalProperties": _LICENCE},
    "graph": {"type": "object", "minProperties": 1}, "output": _OUTPUT,
    "sample_rate": {"type": "integer", "minimum": 8000}, "seed_base": {"type": "integer", "minimum": 0},
}
_COMFY_REQUIRED = ["schema", "recipe_id", "family", "domain", "engine", "models", "licences", "graph", "slots",
                   "output", "sample_rate", "seed_base"]

_DERIVATION = {
    "type": "object", "additionalProperties": False,
    "required": ["energy", "tempo", "keys", "instrument_palettes", "default_palette"],
    "properties": {
        "energy": {"type": "object", "additionalProperties": False,
                   "required": ["calm_max_wps", "lively_min_wps", "default_by_section"],
                   "properties": {"calm_max_wps": {"type": "number", "exclusiveMinimum": 0},
                                  "lively_min_wps": {"type": "number", "exclusiveMinimum": 0},
                                  "default_by_section": {"type": "object", "minProperties": 1,
                                                         "additionalProperties": {"enum": ["calm", "gentle", "lively"]}}}},
        "tempo": {"type": "object", "additionalProperties": False, "required": ["min", "max", "by_energy"],
                  "properties": {"min": {"type": "integer", "minimum": 40}, "max": {"type": "integer", "maximum": 240},
                                 "by_energy": {"type": "object", "additionalProperties": False,
                                               "required": ["calm", "gentle", "lively"],
                                               "properties": {k: {"type": "integer"} for k in ("calm", "gentle", "lively")}}}},
        "keys": {"type": "array", "minItems": 1, "items": _STR},
        "instrument_palettes": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "instruments"],
            "properties": {"id": _STR, "instruments": _STR, "keywords": {"type": "array", "items": _STR},
                           "energy": {"type": "array", "items": {"enum": ["calm", "gentle", "lively"]}}}}},
        "default_palette": _STR}}

MUSIC_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": _COMFY_REQUIRED + [
        "style_template", "lyrics", "max_duration_s", "loop_extend", "derivation", "default_brief", "vocal_gate"],
    "properties": {**_COMFY_COMMON, "family": {"const": "audio-music"},
                   "slots": _slots(["style", "lyrics", "seed", "seconds", "filename_prefix"]),
                   "style_template": _STR, "lyrics": _STR, "max_duration_s": {"type": "number", "exclusiveMinimum": 0},
                   "loop_extend": {"type": "object", "additionalProperties": False,
                                   "required": ["beats_per_bar", "intro_bars", "window_bars", "crossfade_s", "target_extra_s"],
                                   "properties": {"beats_per_bar": {"type": "integer", "minimum": 1},
                                                  "intro_bars": {"type": "integer", "minimum": 0},
                                                  "window_bars": {"type": "integer", "minimum": 1},
                                                  "crossfade_s": {"type": "number", "exclusiveMinimum": 0},
                                                  "target_extra_s": {"type": "number", "minimum": 0}}},
                   "derivation": _DERIVATION,
                   "default_brief": {"type": "object", "minProperties": 1},
                   "vocal_gate": {"type": "object", "additionalProperties": False, "required": ["limit_db", "vocals_file"],
                                  "properties": {"limit_db": {"type": "number", "maximum": 0}, "vocals_file": _STR,
                                                 "window_limit_dbfs": {"type": "number", "maximum": 0},
                                                 "timeout_s": {"type": "number", "exclusiveMinimum": 0}}}}}

_CLASS = {"type": "object", "additionalProperties": False, "required": ["prompt", "seconds", "gain_db"],
          "properties": {
              "event": {"enum": ["keyword", "icon", "card", "transition", "anchor", "bed"]},
              "keywords": {"type": "array", "items": _STR}, "types": {"type": "array", "items": _STR},
              "anchors": {"type": "array", "items": {"type": "object", "required": ["path"],
                                                     "properties": {"path": _STR, "offset_frames": {"type": "integer"}}}},
              "prompt": _STR, "seconds": {"type": "number", "minimum": 1.0}, "gain_db": _NUM, "pan": _NUM,
              "offset_s": _NUM, "lead_frames": {"type": "integer", "minimum": 0}, "optional": {"type": "boolean"},
              "peak_dbfs": _NUM, "loop": {"type": "boolean"}, "span": {"enum": ["shot"]}, "repeat": {"type": "boolean"},
              "repeat_gap_s": {"type": "number", "exclusiveMinimum": 0}}}

SFX_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": _COMFY_REQUIRED + [
        "negative_prompt", "cue_classes", "postprocess"],
    "properties": {**_COMFY_COMMON, "family": {"const": "audio-sfx"},
                   "slots": _slots(["prompt", "negative", "seed", "seconds", "filename_prefix"]),
                   "negative_prompt": _STR, "cue_classes": {"type": "object", "minProperties": 1,
                                                            "additionalProperties": _CLASS},
                   "negation_words": {"type": "array", "items": _STR},
                   "postprocess": {"type": "object", "additionalProperties": False,
                                   "required": ["trim_threshold_dbfs", "peak_dbfs", "fade_in_s", "fade_out_s"],
                                   "properties": {"trim_threshold_dbfs": _NUM, "peak_dbfs": _NUM,
                                                  "fade_in_s": {"type": "number", "minimum": 0},
                                                  "fade_out_s": {"type": "number", "minimum": 0}}}}}

MIX_SCHEMA: dict = {
    "type": "object", "additionalProperties": False,
    "required": ["schema", "recipe_id", "family", "domain", "profile", "sample_rate", "music", "duck", "sfx", "speech",
                 "loudness", "pumping", "remux", "speech_buses"],
    "properties": {
        "selectable_by_default": {"type": "boolean"},
        "pinned_from": {"type": "string"},
        "speech_buses": {"type": "object", "minProperties": 1, "required": ["*"], "additionalProperties": {
            "type": "object", "additionalProperties": False, "required": ["mode"],
            "properties": {"mode": {"enum": ["solve", "fixed"]}, "gain_db": _NUM, "min_db": _NUM, "max_db": _NUM}}},
        "schema": {"const": SCHEMA_ID}, "recipe_id": {"type": "string", "pattern": "^audio/[a-z0-9][a-z0-9._-]*$"},
        "family": {"const": "audio-mix"}, "domain": _STR, "note": {"type": "string"},
        "profile": {"enum": ["cinema", "legacy"]}, "sample_rate": {"type": "integer", "minimum": 8000},
        "music": {"type": "object", "additionalProperties": False,
                  "required": ["gain_db", "section_gains_db", "loop_crossfade_s", "fade_in_s", "fade_out_s",
                               "after_brand_voice_fade_in_s"],
                  "properties": {"gain_db": _NUM, "loop_crossfade_s": {"type": "number", "minimum": 0},
                                 "section_gains_db": {"type": "object", "additionalProperties": _NUM},
                                 "after_brand_voice_fade_in_s": {"type": "number", "minimum": 0},
                                 "fade_in_s": {"type": "number", "minimum": 0},
                                 "fade_out_s": {"type": "number", "minimum": 0}}},
        "duck": {"type": "object", "additionalProperties": False,
                 "required": ["depth_db", "attack_s", "release_s", "merge_gap_s"],
                 "properties": {"depth_db": {"type": "number", "maximum": 0},
                                "attack_s": {"type": "number", "minimum": 0}, "release_s": {"type": "number", "minimum": 0},
                                "merge_gap_s": {"type": "number", "minimum": 0}}},
        "sfx": {"type": "object", "additionalProperties": False, "required": ["duck_db", "avoid_speech_s", "default_enabled"],
                "properties": {"duck_db": {"type": "number", "maximum": 0}, "default_enabled": {"type": "boolean"},
                               "default_on_decision": {"type": "string", "minLength": 1},
                               "avoid_speech_s": {"type": "number", "minimum": 0}}},
        "speech": {"type": "object", "additionalProperties": False, "required": ["threshold_dbfs", "window_ms"],
                   "properties": {"threshold_dbfs": {"type": "number", "maximum": 0},
                                  "window_ms": {"type": "integer", "minimum": 1, "maximum": 100}}},
        "loudness": {"type": "object", "additionalProperties": False,
                     "required": ["enabled", "target_lufs", "tolerance_lu", "true_peak_max_dbtp", "max_section_jump_lu",
                                  "bed_gain_min_db", "bed_gain_max_db", "max_bed_step_db", "max_iterations",
                                  "ramp_s", "min_measure_s", "bed_only", "brand_voice"],
                     "properties": {"enabled": {"type": "boolean"}, "target_lufs": _NUM,
                                    "bed_only": {"type": "object", "additionalProperties": False,
                                                 "required": ["target_lufs", "tolerance_lu", "below_speech_lu", "min_s"],
                                                 "properties": {"target_lufs": _NUM, "min_s": {"type": "number", "minimum": 0.5}, "below_speech_lu": {"type": "number", "minimum": 0},
                                                                "tolerance_lu": {"type": "number", "exclusiveMinimum": 0}}},
                                    "brand_voice": {"type": "object", "additionalProperties": False,
                                                    "required": ["target_lufs", "tolerance_lu"],
                                                    "properties": {"target_lufs": _NUM,
                                                                   "tolerance_lu": {"type": "number", "exclusiveMinimum": 0}}},
                                    "tolerance_lu": {"type": "number", "exclusiveMinimum": 0},
                                    "true_peak_max_dbtp": _NUM,
                                    "max_section_jump_lu": {"type": "number", "exclusiveMinimum": 0},
                                    "bed_gain_min_db": _NUM, "bed_gain_max_db": _NUM,
                                    "max_bed_step_db": {"type": "number", "exclusiveMinimum": 0},
                                    "max_iterations": {"type": "integer", "minimum": 1, "maximum": 16},
                                    "ramp_s": {"type": "number", "minimum": 0},
                                    "min_measure_s": {"type": "number", "minimum": 0.4}}},
        "pumping": {"type": "object", "additionalProperties": False, "required": ["enabled", "max_swing_db", "min_window_s", "gap_s"],
                    "properties": {"enabled": {"type": "boolean"}, "max_swing_db": {"type": "number", "exclusiveMinimum": 0},
                                   "min_window_s": {"type": "number", "minimum": 0.05},
                                   "gap_s": {"type": "number", "minimum": 0.1}}},
        "remux": {"type": "object", "additionalProperties": False, "required": ["audio_codec", "audio_bitrate"],
                  "properties": {"audio_codec": _STR, "audio_bitrate": _STR,
                                    "tracks": {"type": "array", "minItems": 1, "items": {
                                        "type": "object", "additionalProperties": False, "required": ["stem", "title", "codec"],
                                        "properties": {"stem": {"enum": ["final", "dialogue", "music", "sfx", "brand_voice"]},
                                                       "title": _STR, "codec": _STR, "bitrate": _STR, "language": _STR,
                                                       "default": {"type": "boolean"}, "verify_exact": {"type": "boolean"}}}}}},
    },
}

SCHEMAS = {"audio-music": MUSIC_SCHEMA, "audio-sfx": SFX_SCHEMA, "audio-mix": MIX_SCHEMA}
