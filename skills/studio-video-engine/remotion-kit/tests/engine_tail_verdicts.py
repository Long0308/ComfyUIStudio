"""Reads a JSON list of {editorial, delivery, n, native, delivery_fps, native_fps, type?} from stdin and prints the REAL engine verdicts
(true = accepted) of engine/editorial/transitions.py check_tail.

The kit tests feed the same cases to the kit tail rule and assert zero disagreements. Engine import only; no media probing: the native
frame count is injected through the probe callable. fps default to 30 / 24; type defaults to dissolve (a dip_white row takes its tail frame count from the engine schedule, not from n). Run with `python -I`."""
import json
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT))

from engine.core.errors import Refused  # noqa: E402
from engine.editorial import transitions as T  # noqa: E402


def verdict(case):
    row = {'frame': 100, 'from_shot': 'A', 'to_shot': 'B', 'type': case.get('type', 'dissolve'), 'frames': case['n'], 'motivation': 'x',
           'class': 'cut', 'continuity': 'agree', 'direction': 0, 'params': {}}
    outgoing = T.OutgoingShot(shot='A', editorial_frames=case['editorial'], delivery_frames=case['delivery'])
    try:
        T.check_tail(row, outgoing, Path(__file__), lambda _p: case['native'], case.get('delivery_fps', 30), case.get('native_fps', 24))
        return True
    except Refused:
        return False


print(json.dumps([verdict(c) for c in json.load(sys.stdin)]))
