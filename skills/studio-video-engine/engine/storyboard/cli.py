"""Storyboard CLI registration, independent of the shared bin/jjv.py."""
from __future__ import annotations

import json
from pathlib import Path

from ..script.cli import default_out
from ..script.ingest import load_episode
from .plan import build_plan, check_plan


def register_cli(stages) -> None:
    verbs = stages.add_parser('storyboard', help='script briefs, placement and continuity').add_subparsers(dest='verb', required=True)
    for verb in ('plan', 'check'):
        cmd = verbs.add_parser(verb)
        cmd.add_argument('--episode', required=True)
        cmd.add_argument('--ingest', type=Path, help='script ingest directory')
        cmd.add_argument('--out', type=Path, help='storyboard directory; default <ingest>/storyboard')
        cmd.add_argument('--scene-tool', type=Path, help='shared comfyui-blender scene_layout.py (CPU only)')


def run_storyboard(args) -> int:
    _, episode = load_episode(args.episode)
    ingest_dir = args.ingest or default_out(episode)
    out = args.out or ingest_dir / 'storyboard'
    if args.verb == 'plan':
        plan = build_plan(ingest_dir, out, episode_id=episode['episode_id'], scene_tool=args.scene_tool)
        print(json.dumps({'status': 'planned', 'shots': len(plan['shots']), 'out': str(out)}, indent=2))
        return 0
    report = check_plan(out, episode_id=episode['episode_id'], scene_tool=args.scene_tool)
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1
