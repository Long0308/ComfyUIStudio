"""Read-only ComfyUI facts for the health preflight: ``GET /system_stats``, ``/queue``, ``/object_info/<class>``.

``client`` is anything with ``get(path)`` that raises ``engine.core.errors.Uncertain`` on a transport
problem (the real ``ComfyClient`` raises ``ComfyError``, an ``Uncertain``).  Nothing is POSTed.  Every
failure becomes text in the facts; the preflight turns it into a named check with a next step.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from ..core.errors import Uncertain


class Getter(Protocol):
    def get(self, path: str) -> Any: ...


@dataclass(frozen=True)
class ComfyFacts:
    system_stats: dict[str, Any] | None
    system_error: str | None
    queue: dict[str, Any] | None
    queue_error: str | None
    object_info: dict[str, dict[str, Any] | None] = field(default_factory=dict)  # None: unknown to this ComfyUI
    object_info_errors: dict[str, str] = field(default_factory=dict)

    @property
    def http_up(self) -> bool:
        return self.system_error is None and self.system_stats is not None


def _get_object(client: Getter, path: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = client.get(path)
    except Uncertain as error:
        return None, f"GET {path} failed: {error}"
    except Exception as error:  # noqa: BLE001 - a probe must never raise; the check reports it
        return None, f"GET {path} failed: {error!r}"
    if not isinstance(value, dict):
        return None, f"GET {path} did not return a JSON object"
    return value, None


def collect_comfy_facts(client: Getter, classes: Iterable[str]) -> ComfyFacts:
    """``/system_stats`` first; when it fails nothing else is probed (ComfyUI HTTP is down)."""
    stats, stats_error = _get_object(client, "/system_stats")
    if stats_error is not None or stats is None:
        return ComfyFacts(None, stats_error or "GET /system_stats returned nothing", None,
                          "not probed: ComfyUI HTTP down")
    queue, queue_error = _get_object(client, "/queue")
    info: dict[str, dict[str, Any] | None] = {}
    errors: dict[str, str] = {}
    for name in sorted(set(classes)):
        value, error = _get_object(client, "/object_info/" + urllib.parse.quote(name, safe=""))
        if error is not None or value is None:
            errors[name] = error or "empty reply"
            continue
        entry = value.get(name)
        info[name] = entry if isinstance(entry, dict) else None
    return ComfyFacts(stats, None, queue, queue_error, info, errors)
