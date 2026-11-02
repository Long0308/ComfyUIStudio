"""Prints, as JSON, what the REAL engine preset module (engine/editorial/presets.py) says about every ready preset.

argv[1] = the skill root (the folder that holds `engine/`). The kit test compares this with its own reading of the generated
catalog. Engine import only: nothing is rendered or probed. Run with `python -I`."""
import json
import sys

sys.path.insert(0, sys.argv[1])

from engine.editorial import presets as P  # noqa: E402

out = {}
for name in P.ready_names():
    p = P.get(name)
    frames = P.default_frames(p)
    params = P.resolve_params(p, None)
    if p.window == "iris":
        params = {**params, "disc_fade_frames": 6}  # the iris window needs the row's own number
    out[name] = {
        "shows_both": p.shows_both,
        "tail_only": p.tail_only,
        "frames_rule": p.frames,
        "default_frames": frames,
        "candidates": P.candidate_frames(p),
        "params": params,
        "schedule": p.schedule,
        "direction": p.direction,
        "renders_as": p.renders_as,
        "tail": {str(n): P.tail_frames(p, n) for n in P.candidate_frames(p)},
        "window_frames": {str(n): list(P.window(p, 1000, n, params)) for n in P.candidate_frames(p)},
    }
print(json.dumps(out))
