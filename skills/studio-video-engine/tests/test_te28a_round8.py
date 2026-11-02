"""T-E28a round 8: wav_bindings is required for an engine-built config; the binding source is recorded."""

from __future__ import annotations

import copy
import json

import pytest

from av_fixtures import _jjv, _run, _world
from editorial_fixtures import Inputs, REAL_ROOT
from engine.core.errors import Refused
from engine.editorial import build
from engine.qa import av, bindings


@pytest.fixture(scope="module")
def engine_config(tmp_path_factory) -> dict:
    return Inputs(tmp_path_factory.mktemp("r8")).build().config


def _mutated(engine_config: dict, how: str) -> dict:
    config = copy.deepcopy(engine_config)
    if how == "deleted":
        del config["wav_bindings"]
    else:
        config["wav_bindings"] = {"null": None, "empty": [], "dict": {"a": 1}, "string": "x", "zero": 0,
                                  "false": False}[how]
    return config


@pytest.mark.parametrize("how", ["deleted", "null", "empty", "dict", "string", "zero", "false"])
def test_an_engine_built_config_without_a_usable_wav_bindings_is_refused(engine_config, how: str) -> None:
    with pytest.raises(Refused, match="wav_bindings"):  # critic: PASS on the 12 outro-card rows only
        av.bindings_from_config(_mutated(engine_config, how))


@pytest.mark.parametrize("how", ["null", "empty", "dict", "string", "zero", "false"])
def test_a_present_wav_bindings_key_must_be_a_non_empty_list_even_in_a_hand_built_config(how: str) -> None:
    config = {"dialogue": [{"id": "A", "start_frame": 10, "audio": {"path": "a.wav", "sha256": "a" * 64}}]}
    config["wav_bindings"] = {"null": None, "empty": [], "dict": {"a": 1}, "string": "x", "zero": 0,
                              "false": False}[how]
    with pytest.raises(Refused, match="wav_bindings"):
        av.bindings_from_config(config)


def test_the_engine_marker_is_the_schema_the_build_writes_and_survives_in_a_real_build(engine_config) -> None:
    assert engine_config["schema"] == build.CONFIG_SCHEMA
    assert build.CONFIG_SCHEMA.startswith(bindings.ENGINE_CONFIG_SCHEMA_PREFIX)
    assert bindings.is_engine_config(engine_config)


def test_a_marker_stripped_engine_config_is_still_recognised_by_its_engine_shaped_rows(engine_config) -> None:
    config = copy.deepcopy(engine_config)
    for key in ("schema", "inputs", "motion", "word_timing"):
        config.pop(key)
    del config["wav_bindings"]
    assert bindings.is_engine_config(config)
    with pytest.raises(Refused, match="wav_bindings"):
        av.bindings_from_config(config)


def test_a_hand_built_config_without_the_marker_still_falls_back_to_its_audio_rows() -> None:
    real = json.loads((REAL_ROOT / "editorial" / "review-hd-v012" / "config" / "review-config-v012.json")
                      .read_text("utf-8-sig"))
    assert "wav_bindings" not in real and not bindings.is_engine_config(real)
    rows, source = bindings.resolve_bindings(real)
    assert source == "hand_built" and len(rows) == 24


def test_the_receipt_records_the_binding_source_and_row_count(tmp_path) -> None:
    video, config, runner = _world(tmp_path)
    receipt = _run(tmp_path, config, video, runner)
    assert receipt["binding_source"] == "wav_bindings" and receipt["binding_count"] == 1
    config["dialogue"] = [{"id": "A", "start_frame": 60, "audio": {
        "path": "audio/a.wav", "sha256": config["wav_bindings"][0]["sha256"]}}]
    del config["wav_bindings"]
    hand = _run(tmp_path, config, video, runner)
    assert hand["binding_source"] == "hand_built" and hand["binding_count"] == 1 and hand["verdict"] == "PASS"


def test_the_cli_table_shows_the_source(tmp_path, monkeypatch, capsys) -> None:
    from engine.qa import cli
    receipt = {"verdict": "PASS", "params": {"tolerance_ms": 1}, "wav_starts": [], "pcm_identity": None,
               "binding_source": "hand_built", "binding_count": 24}
    assert "hand_built" in cli._table(receipt) and "24" in cli._table(receipt)
