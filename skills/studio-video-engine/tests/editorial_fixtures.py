"""Fixtures for the editorial tests: the real episode inputs, mutated copies in tmp_path.

Nothing is written next to the real episode; outputs go to tmp_path.  The tail-handle probe is a
fake that returns the native frame counts recorded by the hand-built review cut, except in the one
test that runs the real ffprobe.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

from engine.config import loader
from engine.editorial import build

EPISODE = "04-milk-and-mom"
REAL_ROOT = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / EPISODE
REAL_BOUNDARIES = REAL_ROOT / "engine" / "boundaries.json"
# Canonical word timing (root decision T-E28a r4: karaoke onset fix, review v012). v001 is kept only
# as the historical baseline for the v001 -> v003 diff test.
REAL_TIMING = REAL_ROOT / "editorial" / "word-timing-v003" / "WORD-TIMING-v003.json"
HISTORICAL_TIMING_V001 = REAL_ROOT / "editorial" / "word-timing-v001" / "WORD-TIMING-v001.json"
LOGO = (REAL_ROOT / ".." / ".." / "studio-app" / "logo-jenniejoy-kids.png").resolve()  # shared studio logo
# The real episode moved on to its 3444 f contract; these tests pin the v008-era 2520 f cut, so they take the
# episode block from the frozen snapshot (boundaries.json, word timing and clips are still the real files).
LEGACY_EPISODE = Path(__file__).resolve().parent / "fixtures" / "ep04-engine" / "episode.json"
NATIVE_FRAMES = {"S03_B-native.mp4": 107, "S04_B-native.mp4": 141, "S05_B-native.mp4": 107}


def fake_probe(clip: Path) -> int:
    return NATIVE_FRAMES[clip.name]


def probe_returning(count: int):
    return lambda clip: count


class Inputs:
    """Mutable copies of boundaries.json and the word timing, written to tmp on demand."""

    def __init__(self, tmp_path: Path, timing_path: Path = REAL_TIMING) -> None:
        self.tmp = tmp_path
        self.config = dataclasses.replace(loader.resolve_episode(EPISODE),
                                          episode=json.loads(LEGACY_EPISODE.read_text("utf-8")))
        self.boundaries = json.loads(REAL_BOUNDARIES.read_text("utf-8"))
        self.timing = json.loads(Path(timing_path).read_text("utf-8-sig"))

    def row(self, frame: int) -> dict:
        return next(row for row in self.boundaries["boundaries"] if row["frame"] == frame)

    def entry(self, name: str) -> dict:
        return next(entry for entry in self.timing["entries"] if entry["id"] == name)

    def with_config(self, **changes) -> "Inputs":
        self.config = dataclasses.replace(self.config, **changes)
        return self

    def timeline_change(self, **values) -> "Inputs":
        episode = copy.deepcopy(self.config.episode)
        episode["timeline"].update(values)
        return self.with_config(episode=episode)

    def write(self) -> tuple[Path, Path]:
        """The mutated boundaries.json and word timing, written to tmp."""
        boundaries = self.tmp / "boundaries.json"
        timing = self.tmp / "word-timing.json"
        boundaries.write_text(json.dumps(self.boundaries), encoding="utf-8")
        timing.write_text(json.dumps(self.timing), encoding="utf-8")
        return boundaries, timing

    def build(self, probe=fake_probe) -> build.Built:
        boundaries, timing = self.write()
        return build.build_review_config(self.config, boundaries, timing, probe=probe, allow_outside=(LOGO,))

    def table(self, probe=fake_probe, only=None) -> dict:
        """The per-boundary preset feasibility table (``jjv editorial presets``)."""
        boundaries, timing = self.write()
        return build.feasibility_report(self.config, boundaries, timing, probe=probe, allow_outside=(LOGO,),
                                        only=only)


def probe_override(name: str, count: int):
    """The recorded frame counts, except one clip (by file name)."""
    return lambda clip: count if clip.name == name else NATIVE_FRAMES[clip.name]
