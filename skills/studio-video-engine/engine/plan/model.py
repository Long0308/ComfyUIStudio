"""Pure helpers of the planner: stripping, hashing and leaf-level diffs (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from ..core.io import canonical_sha256

MODE = "ascii"
EMPTY = "<empty>"
FILE_KEYS = ("path", "file")            # a key whose string value refers to a file
FILE_SUFFIXES = ("_path", "_file")
Bind = Callable[[str, str], Any] | None  # (key, text) -> what a sha-less file reference hashes as (graph.FileBinder)
_SHA_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class Node:
    """One stage node of one version of the episode.  ``parts`` is the dependency slice (name -> JSON value)."""

    id: str
    kind: str
    device: str                       # cpu | gpu | http-local
    parts: Mapping[str, Any]
    key: str
    output: str | None = None         # content hash of what the node produces, when the planner can see it
    deps: tuple[str, ...] = ()
    materialised: bool = False        # the new inputs already contain this node's output (config carries it)
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    path: str
    old: Any
    new: Any


def sha(value: Any) -> str:
    return canonical_sha256(value, mode=MODE)


def node_key(kind: str, parts: Mapping[str, Any], pins: Mapping[str, Any]) -> str:
    """sha256(canonical {kind, pins, part hashes}); a part is hashed on its own so a stale reason can name it."""
    return sha({"kind": kind, "pins": dict(pins), "parts": {name: sha(value) for name, value in parts.items()}})


def file_key_stem(key: str) -> str | None:
    """``""`` for ``path`` / ``file``, the prefix for ``*_path`` / ``*_file`` (``icon_path`` -> ``icon``), else None."""
    if key in FILE_KEYS:
        return ""
    for suffix in FILE_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)]
    return None


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA_HEX


def bound_by_sha(mapping: Mapping[str, Any], key: str) -> bool:
    """True when a sibling sha names the content ``mapping[key]`` refers to: ``<key>_sha256`` for any key, plus
    ``sha256`` / ``<stem>_sha256`` for a file key (``path`` + ``sha256``, ``icon_path`` + ``icon_sha256``)."""
    stem = file_key_stem(key)
    names = [f"{key}_sha256"] + ([] if stem is None else ["sha256"] + ([f"{stem}_sha256"] if stem else []))
    return any(_is_sha(mapping.get(name)) for name in names)


def strip(value: Any, drop: frozenset[str], bind: Bind = None) -> Any:
    """Copy of ``value`` without the dropped keys and without any file reference whose sibling sha is its identity
    (``path`` / ``*_path`` / ``file`` / ``*_file`` beside ``sha256`` / ``<stem>_sha256``, or any key beside its own
    ``<key>_sha256``): where a tree lives is not content, the sha is.  A file key WITHOUT a sha goes through ``bind``
    (its content hash, see ``graph.FileBinder``) or, without one, is compared as written.  Every other string --
    display text such as ``end_plate.text_en`` or an IPA ``/mɪlk/`` (N60) -- is content and stays as it is."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in drop:
                continue
            if file_key_stem(key) is not None or (isinstance(item, str) and bound_by_sha(value, key)):
                if bound_by_sha(value, key) or not isinstance(item, str):
                    continue
                out[key] = bind(key, item) if bind is not None else item
                continue
            out[key] = strip(item, drop, bind)
        return out
    if isinstance(value, list):
        return [strip(v, drop, bind) for v in value]
    return value


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Leaf path -> scalar (``a.b[3].c``); an empty container is a leaf so an emptied list still shows."""
    if isinstance(value, dict) and value:
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(value, list) and value:
        out = {}
        for i, v in enumerate(value):
            out.update(flatten(v, f"{prefix}[{i}]"))
        return out
    if isinstance(value, (dict, list)):
        return {prefix: EMPTY}
    return {prefix: value}


def diff_parts(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[Change]:
    """Leaf-level differences between two slices; ``+name`` / ``-name`` for a part that appeared / vanished."""
    changes: list[Change] = []
    for name in sorted(set(old) | set(new)):
        if name not in old:
            changes.append(Change(f"+{name}", None, None))
        elif name not in new:
            changes.append(Change(f"-{name}", None, None))
        elif sha(old[name]) != sha(new[name]):
            a, b = flatten(old[name], name), flatten(new[name], name)
            changes.extend(Change(p, a.get(p), b.get(p)) for p in sorted(set(a) | set(b)) if a.get(p) != b.get(p))
    return changes


def show(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value)
    return text[:12] if len(text) == 64 and all(c in "0123456789abcdef" for c in text) else text[:40]


def why_text(changes: Iterable[Change], *, limit: int = 4) -> list[str]:
    """Human lines: the first ``limit`` leaves as ``path old -> new`` and a count for the rest."""
    rows = list(changes)
    lines = [c.path if c.old is None and c.new is None else f"{c.path} {show(c.old)} -> {show(c.new)}"
             for c in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"(+{len(rows) - limit} more leaves)")
    return lines


def group_counts(changes: Iterable[Change]) -> dict[str, int]:
    """Leaves changed per top-level block (the part name before the first ``.`` / ``[``)."""
    counts: dict[str, int] = {}
    for c in changes:
        head = c.path.lstrip("+-").split(".")[0].split("[")[0]
        counts[head] = counts.get(head, 0) + 1
    return counts
