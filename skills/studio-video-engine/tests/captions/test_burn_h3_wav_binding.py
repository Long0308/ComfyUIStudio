"""Burn must bind --wav to the H3 preparation receipt before encoding."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.captions import burn as burn_mod
from engine.core.errors import Refused
from engine.core.io import sha256_file
from test_captions_gate import dump, prepare_burn, qualified_config  # noqa: F401 (fixture)


def _preparation(folder: Path, wav_sha256: str) -> Path:
    return dump(folder / "preparation.json", {"wav": {"sha256": wav_sha256}})


def test_matching_h3_wav_sha_proceeds_and_is_recorded(tmp_path, monkeypatch, qualified_config):
    args = prepare_burn(tmp_path, monkeypatch)
    preparation = _preparation(tmp_path, sha256_file(args["wav"]))
    args["h3_preparation"] = preparation

    receipt = burn_mod.burn(**args)

    assert args["out"].is_file()
    assert receipt["h3_preparation"] == {
        "path": str(preparation),
        "sha256": sha256_file(preparation),
        "receipt_wav_sha256": sha256_file(args["wav"]),
        "wav_sha256": sha256_file(args["wav"]),
        "required_by_domain": False,
    }
    assert receipt["inputs"]["h3_preparation"]["sha256"] == sha256_file(preparation)


def test_mismatching_h3_wav_sha_refuses_before_output(tmp_path, monkeypatch, qualified_config):
    args = prepare_burn(tmp_path, monkeypatch)
    args["h3_preparation"] = _preparation(tmp_path, "0" * 64)

    with pytest.raises(Refused, match="H3_WAV_MISMATCH"):
        burn_mod.burn(**args)

    assert not args["out"].exists()
    assert not (tmp_path / "final.burn-receipt.json").exists()
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_missing_h3_preparation_file_has_named_refusal(tmp_path, monkeypatch, qualified_config):
    args = prepare_burn(tmp_path, monkeypatch)
    args["h3_preparation"] = tmp_path / "missing-preparation.json"

    with pytest.raises(Refused, match="H3_PREPARATION_MISSING"):
        burn_mod.burn(**args)

    assert not args["out"].exists()


def test_domain_policy_can_require_h3_binding(tmp_path, monkeypatch, qualified_config):
    qualified_config.domain["captions"] = {"require_h3_binding": True}
    args = prepare_burn(tmp_path, monkeypatch)

    with pytest.raises(Refused, match="H3_PREPARATION_REQUIRED"):
        burn_mod.burn(**args)

    assert not args["out"].exists()


def test_h3_binding_remains_optional_without_domain_policy(tmp_path, monkeypatch, qualified_config):
    args = prepare_burn(tmp_path, monkeypatch)

    receipt = burn_mod.burn(**args)

    assert receipt["h3_preparation"] is None
