"""Offline mixer acceptance boundaries; no GPU, generation or production audio."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mix_audio


@unittest.skipUnless(shutil.which("ffmpeg"), "Existing FFmpeg is required for offline audio checks")
class AudioMixerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rate = 24000
        t = np.arange(3 * self.rate) / self.rate
        voice = np.sin(2 * np.pi * 420 * t) * .08 * ((t >= .5) & (t <= 1))
        self._wav("voice.wav", voice)
        self._wav("music.wav", np.sin(2 * np.pi * 180 * t) * .008)
        short = np.arange(round(.2 * self.rate)) / self.rate
        self._wav("effect.wav", np.sin(2 * np.pi * 720 * short) * .02 * np.sin(np.pi * short / .2) ** 2)
        bed = np.arange(round(.4 * self.rate)) / self.rate
        self._wav("air.wav", np.sin(2 * np.pi * 140 * bed) * .002)
        self.config: dict[str, Any] = {
            "schema_version": "1.0", "output_dir": "mix-v1", "duration_seconds": 3,
            "fps": 24, "sample_rate": 48000, "ffmpeg": shutil.which("ffmpeg"),
            "voice": self._source("voice.wav"), "music": self._source("music.wav"),
            "speech": [{"id": "line", "start_seconds": .5, "end_seconds": 1.0}],
            "ambience": [{"id": "air", **self._source("air.wav"), "placement_status": "ambient_no_contact",
                          "start_seconds": 0, "duration_seconds": 3, "loop": True, "loop_crossfade_seconds": .06}],
            "cues": [{"id": "bird", **self._source("effect.wav"), "category": "animal", "placement_status": "measured",
                      "measured_local_frame": 12, "scene_start_global_frame": 24,
                      "transient_seconds": .05, "offset_seconds": .02},
                     {"id": "step", **self._source("effect.wav"), "category": "footsteps", "placement_status": "measured",
                      "measured_global_frame": 18, "transient_seconds": .05}],
            "mastering": {"normalize": False, "true_peak_db": -1, "integrated_lufs": -16}}

    def _wav(self, name: str, samples: np.ndarray) -> None:
        with wave.open(str(self.root / name), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(self.rate)
            stream.writeframes(np.rint(samples * 32767).astype("<i2").tobytes())

    def _source(self, name: str) -> dict[str, str]:
        return {"file": name, "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest()}

    def _write(self, config: dict[str, Any] | None = None) -> Path:
        path = self.root / "audio-config.json"
        path.write_text(json.dumps(self.config if config is None else config), encoding="utf-8")
        return path

    def test_resampled_mix_keeps_source_hashes_clock_and_separate_stems(self) -> None:
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.glob("*.wav")}
        receipt = mix_audio.mix(self._write())
        output = Path(receipt["output_dir"])
        clock = json.loads((output / "actual-clock.json").read_text())
        provenance = json.loads((output / "provenance.json").read_text())
        self.assertEqual(clock["events"][0]["global_event_frame"], 36)
        self.assertEqual(clock["events"][0]["aligned_hit_sample"], 72000)
        self.assertEqual(clock["events"][0]["start_sample"], 70560)
        self.assertTrue(clock["events"][1]["speech_conflict"])
        self.assertLess(provenance["checks"]["footsteps.wav"]["sample_peak"], .01)
        self.assertFalse(provenance["mastering"]["time_stretch"])
        self.assertEqual(set(provenance["checks"]), {name + ".wav" for name in (*mix_audio.STEMS, "premaster", "final-mix")})
        with wave.open(str(output / "final-mix.wav")) as stream:
            self.assertEqual((stream.getframerate(), stream.getnframes()), (48000, 144000))
        for name, digest in before.items():
            self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), digest)

    def test_one_sample_ambience_does_not_broadcast_empty_edge_fade(self) -> None:
        self.config['ambience'][0].update(duration_seconds=1 / 48000, loop=False)
        receipt = mix_audio.mix(self._write())
        self.assertTrue(Path(receipt['output_dir'], 'ambience.wav').is_file())

    def test_placeholders_and_local_global_mismatch_are_rejected(self) -> None:
        for changes in ({"placement_status": "planned"}, {"measured_local_frame": None}, {"measured_global_frame": 37}):
            with self.subTest(changes=changes):
                config = copy.deepcopy(self.config)
                config["cues"][0].update(changes)
                with self.assertRaises(ValueError):
                    mix_audio.mix(self._write(config))
                self.assertFalse((self.root / "mix-v1").exists())

    def test_animal_and_food_cues_cannot_mask_guarded_words(self) -> None:
        for category in ("animal", "props"):
            config = copy.deepcopy(self.config)
            config["cues"][0].update(category=category, measured_local_frame=0, scene_start_global_frame=18)
            with self.assertRaisesRegex(ValueError, "speech guard conflict"):
                mix_audio.mix(self._write(config))
            config["cues"][0]["speech_policy"] = "attenuate"
            with self.assertRaisesRegex(ValueError, "Only footsteps"):
                mix_audio.mix(self._write(config))

    def test_hash_mismatch_and_truncated_source_are_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["voice"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            mix_audio.mix(self._write(config))
        path = self.root / "effect.wav"
        path.write_bytes(path.read_bytes()[:-1000])
        config = copy.deepcopy(self.config)
        for cue in config["cues"]:
            cue.update(self._source("effect.wav"))
        with self.assertRaisesRegex(ValueError, "duration mismatch|FFmpeg failed"):
            mix_audio.mix(self._write(config))

    def test_transient_crop_and_timeline_truncation_are_rejected(self) -> None:
        for changes in ({"transient_seconds": .01}, {"transient_seconds": .2},
                        {"measured_local_frame": 0, "scene_start_global_frame": 0}):
            with self.subTest(changes=changes):
                config = copy.deepcopy(self.config)
                config["cues"][0].update(changes)
                with self.assertRaises(ValueError):
                    mix_audio.mix(self._write(config))

    def test_finite_fields_and_explicit_ambient_loop_are_required(self) -> None:
        for mutate in (lambda c: c["voice"].update(gain_db=float("nan")),
                       lambda c: c["cues"][0].update(pan=2),
                       lambda c: c["ambience"][0].update(loop=False),
                       lambda c: c.update(duration_seconds=10 ** 1000)):
            config = copy.deepcopy(self.config)
            mutate(config)
            with self.assertRaises(ValueError):
                mix_audio.mix(self._write(config))

    def test_existing_version_is_never_overwritten(self) -> None:
        path = self._write()
        mix_audio.mix(path)
        final = self.root / "mix-v1/final-mix.wav"
        digest = hashlib.sha256(final.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "already exists"):
            mix_audio.mix(path)
        self.assertEqual(hashlib.sha256(final.read_bytes()).hexdigest(), digest)

    def test_normalization_is_disclosed_and_sample_clock_remains_exact(self) -> None:
        self.config["mastering"]["normalize"] = True
        output = Path(mix_audio.mix(self._write())["output_dir"])
        data = json.loads((output / "provenance.json").read_text())
        self.assertTrue(data["mastering"]["normalization_applied"])
        self.assertIn("first_pass", data["mastering"])
        self.assertEqual(data["checks"]["final-mix.wav"]["frames"], 144000)
        self.assertLessEqual(data["checks"]["final-mix.wav"]["true_peak_dbfs"], -.9)


if __name__ == "__main__":
    unittest.main()
