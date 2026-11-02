"""Fixtures of the audio stage tests: a throw-away episode world, synthetic WAVs, a review config, a fake ComfyUI.

Nothing here touches the real ComfyUI, the real GPU lock or docker: ComfySettings point at tmp paths and the
fake server; the pinned multi-GB model files are replaced by tiny files with matching pins.
"""

from __future__ import annotations

import copy
import hashlib
import io
import shutil
import wave
from pathlib import Path

import numpy as np

from config_fixtures import make_world
from fake_comfy import FakeComfy

from engine.audio import jobs
from engine.audio.recipe import AudioRecipe, load_recipe
from engine.comfy.client import ComfyClient
from engine.comfy.guards import ClassPolicy
from engine.comfy.settings import ComfySettings
from engine.config.loader import ResolvedConfig, resolve_episode

RATE = 48_000


def audio_world(tmp_path: Path) -> tuple[ResolvedConfig, Path]:
    world = make_world(tmp_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    return config, world.skill_root


def wav_bytes(audio: np.ndarray, rate: int = RATE) -> bytes:
    """float (n, 2) in [-1, 1] -> PCM16 WAV bytes."""
    pcm = np.rint(np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return stream.getvalue()


def tone(seconds: float, amplitude: float, freq: float = 220.0, rate: int = RATE) -> np.ndarray:
    t = np.arange(int(round(seconds * rate))) / rate
    return np.repeat((amplitude * np.sin(2 * np.pi * freq * t))[:, None], 2, axis=1)


def write_tone(path: Path, seconds: float, amplitude: float, freq: float = 220.0) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = wav_bytes(tone(seconds, amplitude, freq))
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def hand_built_review(root: Path, *, fps: int = 30, total_frames: int = 600,
                      lines: tuple = (("S01_A", 30, 2.0, 0.30), ("S01_B", 150, 2.0, 0.30)),
                      cards: tuple = (("Alpha", 300, 0.6, 0.30), ("Beta", 390, 0.6, 0.30))) -> dict:
    """A hand-built review config (dialogue[].audio + outro_cards[].audio) with real tone WAVs under ``root``."""
    dialogue, outro = [], []
    for ident, start, seconds, amp in lines:
        sha = write_tone(root / "audio" / f"{ident}.wav", seconds, amp)
        dialogue.append({"id": ident, "start_frame": start, "duration_frames": int(round(seconds * fps)) + 6,
                         "speech_text": "Alice look at the milk now please", "audio": {"path": f"audio/{ident}.wav", "sha256": sha}})
    for term, start, seconds, amp in cards:
        sha = write_tone(root / "audio" / f"{term}.wav", seconds, amp, 330.0)
        outro.append({"term": term, "start_frame": start, "duration_frames": 90,
                      "audio": {"path": f"audio/{term}.wav", "sha256": sha}})
    return {"schema": "hand-built", "fps": fps, "total_frames": total_frames, "dialogue": dialogue, "outro_cards": outro,
            "motion": {"transitions": [{"id": "T120", "boundary": 120, "from": "S01_A", "to": "S01_B", "type": "whip",
                                        "start": 118, "end_exclusive": 126}],
                       "icons": [{"id": "IC01", "shot": "S01_A", "word": "milk", "frame": 50}],
                       "ending": {"logo_disc": {"in": 480}}}}


def song_wav(seconds: float, bpm: float = 96.0, rate: int = RATE) -> bytes:
    """A bar-periodic synthetic song with a fade-out end (so a loop point exists and the ending is natural)."""
    bar = 4 * 60.0 / bpm
    t = np.arange(int(seconds * rate)) / rate
    envelope = 0.15 + 0.25 * np.sin(np.pi * (t % bar) / bar) ** 2
    tail = np.clip((seconds - t) / 2.0, 0.0, 1.0)
    return wav_bytes(np.repeat((envelope * tail * np.sin(2 * np.pi * 262.0 * t))[:, None], 2, axis=1), rate)


def sfx_wav(seconds: float = 0.5) -> bytes:
    """0.3 s of silence, a tone burst, 0.3 s of silence: the trim must remove the silence."""
    silence = np.zeros((int(0.3 * RATE), 2))
    return wav_bytes(np.concatenate([silence, tone(seconds, 0.2, 880.0), silence]))


class Rig:
    def __init__(self, tmp_path: Path, fake: FakeComfy, recipe: AudioRecipe, skill_root: Path) -> None:
        self.root = tmp_path / "comfy"
        self.settings = ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=self.root / "input",
                                      output_dir=self.root / "output", container="test-container", lock_timeout_seconds=0.3,
                                      poll_seconds=0.01, http_timeout_seconds=5, history_timeout_seconds=5.0,
                                      min_history_timeout_seconds=0)
        self.client = ComfyClient(fake.url, timeout_seconds=5.0)
        self.policy = ClassPolicy(frozenset({"claudenode"}), True, frozenset())
        self.recipe = recipe
        self.fake = fake
        self.data = tiny_models(recipe.data, self.root)

    def context(self, out: Path) -> jobs.RunContext:
        return jobs.RunContext(client=self.client, settings=self.settings, policy=self.policy, out=out, timeout_seconds=5.0)

    def serve(self, make: "callable") -> None:
        """Every POST writes ``make(payload)`` (WAV bytes named .flac) where SaveAudio would and answers it."""
        def render(payload: dict, prompt_id: str) -> dict:
            prefix = payload["prompt"]["8"]["inputs"]["filename_prefix"]
            subfolder, name = prefix.rsplit("/", 1)
            target = self.settings.output_dir / subfolder / f"{name}_00001_.flac"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(make(payload["prompt"]))
            return {"8": {"audio": [{"filename": target.name, "subfolder": subfolder, "type": "output"}]}}
        self.fake.on_post = render
        self.fake.auto_complete = True


def tiny_models(data: dict, comfy_root: Path) -> dict:
    """A copy of the recipe whose model pins match tiny files created under the fake ComfyUI root."""
    patched = copy.deepcopy(data)
    for model in patched["models"]:
        path = comfy_root / model["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(model["role"].encode("utf-8"))
        model["bytes"], model["sha256"] = path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()
    return patched


def recipe_of(skill_root: Path, recipe_id: str, family: str) -> AudioRecipe:
    return load_recipe(recipe_id, family, skill_root=skill_root)


def copy_recipes(tmp_path: Path) -> Path:
    target = tmp_path / "skill_copy"
    shutil.copytree(Path(__file__).resolve().parents[1] / "recipes", target / "recipes")
    return target
