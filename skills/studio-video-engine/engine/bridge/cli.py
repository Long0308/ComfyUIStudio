"""``jjv bridge serve [--host] [--port] [--accounts L1,L2]``: run the loopback bridge in the foreground.

Prints one JSON start line (URL, secret FILE path, allowed labels, jobs folder; never the secret value), then serves
until Ctrl-C.  machine.json is read only; the allow-list comes from ``--accounts`` or ``<state>/config.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config.loader import DEFAULT_MACHINE_PATH
from ..core.errors import EXIT_OK
from . import characters, wardrobe
from .config import DEFAULT_PORT, BridgeConfig, config_section, config_wardrobe, default_state_dir, resolve_accounts
from .server import make_server


def register_cli(stages: Any) -> None:
    bridge = stages.add_parser("bridge", help="loopback HTTP bridge for a ComfyUI graph node: codex-exec image jobs "
                                              "(cloud GPT) + detached video jobs; shared secret")
    verbs = bridge.add_subparsers(dest="verb", required=True)
    serve = verbs.add_parser("serve", help="serve until Ctrl-C (bind 127.0.0.1; wildcard addresses refused)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--accounts", default=None, help="comma-separated machine codex account labels allowed to run "
                                                        "(narrows <state>/config.json accounts, never widens; required one way or the other)")
    serve.add_argument("--state-dir", default=None, help="secret, config.json and jobs/ (default: <machine.json folder>/bridge)")
    serve.add_argument("--machine", default=None, help="machine.json (read only)")
    serve.add_argument("--codex-bin", default=None, help="Codex CLI (default: machine/env/PATH)")
    serve.add_argument("--timeout", type=float, default=None, help="codex exec timeout per image, seconds")
    stage = verbs.add_parser("wardrobe-stage", help="copy (never move) the wardrobe anchors of a domain into the ComfyUI input "
                                                    "folder (write-once) and write the step-UI presets JSON")
    stage.add_argument("--domain", required=True, help="domain id keyed in <state>/config.json wardrobe")
    stage.add_argument("--state-dir", default=None)
    stage.add_argument("--machine", default=None, help="machine.json (read only)")
    library = verbs.add_parser("library-stage", help="copy (never move) each character's current FACE/ACTION library images "
                                                     "into the ComfyUI input folder (write-once) and write the step-UI JSON")
    library.add_argument("--domain", required=True, help="domain id keyed in <state>/config.json characters")
    library.add_argument("--state-dir", default=None)
    library.add_argument("--machine", default=None, help="machine.json (read only)")


def run_library_stage(args: argparse.Namespace) -> int:
    state = Path(args.state_dir) if args.state_dir else default_state_dir()
    machine = Path(args.machine) if args.machine else Path(DEFAULT_MACHINE_PATH)
    done = characters.stage(config_section(state, "characters"), args.domain, machine)
    print(json.dumps({k: done[k] for k in ("presets", "input_dir", "counts", "schema", "domain")}, indent=1))
    return EXIT_OK


def run_stage(args: argparse.Namespace) -> int:
    state = Path(args.state_dir) if args.state_dir else default_state_dir()
    machine = Path(args.machine) if args.machine else Path(DEFAULT_MACHINE_PATH)
    print(json.dumps(wardrobe.stage(config_wardrobe(state), args.domain, machine), indent=1))
    return EXIT_OK


def run_bridge(args: argparse.Namespace) -> int:
    if args.verb == "library-stage":
        return run_library_stage(args)
    if args.verb == "wardrobe-stage":
        return run_stage(args)
    state = Path(args.state_dir) if args.state_dir else default_state_dir()
    accounts = resolve_accounts(state, args.accounts)  # the flag can only narrow config.json, never widen it
    cfg = BridgeConfig(state_dir=state, accounts=tuple(accounts), machine_path=Path(args.machine) if args.machine else None,
                       codex_cmd=[args.codex_bin] if args.codex_bin else None, timeout=args.timeout,
                       wardrobe=config_wardrobe(state))
    server = make_server(cfg, args.host, args.port)
    host, port = server.server_address[:2]
    print(json.dumps({"ok": True, "listening": f"http://{host}:{port}", "secret_file": cfg.secret_path.as_posix(),
                      "accounts": list(cfg.accounts), "jobs": cfg.jobs_dir.as_posix()}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return EXIT_OK
