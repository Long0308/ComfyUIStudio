"""Writes a master-config with the REAL producer (engine/edit/master_config.py) from an engine build folder, for the kit test.

argv: SKILL_ROOT BUILD_DIR EPISODE_ROOT OUT [--runs DIR] [--tail-map FILE] [--preview]
The contract is read from the build itself (fps, main_frames, end_hold_frames) and the 3840x2160 / 24 fps master of the cartoon domain: the
test episode has no resolved contract of its own. Engine import only: nothing is rendered. Run with `python -I`."""
import json
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, sys.argv[1])

from engine.edit import master_config as mc  # noqa: E402

build, root, out = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
rest = sys.argv[5:]
value = lambda flag: Path(rest[rest.index(flag) + 1]) if flag in rest else None  # noqa: E731
review = json.loads((build / "review-config.json").read_text(encoding="utf8"))
events = json.loads((build / "events.json").read_text(encoding="utf8"))
contract = mc.Contract(3840, 2160, review["fps"], Fraction(24), review["main_frames"], review["end_hold_frames"])
document = mc.build_master_config(review, events, contract, episode_root=root, runs_dir=value("--runs"), tail_map=value("--tail-map"),
                                  preview="--preview" in rest)
out.write_text(json.dumps(document, indent=2), encoding="utf8")
print(json.dumps({"master_ready": document["master_ready"], "build_mode": document["build_mode"], "missing_shots": document["missing_shots"],
                  "missing_tails": document["missing_tails"]}))
