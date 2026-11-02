"""T-E28a round 7: a present-but-falsy hand-built audio row is a row (never silently skipped); slack once."""

from __future__ import annotations

import pytest

from av_fixtures import SR, _run, _world, np
from engine.core.errors import Refused
from engine.qa import av

_AUDIO = {"path": "a.wav", "sha256": "a" * 64}
_BINDING = {"name": "dlg A", "path": "a.wav", "sha256": "a" * 64, "start_frame": 10}


# ---- GAP: `if audio:` skipped "", 0, [], false, {} ------------------------------------------------------------
@pytest.mark.parametrize("bad", ["", 0, [], False, None, {}, "x", 1])
def test_a_present_audio_key_is_always_a_row_so_a_falsy_value_is_refused_not_skipped(bad) -> None:
    good = {"id": "A", "start_frame": 10, "audio": _AUDIO}  # a valid row beside it: the bad row must not just vanish
    dialogue = {"dialogue": [good, {"id": "B", "start_frame": 20, "audio": bad}]}
    cards = {"outro_cards": [{"term": "g", "start_frame": 10, "audio": _AUDIO},
                             {"term": "t", "start_frame": 20, "audio": bad}]}
    for rows in (dialogue, cards):
        with pytest.raises(Refused, match="audio"):
            av.bindings_from_config(rows)  # hand-built path
        with pytest.raises(Refused, match="audio"):
            av.bindings_from_config({"wav_bindings": [_BINDING], **rows})  # alongside wav_bindings


def test_an_absent_audio_key_is_still_a_row_without_audio() -> None:
    config = {"wav_bindings": [_BINDING], "dialogue": [{"id": "B", "start_frame": 10}],
              "outro_cards": [{"term": "t", "start_frame": 10}]}
    assert [b.name for b in av.bindings_from_config(config)] == ["dlg A"]


def test_a_review_config_whose_hand_built_audio_was_blanked_no_longer_passes_with_a_missing_row(tmp_path) -> None:
    video, config, runner = _world(tmp_path)
    config.pop("wav_bindings")
    good = {"path": "audio/a.wav", "sha256": _sha(tmp_path)}
    config["dialogue"] = [{"id": "A", "start_frame": 60, "audio": good}, {"id": "B", "start_frame": 60, "audio": good}]
    assert len(_run(tmp_path, config, video, runner)["wav_starts"]) == 2
    config["dialogue"][1]["audio"] = ""  # critic: S06_B audio "" -> PASS with 23 rows instead of 24
    with pytest.raises(Refused, match="audio"):
        _run(tmp_path, config, video, runner)


def _sha(tmp_path) -> str:
    from engine.core.io import sha256_file
    return sha256_file(tmp_path / "audio" / "a.wav")


# ---- LOW: the slack is subtracted once (inside pcm_identity), the floor has no extra margin -----------------
def _two_exports(tmp_path, diverge_sample: int):
    video, config, runner = _world(tmp_path)
    reference = tmp_path / "ref.mp4"
    reference.write_bytes(b"ref")
    base = runner.table[str(video.resolve())]
    runner.table[str(reference.resolve())] = base.copy()
    changed = base.copy()
    changed[diverge_sample:] += (0.2 * np.sin(2 * np.pi * 1000 * np.arange(len(base) - diverge_sample) / SR)
                                 ).astype(np.float32)
    runner.table[str(video.resolve())] = changed
    return video, reference, config, runner


def test_a_cli_window_one_sample_below_the_floor_is_partial_and_the_floor_itself_is_not(tmp_path) -> None:
    video, reference, config, runner = _two_exports(tmp_path, 6 * SR - 10)
    floor_frames = 150  # 5 s main film
    at_floor = _run(tmp_path, config, video, runner, reference=reference, reference_seconds=5.0,
                    main_frames=floor_frames)
    assert at_floor["partial"] is False and at_floor["verdict"] == "PASS"
    below = _run(tmp_path, config, video, runner, reference=reference, reference_seconds=5.0 - 1 / SR,
                 main_frames=floor_frames)
    assert below["partial"] is True and below["verdict"] == "PASS_PARTIAL"


def test_a_config_window_one_sample_below_the_floor_is_refused(tmp_path) -> None:
    video, reference, config, runner = _two_exports(tmp_path, 6 * SR - 10)
    config["qa"] = {"av": {"reference_seconds": 5.0 - 1 / SR}}
    with pytest.raises(Refused, match="main film"):
        _run(tmp_path, config, video, runner, reference=reference, main_frames=150)
