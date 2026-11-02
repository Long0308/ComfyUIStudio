"""The stdlib JSON Schema subset validator, and the CLI wrapper for ``config validate``."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from config_fixtures import make_world
from engine.config import loader
from engine.config.schema import validate


def _errors(value, schema):
    return validate(value, schema)


def test_type_and_bool_is_not_integer() -> None:
    assert _errors(1, {"type": "integer"}) == []
    assert _errors(True, {"type": "integer"})
    assert _errors(1.5, {"type": "number"}) == []
    assert _errors("x", {"type": ["string", "null"]}) == []
    assert _errors(None, {"type": ["string", "null"]}) == []
    assert _errors(3, {"type": ["string", "null"]})


def test_const_enum_and_equality_rules() -> None:
    assert _errors(True, {"const": 1})
    assert _errors(1.0, {"const": 1}) == []
    assert _errors(["a", 1], {"const": ["a", 1]}) == []
    assert _errors("c", {"enum": ["a", "b"]})


def test_object_keywords() -> None:
    schema = {"type": "object", "required": ["a"], "additionalProperties": False,
              "properties": {"a": {"type": "integer"}}}
    assert _errors({"a": 1}, schema) == []
    assert any("missing required property 'a'" in e for e in _errors({}, schema))
    assert any("unexpected property 'b'" in e for e in _errors({"a": 1, "b": 2}, schema))
    assert any("expected type integer" in e for e in _errors({"a": "x"}, schema))
    typed = {"type": "object", "additionalProperties": {"type": "string"}, "propertyNames": {"pattern": "^[a-z]+$"}}
    assert _errors({"ok": "v"}, typed) == []
    assert _errors({"Bad": "v"}, typed) and _errors({"ok": 1}, typed)
    assert _errors({}, {"minProperties": 1})


def test_array_string_number_keywords() -> None:
    assert _errors([1, 1], {"uniqueItems": True})
    assert _errors([1, True], {"uniqueItems": True}) == []
    assert _errors([], {"minItems": 1}) and _errors([1, 2], {"maxItems": 1})
    assert _errors(["a", 1], {"items": {"type": "string"}})
    assert _errors("ab", {"minLength": 3}) and _errors("ab", {"pattern": "^c"})
    assert _errors(0, {"minimum": 1}) and _errors(5, {"maximum": 4})
    assert _errors(0, {"exclusiveMinimum": 0}) and _errors(0.1, {"exclusiveMinimum": 0}) == []


def test_anyof_oneof_and_ref() -> None:
    schema = {"$defs": {"n": {"type": "integer"}}, "anyOf": [{"type": "null"}, {"$ref": "#/$defs/n"}]}
    assert _errors(None, schema) == [] and _errors(3, schema) == [] and _errors("x", schema)
    assert _errors(1, {"oneOf": [{"type": "integer"}, {"minimum": 0}]})  # matches both
    assert _errors("s", {"oneOf": [{"type": "integer"}, {"type": "string"}]}) == []


def test_unsupported_keywords_fail_loudly() -> None:
    with pytest.raises(ValueError, match="unsupported schema keyword"):
        validate(1, {"multipleOf": 2})
    with pytest.raises(ValueError, match="only local"):
        validate(1, {"$ref": "http://elsewhere/x"})


def _keywords(node, path="$"):
    """Yield every schema keyword used anywhere in a schema document."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key
            if key in ("properties", "$defs"):
                for name, sub in value.items():
                    yield from _keywords(sub, f"{path}.{name}")
            elif key in ("items", "additionalProperties", "propertyNames"):
                yield from _keywords(value, f"{path}.{key}")
            elif key in ("anyOf", "oneOf"):
                for index, sub in enumerate(value):
                    yield from _keywords(sub, f"{path}.{key}[{index}]")


def test_every_shipped_schema_uses_only_supported_keywords() -> None:
    from engine.config import schema as engine_schema
    allowed = engine_schema._KNOWN | engine_schema._IGNORED
    files = sorted((loader.SKILL_ROOT / "schemas").glob("*.schema.json"))
    assert len(files) == 9  # +boundaries (T-E28a), +segments (T-E45 P2), +script.schema.json (M6, 2026-10-28)
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        for where, key in _keywords(document):
            assert key in allowed, (path.name, where, key)


def _jjv():
    spec = importlib.util.spec_from_file_location("jjv_cli", loader.SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_validate_real_episode_exits_zero(capsys) -> None:
    code = _jjv().main(["config", "validate", "--episode", "04-milk-and-mom"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] is True and out["violations"] == []
    assert out["resolved"]["domain"]["domain_id"] == "jenniejoy_cartoon_3d"
    assert out["resolved"]["config_sha256"]


def test_cli_validate_violation_exits_one(tmp_path: Path, capsys) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update({"domain.delivery.master.width": 1280}))
    code = _jjv().main(["config", "validate", "--episode", str(world.episode_file)])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["ok"] is False and out["resolved"] is None
    assert any("domain.delivery.master.width" in v for v in out["violations"])


def test_cli_unknown_episode_is_refused_with_exit_one(capsys) -> None:
    code = _jjv().main(["config", "validate", "--episode", "no-such-episode"])
    assert code == 1 and json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_malformed_episode_is_exit_two(tmp_path: Path, capsys) -> None:
    world = make_world(tmp_path)
    world.episode_file.write_text("{oops", encoding="utf-8")
    code = _jjv().main(["config", "validate", "--episode", str(world.episode_file)])
    assert code == 2 and json.loads(capsys.readouterr().out)["ok"] is False
