"""The speech of a film: receipt WAV bindings placed sample-exact, and the duck windows derived from them.

Bindings come from the review config through ``engine.qa.bindings.resolve_bindings`` (``wav_bindings``
authoritative, hand-built rows only when no engine marker); every WAV must hash to its binding (receipt-WAV
rule).  The dialogue stem is the integer sum of the WAV samples at ``start_frame * rate / fps`` with NO gain.
A duck window is the span of each WAV where its speech actually is (RMS gate), unless ``--windows`` gives
explicit ones (``start_s``/``end_s`` seconds or ``start_sample``/``end_sample``).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path
from ..qa.bindings import resolve_bindings
from ..voice.wavio import WavData, read_wav
from .timeline import samples_for_frames


@dataclass(frozen=True)
class PlacedWav:
    name: str
    path: str
    sha256: str
    start_frame: int
    start_sample: int
    data: WavData
    bus: str = "dialogue"  # speech class: dialogue | vocabulary | any --extra-wav class

    @property
    def end_sample(self) -> int:
        return self.start_sample + self.data.frames

    def pcm(self) -> np.ndarray:
        return np.frombuffer(self.data.pcm, dtype="<i2").reshape(-1, self.data.channels)


def bus_of(name: str) -> str:
    """Speech class of a binding: ``voc ...`` (vocabulary cards) is ``vocabulary``, everything else ``dialogue``."""
    return "vocabulary" if name.lower().startswith("voc") else "dialogue"


def resolve_path(text: str, episode_root: Path, allow: tuple[Path, ...]) -> Path:
    path = Path(text)
    path = resolve_data_path(path if path.is_absolute() else Path(episode_root) / path)
    resolved = path.resolve()
    roots = [Path(episode_root).resolve(), *[Path(a).resolve() for a in allow]]
    if not any(root == resolved or root in resolved.parents for root in roots):
        raise Refused(f"{text}: outside the episode root; name it with --allow-outside")
    return resolved


def load_placed(review_config: dict, episode_root: Path, timeline: dict, allow: tuple[Path, ...]) -> list[PlacedWav]:
    rows, _ = resolve_bindings(review_config)
    placed = []
    for binding in rows:
        path = resolve_path(binding.path, episode_root, allow)
        if not path.is_file():
            raise Refused(f"binding {binding.name!r}: WAV not found: {path}")
        if sha256_file(path) != binding.sha256:
            raise Refused(f"binding {binding.name!r}: WAV differs from its receipt sha256 ({path})")
        data = read_wav(path)
        if data.rate != timeline["sample_rate"] or data.channels != 2:
            raise Refused(f"binding {binding.name!r}: {data.rate} Hz / {data.channels} ch; the mix needs "
                          f"{timeline['sample_rate']} Hz stereo (sample-exact placement, no resample)")
        placed.append(PlacedWav(binding.name, str(path), binding.sha256, binding.start_frame,
                                samples_for_frames(binding.start_frame, timeline["fps"], timeline["sample_rate"]), data,
                                bus_of(binding.name)))
    return sorted(placed, key=lambda w: (w.start_sample, w.name))


def load_extra(spec: str, episode_root: Path, timeline: dict, allow: tuple[Path, ...]) -> PlacedWav:
    """``name|path|sha256|start_frame[|class]``: one more receipt WAV (e.g. a late end line) placed like the bound ones;
    ``class`` is its speech bus (default ``extra``)."""
    parts = spec.split("|")
    if len(parts) not in (4, 5) or not parts[0] or not parts[3].isdigit() or (len(parts) == 5 and not parts[4]):
        raise Refused(f"--extra-wav must be 'name|path|sha256|start_frame[|class]', got {spec!r}")
    name, text, sha, frame = parts[0], parts[1], parts[2].lower(), int(parts[3])
    bus = parts[4] if len(parts) == 5 else "extra"
    path = resolve_path(text, episode_root, allow)
    if not path.is_file() or sha256_file(path) != sha:
        raise Refused(f"--extra-wav {name!r}: file missing or not the receipt sha256 ({path})")
    data = read_wav(path)
    if data.rate != timeline["sample_rate"] or data.channels != 2:
        raise Refused(f"--extra-wav {name!r}: {data.rate} Hz / {data.channels} ch; the mix needs {timeline['sample_rate']} Hz stereo")
    return PlacedWav(name, str(path), sha, frame, samples_for_frames(frame, timeline["fps"], timeline["sample_rate"]), data, bus)


def load_brand_voice(path: str | Path, expected_sha: str | None, timeline: dict, start_s: float,
                     first_speech_sample: int, guard_s: float = 0.2) -> PlacedWav:
    """The brand voice layer: a stereo WAV at ``start_s``, which must end ``guard_s`` before the first speech window."""
    path = Path(path)
    if not path.is_file():
        raise Refused(f"brand voice WAV not found: {path}")
    digest = sha256_file(path)
    if expected_sha is not None and digest != expected_sha.lower():
        raise Refused(f"brand voice {path} hashes to {digest}, expected {expected_sha}")
    data = read_wav(path)
    if data.rate != timeline["sample_rate"] or data.channels != 2:
        raise Refused(f"brand voice: {data.rate} Hz / {data.channels} ch; the mix needs {timeline['sample_rate']} Hz stereo")
    start = int(round(start_s * data.rate))
    voice = PlacedWav("brand voice", str(path), digest, start * timeline["fps"] // data.rate, start, data)
    if voice.end_sample > first_speech_sample - int(round(guard_s * data.rate)):
        raise Refused(f"the brand voice ends at {voice.end_sample / data.rate:.2f} s, inside the {guard_s} s guard before the first "
                      f"speech window ({first_speech_sample / data.rate:.2f} s)")
    return voice


def dialogue_stem(placed: list[PlacedWav], total: int) -> np.ndarray:
    """int16 (total, 2): the WAV samples exactly as bound; overlapping audible WAVs are Refused."""
    stem = np.zeros((total, 2), dtype=np.int32)
    previous: PlacedWav | None = None
    for wav in placed:
        if wav.end_sample > total:
            raise Refused(f"{wav.name}: runs to sample {wav.end_sample}, past the film end {total}")
        audible = bool(np.any(wav.pcm()))
        if previous is not None and wav.start_sample < previous.end_sample and audible and np.any(previous.pcm()):
            raise Refused(f"{wav.name} overlaps {previous.name}: two audible WAVs may not share samples")
        stem[wav.start_sample:wav.end_sample] += wav.pcm()
        previous = wav if previous is None or wav.end_sample >= previous.end_sample else previous
    return stem.astype("<i2")


def class_stems(placed: list[PlacedWav], total: int) -> dict[str, np.ndarray]:
    """int16 (total, 2) per speech class, each exactly the bound samples of that class (no gain)."""
    return {bus: dialogue_stem([w for w in placed if w.bus == bus], total) for bus in sorted({w.bus for w in placed})}


def speech_extent(wav: PlacedWav, threshold_dbfs: float, window_ms: int) -> tuple[int, int] | None:
    """(first, end) sample of the speech inside the WAV: windows with RMS >= threshold; None when silent."""
    size = max(1, wav.data.rate * window_ms // 1000)
    pcm = wav.pcm().astype(np.float64) / 32768.0
    count = pcm.shape[0] // size
    if count == 0:
        return None
    energy = np.sqrt(np.mean(np.square(pcm[:count * size].reshape(count, size, -1)), axis=(1, 2)))
    loud = np.nonzero(energy >= 10 ** (threshold_dbfs / 20.0))[0]
    if loud.size == 0:
        return None
    return int(loud[0] * size), int(min(pcm.shape[0], (loud[-1] + 1) * size))


def windows_from_bindings(placed: list[PlacedWav], threshold_dbfs: float, window_ms: int) -> list[dict]:
    rows = []
    for wav in placed:
        extent = speech_extent(wav, threshold_dbfs, window_ms)
        if extent is not None:
            rows.append({"id": wav.name, "kind": "speech", "start_sample": wav.start_sample + extent[0],
                         "end_sample": wav.start_sample + extent[1]})
    return rows


def load_windows(path: str | Path, rate: int) -> list[dict]:
    document = read_json(Path(path))
    if not isinstance(document, list) or not document:
        raise Refused(f"{path}: windows must be a non-empty JSON list")
    rows = []
    for index, item in enumerate(document):
        if not isinstance(item, dict):
            raise Refused(f"{path}: window {index} is not an object")
        if "start_s" in item and "end_s" in item:
            start, end = int(round(float(item["start_s"]) * rate)), int(round(float(item["end_s"]) * rate))
        elif "start_sample" in item and "end_sample" in item:
            start, end = int(item["start_sample"]), int(item["end_sample"])
        else:
            raise Refused(f"{path}: window {index} needs start_s/end_s or start_sample/end_sample")
        rows.append({"id": str(item.get("id", f"W{index + 1:02d}")), "kind": str(item.get("kind", "speech")),
                     "start_sample": start, "end_sample": end})
    return rows
