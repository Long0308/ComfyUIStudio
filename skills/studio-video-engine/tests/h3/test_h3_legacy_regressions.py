"""Regression tests for two legacy-cast engine defects found while stage A was applied.

D1: ``inputs._cast_parts`` dropped ``character_id`` from manifest face rows, so ``prepare`` could not find the cast approval.
D2: ``prepare`` legacy evidence omitted ``provenance.images_dir``, so the load-time recheck searched an empty path.

Neither test relaxes a refusal: a missing pack AND a missing legacy record still refuses (see test_h3_m7.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from h3_fixtures import SHOT, H3World
from test_h3_inputs_m8b import InputsWorld, library_stub  # noqa: F401  (library_stub: fixture)

from engine.h3 import prepare as prepare_mod

pytestmark = pytest.mark.usefixtures("library_stub")


def test_d1_builder_face_rows_carry_character_id_and_prepare_accepts_them(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    summary = world.build()
    manifest = json.loads(Path(summary["inputs"]).read_text(encoding="utf-8"))
    faces = manifest["shots"][0]["faces"]
    assert sorted(face["character_id"] for face in faces) == ["alice", "mom-alice"]
    result = prepare_mod.prepare(world.ctx(), Path(summary["inputs"]), tmp_path / "h3-d1")
    assert result["shots"][0]["shot"] == SHOT


def test_d2_receipt_records_images_dir_and_reload_rechecks_the_real_folder(tmp_path) -> None:
    world = H3World(tmp_path)
    world.prepare()
    manifest = json.loads(world.manifest.read_text(encoding="utf-8"))
    receipt = json.loads((world.out / SHOT / "preparation.json").read_text(encoding="utf-8"))
    assert receipt["legacy_cast_evidence"]["images_dir"] == manifest["provenance"]["images_dir"]
    assert prepare_mod.load_prepared(world.ctx(), world.out)  # reload re-runs the legacy recheck against that folder
