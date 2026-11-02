"""Registration hooks (bin/jjv.py is wired by the task integrator)."""
from __future__ import annotations

import json
from pathlib import Path

from ..config.budget import BudgetRefused
from .ingest import ingest, load_episode


def default_out(episode: dict) -> Path:
    return Path.cwd() / 'derived' / episode['episode_id'] / 'script'


def register_cli(stages) -> None:
    verbs = stages.add_parser('script', help='validate authoring scripts and derive stage inputs').add_subparsers(dest='verb', required=True)
    cmd = verbs.add_parser('ingest', help='immutable script inputs + shared delivery section budget')
    cmd.add_argument('--script', required=True, type=Path)
    cmd.add_argument('--episode', required=True)
    cmd.add_argument('--out', type=Path, help='derived workspace; default ./derived/<episode>/script')
    cmd.add_argument('--target-seconds', type=float, help='hard delivery target; refuses below section floors')
    cmd.add_argument('--vocabulary-speaker')
    cmd.add_argument('--install-shots', action='store_true',
                     help='also write the skeleton shot list to episode.files.shots (write-once, never overwrites)')
    cmd.add_argument('--section-kinds', help="per-run section kinds, e.g. '+vocab_card,-broll'; "
                     'only kinds the domain declares; the domain file is not changed')


def run_script(args) -> int:
    episode_file, episode = load_episode(args.episode)
    try:
        result = ingest(args.script, episode_file, args.out or default_out(episode),
                        target_seconds=args.target_seconds, vocabulary_speaker=args.vocabulary_speaker,
                        install=args.install_shots, section_kinds_spec=args.section_kinds)
    except BudgetRefused as error:
        print(json.dumps({'status': 'refused', 'error': str(error), 'options': error.options, 'sections': error.table}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0
