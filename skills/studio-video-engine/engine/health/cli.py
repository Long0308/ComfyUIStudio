"""``jjv health preflight``: the engine-level health gate as a verb.  One JSON report on stdout.

Exit 0 ready, 1 not ready (nothing was queued), 2 an input (episode, fixture, graph) is unreadable.
``--fixture`` is the dry form: no HTTP, no docker; the document stands in for both.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..comfy.client import ComfyClient
from ..comfy.settings import settings_from_machine
from ..config.loader import resolve_episode
from ..core.errors import EXIT_OK, EXIT_REFUSED, Refused
from ..core.io import read_json
from .fixture import load_fixture
from .preflight import dry_preflight, run_preflight


def register_cli(stages: Any) -> None:
    health = stages.add_parser("health", help="engine-level docker/ComfyUI health preflight (read-only)")
    verbs = health.add_subparsers(dest="verb", required=True)
    pre = verbs.add_parser("preflight", help="docker engine, container identity, ComfyUI HTTP, idle queue, free VRAM, "
                                             "graph nodes; exit 0 ready / 1 not ready (nothing queued)")
    pre.add_argument("--episode", default=None, help="episode.json path, episode root or slug (machine: ComfyUI url + container)")
    pre.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    pre.add_argument("--base-url", default=None, help="ComfyUI base URL when no --episode is given")
    pre.add_argument("--container", default=None, help="ComfyUI container name when no --episode is given")
    pre.add_argument("--graph", default=None, help="API graph whose node classes must exist on this ComfyUI (optional)")
    pre.add_argument("--min-free-vram-mib", type=int, default=0, help="recipe minimum free VRAM in MiB (default 0: report only)")
    pre.add_argument("--fixture", default=None, help="dry form: a jjv/health-fixture/v1 document instead of docker + HTTP")
    pre.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout per GET (seconds)")


def _target(args: argparse.Namespace) -> tuple[str, str]:
    if args.episode:
        config = resolve_episode(args.episode, machine_path=Path(args.machine) if args.machine else None)
        settings = settings_from_machine(config.machine)
        return settings.base_url, settings.container
    if args.base_url and args.container:
        return str(args.base_url).rstrip("/"), str(args.container)
    raise Refused("give --episode, or both --base-url and --container")


def run_health(args: argparse.Namespace) -> int:
    if args.min_free_vram_mib < 0:
        raise Refused("--min-free-vram-mib must be >= 0")
    base_url, container = _target(args)
    graph = read_json(Path(args.graph)) if args.graph else None
    if args.fixture:
        report = dry_preflight(load_fixture(Path(args.fixture)), container=container, base_url=base_url, graph=graph,
                               min_free_vram_mib=args.min_free_vram_mib)
    else:
        client = ComfyClient(base_url, timeout_seconds=args.timeout)
        report = run_preflight(client, SimpleNamespace(base_url=base_url, container=container), graph=graph,
                               min_free_vram_mib=args.min_free_vram_mib)
    print(json.dumps(report.to_json(), indent=2, ensure_ascii=True))
    return EXIT_OK if report.ready else EXIT_REFUSED
