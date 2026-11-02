"""Copy (never move) the v005 wardrobe + character reference images to TOP-LEVEL names in ComfyUI input/.

Why: frontend 1.55.17 lists only top-level input/ files in the LoadImage combo and raises its error overlay for
subfolder values (measured v003 and again 31/10 on v005: 12 errors = 7 wardrobe + 5 character slots), although the
server accepts them. Names are content-addressed: newtecons_wd_<sha12>.png and newtecons_ch_<CHAR>_<sha12>.png.
Each source must hash to the sha256 in its presets/characters JSON; an existing target must be byte-identical
(else refused). Exclusive create, no deletes, no network, no GPU.

Usage: python -I stage_toplevel_refs_v005.py [--max-face 3 --max-pose 2]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
INPUT = HERE.parents[4] / 'production-local' / 'ComfyUI' / 'input'
DATA = HERE.parents[4] / 'production-local' / 'ComfyUI' / 'custom_nodes' / 'newtecons_step_ui' / 'web' / 'data'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def toplevel_name(rel: str, digest: str, char: str | None = None) -> str:
    return ('newtecons_ch_%s_%s.png' % (char, digest[:12])) if char else ('newtecons_wd_%s.png' % digest[:12])


def copy_exclusive(src: Path, dst: Path, digest: str) -> str:
    if sha(src) != digest:
        raise ValueError('%s does not hash to its registry sha %s' % (src, digest))
    if dst.exists():
        if sha(dst) != digest:
            raise ValueError('%s exists with different bytes; refusing' % dst)
        return 'identical'
    with dst.open('xb') as stream:
        stream.write(src.read_bytes())
    if sha(dst) != digest:
        raise ValueError('copy of %s did not reproduce %s' % (src, digest))
    return 'copied'


def plan(max_face: int, max_pose: int) -> list[tuple[str, str, str | None]]:
    rows = []
    wardrobe = json.loads((DATA / 'wardrobe' / 'newtecons_live_action.json').read_text(encoding='utf-8-sig'))
    for items in wardrobe['contexts'].values():
        rows += [(r['file'], r['sha256'], None) for r in items]
    chars = json.loads((DATA / 'characters' / 'newtecons_live_action.json').read_text(encoding='utf-8-sig'))
    for cid, entry in chars['characters'].items():
        rows += [(r['file'], r['sha256'], cid) for r in entry['face'][:max_face]]
        rows += [(r['file'], r['sha256'], cid) for r in entry['action'][:max_pose]]
    seen, out = set(), []
    for row in rows:
        if row[:2] not in seen:
            seen.add(row[:2])
            out.append(row)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--max-face', type=int, default=3)
    p.add_argument('--max-pose', type=int, default=2)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8')
    states = {}
    try:
        for rel, digest, char in plan(a.max_face, a.max_pose):
            state = copy_exclusive(INPUT / rel, INPUT / toplevel_name(rel, digest, char), digest)
            states[state] = states.get(state, 0) + 1
    except (OSError, ValueError, KeyError) as exc:
        print('REFUSED: %s: %s' % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    print(json.dumps({'input': str(INPUT), **states}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
