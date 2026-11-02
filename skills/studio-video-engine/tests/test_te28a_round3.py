"""T-E28a round 3: the remaining fail-open gaps of ``qa av`` and ``editorial build-config`` (F1-F6)."""

from __future__ import annotations

import copy
import json

import pytest

from av_fixtures import FPS, HAS_FFMPEG, SR, P, _jjv, _noise, _run, _world, np
from editorial_fixtures import Inputs
from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.editorial import sources
from engine.qa import av


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


def _silent_row(binding_start: int, window_start: int = 60, *, mix=None, max_rms: float = 0.04) -> dict:
    quiet = np.full(SR, 1e-5, dtype=np.float32)
    spec = {"start_frame": window_start, "end_frame_exclusive": window_start + 30, "max_rms": max_rms}
    binding = av.Binding("sleep", "s.wav", "a" * 64, binding_start, spec)
    return av.check_binding(_noise(6.0, 1, 0.01) if mix is None else mix, quiet, binding, fps=FPS, params=P,
                            actual_sha256="a" * 64)


# ---- F1: a silent WAV bound away from its declared window ---------------------------------------------
def test_f1_a_silent_binding_moved_off_its_window_fails() -> None:
    row = _silent_row(binding_start=90, window_start=60)  # critic case Q5: start_frame += 30
    assert row["status"] == "silent-misplaced" and row["ok"] is False and row["placement_proven"] is False
    assert "60" in row["reason"] and "90" in row["reason"]


def test_f1_a_silent_binding_at_its_window_start_still_passes() -> None:
    row = _silent_row(binding_start=60, window_start=60)
    assert row["status"] == "silent-declared" and row["ok"] is True


def test_f1_the_receipt_verdict_is_fail_for_a_misplaced_silent_wav(tmp_path) -> None:
    video, config, runner = _world(tmp_path)
    from av_fixtures import _write_wav
    quiet = tmp_path / "audio" / "quiet.wav"
    sha = _write_wav(quiet, np.full(SR, 1e-5, dtype=np.float32))
    runner.table[str(quiet.resolve())] = np.full(SR, 1e-5, dtype=np.float32)
    config["wav_bindings"].append({"name": "dlg Q", "path": "audio/quiet.wav", "sha256": sha, "start_frame": 180,
                                   "expect_silent": {"start_frame": 150, "end_frame_exclusive": 180,
                                                     "max_rms": 0.04}})
    receipt = _run(tmp_path, config, video, runner)
    assert receipt["verdict"] == "FAIL" and receipt["wav_starts"][1]["status"] == "silent-misplaced"
    assert receipt["caveats"] == []  # a failure is not a caveat


# ---- F4: start frames must be integers --------------------------------------------------------------
@pytest.mark.parametrize("bad", [240.9, 240.0, True, "240", None])
def test_f4_a_non_integer_start_frame_is_refused(bad) -> None:
    config = {"wav_bindings": [{"name": "a", "path": "a.wav", "sha256": "a" * 64, "start_frame": bad}]}
    with pytest.raises(Refused, match="start_frame"):
        av.bindings_from_config(config)


@pytest.mark.parametrize("field,bad", [("start_frame", 12.5), ("offset_frames", 1.5)])
def test_f4_hand_built_dialogue_rows_need_integer_frames(field: str, bad) -> None:
    audio = {"path": "a.wav", "sha256": "a" * 64, "offset_frames": 0}
    entry = {"id": "A", "start_frame": 10, "audio": audio}
    (audio if field == "offset_frames" else entry)[field] = bad
    with pytest.raises(Refused, match=field):
        av.bindings_from_config({"dialogue": [entry]})


def test_f4_a_hand_built_card_needs_an_integer_start_frame() -> None:
    card = {"term": "x", "start_frame": 7.5, "audio": {"path": "a.wav", "sha256": "a" * 64}}
    with pytest.raises(Refused, match="start_frame"):
        av.bindings_from_config({"outro_cards": [card]})


# ---- F5: a malformed expect_silent is a rule violation (exit 1), not a KeyError (exit 2) -----------------
@pytest.mark.parametrize("spec", [
    {"start_frame": 2110, "end_frame_exclusive": 2160},                       # missing max_rms (critic T1)
    {"start_frame": 2110, "max_rms": 0.04},                                  # missing end
    {"start_frame": 2110, "end_frame_exclusive": 2160, "max_rms": 0.04, "x": 1},  # unknown key
    {"start_frame": 2110.5, "end_frame_exclusive": 2160, "max_rms": 0.04},   # float frame
    {"start_frame": 2160, "end_frame_exclusive": 2110, "max_rms": 0.04},     # empty window
    {"start_frame": 2110, "end_frame_exclusive": 2160, "max_rms": 0},        # zero bound
    {"start_frame": 2110, "end_frame_exclusive": 2160, "max_rms": "0.04"},
    "oops",
])
def test_f5_a_malformed_expect_silent_is_refused(spec) -> None:
    config = {"wav_bindings": [{"name": "s", "path": "s.wav", "sha256": "a" * 64, "start_frame": 2110,
                                "expect_silent": spec}]}
    with pytest.raises(Refused, match="expect_silent"):
        av.bindings_from_config(config)


def test_f5_a_binding_missing_a_key_is_refused_not_a_keyerror() -> None:
    for drop in ("name", "path", "start_frame"):
        row = {"name": "s", "path": "s.wav", "sha256": "a" * 64, "start_frame": 1}
        del row[drop]
        with pytest.raises(Refused, match=drop):
            av.bindings_from_config({"wav_bindings": [row]})


@pytest.mark.skipif(not HAS_FFMPEG, reason="the CLI resolves ffmpeg before running")
def test_f5_the_cli_exits_1_for_a_malformed_expect_silent(tmp_path, capsys) -> None:
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"wav_bindings": [{
        "name": "s", "path": "s.wav", "sha256": "a" * 64, "start_frame": 2110,
        "expect_silent": {"start_frame": 2110, "end_frame_exclusive": 2160}}]}), encoding="utf-8")
    code = _jjv().main(["qa", "av", "--episode", "04-milk-and-mom", "--video", str(tmp_path / "v.mp4"),
                        "--config", str(config), "--json", "--allow-outside", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1 and "KeyError" not in out and "expect_silent" in out


# ---- F6: max_rms has an upper bound ----------------------------------------------------------------
def test_f6_the_engine_ceiling_and_the_schema_maximum_are_one_number() -> None:
    schema = json.loads((SKILL_ROOT / "schemas" / "boundaries.schema.json").read_text("utf-8"))
    assert schema["$defs"]["silent_window"]["properties"]["max_rms"]["maximum"] == av.SILENT_MAX_RMS_CEILING
    assert schema["$defs"]["silent_bound"]["properties"]["max_rms"]["maximum"] == av.SILENT_MAX_RMS_CEILING


def test_f6_the_ceiling_sits_below_the_quietest_dialogue_line_of_the_reference_episode() -> None:
    # measured on ep04: quietest dialogue WAV RMS 0.0731 (S06_B1); ceiling must be below it
    assert 0 < av.SILENT_MAX_RMS_CEILING < 0.0731


@pytest.mark.parametrize("value", [1.0, 0.06, av.SILENT_MAX_RMS_CEILING * 1.01])
def test_f6_a_max_rms_above_the_ceiling_is_refused(value: float) -> None:
    spec = {"start_frame": 60, "end_frame_exclusive": 90, "max_rms": value}
    with pytest.raises(Refused, match="max_rms"):
        av.bindings_from_config({"wav_bindings": [{"name": "s", "path": "s.wav", "sha256": "a" * 64,
                                                   "start_frame": 60, "expect_silent": spec}]})


def test_f6_the_ceiling_itself_is_accepted() -> None:
    spec = {"start_frame": 60, "end_frame_exclusive": 90, "max_rms": av.SILENT_MAX_RMS_CEILING}
    rows = av.bindings_from_config({"wav_bindings": [{"name": "s", "path": "s.wav", "sha256": "a" * 64,
                                                      "start_frame": 60, "expect_silent": spec}]})
    assert rows[0].expect_silent["max_rms"] == av.SILENT_MAX_RMS_CEILING


def test_f6_a_quiet_tone_over_the_ep04_bed_fails_at_the_ep04_bound() -> None:
    """ep04 S06_B3 bed RMS 0.0279; a 0.05-amplitude tone on top measures ~0.045 (critic N12)."""
    rng = np.random.default_rng(3)
    mix = (rng.standard_normal(6 * SR) * 0.0279).astype(np.float32)
    first, last = int(2.0 * SR), int(3.0 * SR)
    t = np.arange(last - first) / SR
    quiet_tone = mix.copy()
    quiet_tone[first:last] += (0.05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    bed_only = _silent_row(60, 60, mix=mix, max_rms=0.04)
    toned = _silent_row(60, 60, mix=quiet_tone, max_rms=0.04)
    assert bed_only["ok"] and bed_only["expect_silent"]["export_rms"] == pytest.approx(0.0279, rel=0.1)
    assert not toned["ok"] and toned["expect_silent"]["export_rms"] > 0.04


def test_f6_the_ep04_boundaries_value_is_within_the_ceiling_and_above_the_measured_bed() -> None:
    from editorial_fixtures import REAL_BOUNDARIES
    window = json.loads(REAL_BOUNDARIES.read_text("utf-8"))["expect_silent"][0]
    assert 0.0279 < window["max_rms"] <= av.SILENT_MAX_RMS_CEILING


# ---- F2: one source of truth for the WAV offset (shots.json wav_binding.offset_s) ----------------------
def _with_offset_s(inputs: Inputs, shot_id: str, offset_s: float) -> None:
    shots = copy.deepcopy(inputs.config.shots)
    next(s for s in shots if s["shot"] == shot_id)["wav_binding"]["offset_s"] = offset_s
    inputs.with_config(shots=shots)


def test_f2_a_timing_only_offset_is_refused(inputs: Inputs) -> None:
    inputs.entry("S04_B")["audio"]["offset_frames"] = 3  # critic BX4: shots.json offset_s stays 0
    with pytest.raises(Refused, match="offset"):
        inputs.build()


def test_f2_a_shots_only_offset_is_refused(inputs: Inputs) -> None:
    _with_offset_s(inputs, "S04_B", 0.1)  # 3 frames at 30 fps; the word timing does not know
    with pytest.raises(Refused, match="offset"):
        inputs.build()


def test_f2_agreeing_offsets_move_binding_and_icons_together(inputs: Inputs) -> None:
    base = inputs.build()
    _with_offset_s(inputs, "S04_B", 0.1)
    inputs.entry("S04_B")["audio"]["offset_frames"] = 3
    moved = inputs.build()
    old = {e["id"]: e["frame"] for e in base.events["icon_events"] if e["shot"] == "S04_B"}
    new = {e["id"]: e["frame"] for e in moved.events["icon_events"] if e["shot"] == "S04_B"}
    assert old and all(new[key] == old[key] + 3 for key in old)
    bindings = {b["name"]: b["start_frame"] for b in moved.config["wav_bindings"]}
    assert bindings["dlg S04_B"] == {b["name"]: b["start_frame"] for b in base.config["wav_bindings"]}["dlg S04_B"] + 3


def test_f2_the_icon_offset_comes_from_the_shots_binding_not_the_timing_file() -> None:
    entry = {"start_frame": 100, "audio": {"offset_frames": 99}}
    word = {"start_frame": 110, "start_s": 3.6, "raw_whisper_start_s": None}
    assert sources.captions.pop_frame(entry, word, 30, offset_frames=2)[0] == 112


def test_f2_a_silent_shot_with_a_nonzero_offset_is_refused(inputs: Inputs) -> None:
    """Placement of a silent WAV is unprovable, so its binding must start exactly at its window."""
    _with_offset_s(inputs, "S06_B3", 0.1)
    inputs.entry("S06_B")["audio"]["offset_frames"] = 3
    with pytest.raises(Refused, match="silent"):
        inputs.build()


# ---- F3: single-shot dialogue timing needs its audio.sha256 ------------------------------------------
def test_f3_a_single_shot_entry_without_audio_sha_is_refused(inputs: Inputs) -> None:
    del inputs.entry("S01_B")["audio"]["sha256"]  # critic T3
    with pytest.raises(Refused, match="sha256"):
        inputs.build()


def test_f3_a_single_shot_entry_without_audio_block_is_refused(inputs: Inputs) -> None:
    del inputs.entry("S01_B")["audio"]
    with pytest.raises(Refused, match="sha256"):
        inputs.build()


def test_f3_a_wrong_sha_is_still_refused(inputs: Inputs) -> None:
    inputs.entry("S01_B")["audio"]["sha256"] = "0" * 64
    with pytest.raises(Refused, match="word timing was measured on WAV"):
        inputs.build()
