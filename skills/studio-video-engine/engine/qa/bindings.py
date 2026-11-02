"""Bindings of ``jjv qa av``: which WAVs are verified at which start, and the ``expect_silent`` rules.

``wav_bindings`` (engine config) is authoritative; hand-built ``dialogue[].audio`` / ``outro_cards[].audio``
rows are only accepted when they agree with it (see ``_check_hand_built_agree``).  Every rule violation is a
``Refused`` (exit 1), never a KeyError.
"""

from __future__ import annotations

import math
import posixpath
from dataclasses import dataclass
from typing import Any

from ..config.loader import SKILL_ROOT
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import read_json

# Upper bound of expect_silent.max_rms (RMS, full scale = -26 dBFS).  It is the SAME number as
# ``maximum`` of ``silent_window``/``silent_bound`` in schemas/boundaries.schema.json (a test pins the
# parity).  Provenance (measured on the reference episode, see its engine/boundaries.README.md): the
# quietest dialogue WAV has RMS 0.0731 and the silent-window bed 0.0279; a bound above 0.05 could let a
# quiet line ride on the bed.
SILENT_MAX_RMS_CEILING = 0.05
BOUNDARIES_SCHEMA = SKILL_ROOT / "schemas" / "boundaries.schema.json"
@dataclass(frozen=True)
class Binding:
    name: str
    path: str
    sha256: str
    start_frame: int
    expect_silent: dict | None = None


def _bound_sha(row: dict, name: str) -> str:
    sha = row.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise Refused(f"binding {name!r} has no sha256: a WAV that is not hash-bound to its receipt "
                      "cannot be verified (receipt-WAV rule)")
    return sha


def _frame(value: Any, label: str) -> int:
    """A frame number must be a true integer: 240.9 would silently truncate to 240."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused(f"{label} must be an integer frame number, got {value!r}")
    return value


def _field(row: Any, key: str, label: str) -> Any:
    if not isinstance(row, dict) or key not in row:
        raise Refused(f"{label} is missing {key!r}")
    return row[key]


def check_silent_window(spec: Any, label: str) -> dict:
    """Validate one ``expect_silent`` window (``silent_bound`` of the boundaries schema) so a malformed
    one is a rule violation (exit 1), never a KeyError.  Returns the window unchanged."""
    schema = read_json(BOUNDARIES_SCHEMA)
    bound = {"$defs": schema["$defs"], "$ref": "#/$defs/silent_bound"}
    errors = validate(spec, bound, label="expect_silent")
    if errors:
        raise Refused(f"{label}: expect_silent is invalid: " + "; ".join(errors))
    if not math.isfinite(spec["max_rms"]):
        raise Refused(f"{label}: expect_silent.max_rms must be finite, got {spec['max_rms']!r}")
    if spec["end_frame_exclusive"] <= spec["start_frame"]:
        raise Refused(f"{label}: expect_silent window f{spec['start_frame']}-f{spec['end_frame_exclusive']} is empty")
    if spec["max_rms"] > SILENT_MAX_RMS_CEILING:
        raise Refused(f"{label}: expect_silent.max_rms {spec['max_rms']} is above the engine ceiling "
                      f"{SILENT_MAX_RMS_CEILING}")
    return spec


def normalise_path(path: str) -> str:
    """Comparable form of an episode-relative path: forward slashes, no ``./``, ``//`` or ``..``."""
    return posixpath.normpath(str(path).replace("\\", "/"))


def _rows(config: dict, key: str) -> list:
    value = config.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise Refused(f"config.{key} must be a list, got {type(value).__name__}")
    return value


def _require_audio_object(audio: Any, name: str) -> None:
    """A present ``audio`` must be an object.  ``null`` is refused too (decision): "no audio" is expressed by
    OMITTING the key; an explicit null/""/0/[]/false is indistinguishable from a blanked-out row that would
    otherwise drop its WAV from the verification and still PASS."""
    if not isinstance(audio, dict):
        raise Refused(f"{name}: audio must be an object with path and sha256, got {audio!r} "
                      "(omit the key for a row without audio; a falsy value is not skipped)")


def _hand_built(config: dict) -> list[Binding]:
    """The ``dialogue[].audio`` + ``outro_cards[].audio`` rows (same start rule: start_frame + offset).
    A malformed row is ``Refused`` (exit 1), never a KeyError/AttributeError."""
    rows: list[Binding] = []
    for index, entry in enumerate(_rows(config, "dialogue")):
        where = f"dialogue[{index}]"
        if not isinstance(entry, dict):
            raise Refused(f"{where} must be an object, got {type(entry).__name__}")
        if "audio" in entry:  # a PRESENT key is a row, whatever its value: never skipped for being falsy
            audio = entry["audio"]
            name = f"dlg {_field(entry, 'id', where)}"
            _require_audio_object(audio, name)
            start = _frame(_field(entry, "start_frame", name), f"{name} start_frame")
            offset = _frame(audio["offset_frames"] if "offset_frames" in audio else 0, f"{name} offset_frames")
            rows.append(Binding(name, str(_field(audio, "path", f"{name} audio")), _bound_sha(audio, name),
                                start + offset))
    for index, card in enumerate(_rows(config, "outro_cards")):
        where = f"outro_cards[{index}]"
        if not isinstance(card, dict):
            raise Refused(f"{where} must be an object, got {type(card).__name__}")
        if "audio" in card:
            audio = card["audio"]
            name = f"voc {_field(card, 'term', where)}"
            _require_audio_object(audio, name)
            rows.append(Binding(name, str(_field(audio, "path", f"{name} audio")), _bound_sha(audio, name),
                                _frame(_field(card, "start_frame", name), f"{name} start_frame")))
    return rows


def _check_hand_built_agree(config: dict, explicit: list) -> None:
    """``wav_bindings`` is authoritative.  Hand-built ``dialogue[].audio`` / ``outro_cards[].audio`` rows may
    sit beside it (the engine config carries the card WAVs in both places) but each must be one of the
    bindings, same path (compared normalised), sha256 and start frame.  They are not unioned: a WAV declared
    only in the hand-built block would otherwise be silently skipped (never verified), and a disagreeing copy
    would hide which start is the real one."""
    bound: dict = {}
    for row in explicit:
        if isinstance(row, dict) and "path" in row:
            key = (normalise_path(row["path"]), row.get("sha256"))
            bound.setdefault(key, []).append(row.get("start_frame"))
    for hand in _hand_built(config):
        starts = bound.get((normalise_path(hand.path), hand.sha256))
        if starts is None:
            raise Refused(f"{hand.name!r} ({hand.path}) is declared under dialogue/outro_cards audio but is not in "
                          "config.wav_bindings: with wav_bindings present only those are verified, so it would be "
                          "silently skipped (add it to wav_bindings or drop the hand-built row)")
        if hand.start_frame not in starts:
            raise Refused(f"{hand.name!r} starts at f{hand.start_frame} in the hand-built rows but config.wav_bindings "
                          f"binds {hand.path} at {starts}: the two must agree")


ENGINE_CONFIG_SCHEMA_PREFIX = "jjv/review-config/"  # engine/editorial/build.py CONFIG_SCHEMA (a test pins it)


def is_engine_config(config: dict) -> bool:
    """True for a config produced by ``jjv editorial build-config``: it carries the engine schema string, or
    ``inputs.boundaries_sha256``, or engine-shaped dialogue rows (a ``timing_audio`` key, which hand-built
    rows do not have; ``segments`` is NOT a marker, hand-built rows carry it too), so deleting one marker does
    not turn it into a "hand-built" config."""
    schema = config.get("schema")
    if isinstance(schema, str) and schema.startswith(ENGINE_CONFIG_SCHEMA_PREFIX):
        return True
    inputs = config.get("inputs")
    if isinstance(inputs, dict) and "boundaries_sha256" in inputs:
        return True
    rows = config.get("dialogue")
    return isinstance(rows, list) and any(isinstance(r, dict) and "timing_audio" in r for r in rows)


def bindings_from_config(config: dict) -> list[Binding]:
    """The WAVs to locate (see ``resolve_bindings`` for the rule)."""
    return resolve_bindings(config)[0]


def resolve_bindings(config: dict) -> tuple[list[Binding], str]:
    """(bindings, source) with source ``wav_bindings`` or ``hand_built``.

    A PRESENT ``wav_bindings`` key must be a non-empty list (null, ``[]`` and non-lists are ``Refused``, never
    a silent fall back).  An engine-built config REQUIRES it (absent is ``Refused``): otherwise deleting the key
    would verify only the outro-card rows and still PASS.  The hand-built fallback is only for configs that do
    not carry an engine marker."""
    if "wav_bindings" not in config and is_engine_config(config):
        raise Refused("config is an engine-built review config (it carries the engine schema/inputs/timing_audio) but "
                      "has no wav_bindings: they are required, a fall back to the hand-built audio rows would "
                      "verify only the outro cards")
    if "wav_bindings" in config:
        explicit = config["wav_bindings"]
        if not isinstance(explicit, list) or not explicit:
            raise Refused(f"config.wav_bindings must be a non-empty list, got {explicit!r}")
        out: list[Binding] = []
        _check_hand_built_agree(config, explicit)
        for index, row in enumerate(explicit):
            where = f"wav_bindings[{index}]"
            name = str(_field(row, "name", where))
            path = str(_field(row, "path", f"binding {name!r}"))
            start = _frame(_field(row, "start_frame", f"binding {name!r}"), f"binding {name!r} start_frame")
            spec = row.get("expect_silent")
            if spec is not None:
                check_silent_window(spec, f"binding {name!r}")
            out.append(Binding(name, path, _bound_sha(row, name), start, spec))
        return out, "wav_bindings"
    rows = _hand_built(config)
    if not rows:
        raise Refused("config has no wav_bindings and no dialogue/outro_cards audio to verify")
    return rows, "hand_built"
