"""Small stdlib validator for the JSON Schema (draft 2020-12) subset the engine schemas use.

Supported keywords: type, enum, const, properties, required, additionalProperties
(bool or schema), propertyNames, items, minItems, maxItems, uniqueItems, minProperties,
minimum, maximum, exclusiveMinimum, minLength, pattern, anyOf, oneOf and local ``$ref``
(``#/$defs/name``).  Any other keyword that could change validity raises ``ValueError`` so a
schema author cannot silently rely on an unchecked rule.
"""

from __future__ import annotations

import math
import re
from typing import Any

_IGNORED = {"$schema", "$id", "$defs", "title", "description", "$comment"}
_KNOWN = {
    "type", "enum", "const", "properties", "required", "additionalProperties",
    "propertyNames", "items", "minItems", "maxItems", "uniqueItems", "minProperties",
    "minimum", "maximum", "exclusiveMinimum", "minLength", "pattern", "anyOf", "oneOf",
    "$ref",
}


def _type_ok(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError(f"unsupported schema type {name!r}")


def _equal(left: Any, right: Any) -> bool:
    """JSON equality: True is not 1, 1 equals 1.0."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    return type(left) is type(right) and left == right


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    unknown = set(schema) - _KNOWN - _IGNORED
    if unknown:
        raise ValueError(f"unsupported schema keyword(s) at {path}: {sorted(unknown)}")
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, path, errors)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, name) for name in names):
            errors.append(f"{path}: expected type {'|'.join(names)}, got {type(value).__name__}")
            return
    if "const" in schema and not _equal(value, schema["const"]):
        errors.append(f"{path}: must equal {schema['const']!r}, got {value!r}")
    if "enum" in schema and not any(_equal(value, option) for option in schema["enum"]):
        errors.append(f"{path}: must be one of {schema['enum']!r}, got {value!r}")
    if "anyOf" in schema:
        if not any(not _errors_of(value, option, root, path) for option in schema["anyOf"]):
            errors.append(f"{path}: matches none of the anyOf alternatives")
    if "oneOf" in schema:
        hits = sum(1 for option in schema["oneOf"] if not _errors_of(value, option, root, path))
        if hits != 1:
            errors.append(f"{path}: must match exactly one oneOf alternative, matched {hits}")
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        _check_number(value, schema, path, errors)
    elif isinstance(value, str):
        _check_string(value, schema, path, errors)
    elif isinstance(value, list):
        _check_array(value, schema, root, path, errors)
    elif isinstance(value, dict):
        _check_object(value, schema, root, path, errors)


def _errors_of(value: Any, schema: dict, root: dict, path: str) -> list[str]:
    found: list[str] = []
    _check(value, schema, root, path, found)
    return found


def _check_number(value: float, schema: dict, path: str, errors: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: {value} is not a finite number")
        return
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: {value} is below minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path}: {value} is above maximum {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(f"{path}: {value} must be greater than {schema['exclusiveMinimum']}")


def _check_string(value: str, schema: dict, path: str, errors: list[str]) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{path}: shorter than {schema['minLength']} characters")
    if "pattern" in schema and re.search(schema["pattern"], value) is None:
        errors.append(f"{path}: {value!r} does not match pattern {schema['pattern']}")


def _check_array(value: list, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{path}: needs at least {schema['minItems']} item(s), has {len(value)}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{path}: allows at most {schema['maxItems']} item(s), has {len(value)}")
    if schema.get("uniqueItems"):
        for index, item in enumerate(value):
            if any(_equal(item, other) for other in value[:index]):
                errors.append(f"{path}[{index}]: duplicate item {item!r}")
    if "items" in schema:
        for index, item in enumerate(value):
            _check(item, schema["items"], root, f"{path}[{index}]", errors)


def _check_object(value: dict, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "minProperties" in schema and len(value) < schema["minProperties"]:
        errors.append(f"{path}: needs at least {schema['minProperties']} propert(ies)")
    for name in schema.get("required", []):
        if name not in value:
            errors.append(f"{path}: missing required property {name!r}")
    properties = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for name, item in value.items():
        child = f"{path}.{name}"
        if "propertyNames" in schema:
            _check(name, schema["propertyNames"], root, f"{path}<name {name!r}>", errors)
        if name in properties:
            _check(item, properties[name], root, child, errors)
        elif extra is False:
            errors.append(f"{path}: unexpected property {name!r}")
        elif isinstance(extra, dict):
            _check(item, extra, root, child, errors)


def validate(instance: Any, schema: dict, *, label: str = "$") -> list[str]:
    """Return a list of human-readable violations (empty means valid)."""
    errors: list[str] = []
    _check(instance, schema, schema, label, errors)
    return errors
