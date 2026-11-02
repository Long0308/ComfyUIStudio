"""N41b: every remaining engine site that reads an absolute path out of data goes through ``resolve_data_path``, so a
path recorded under a retired root (``machine.legacy_roots``) is read where the file lives now.  One test per site;
each writes the file under the CURRENT root only and hands the engine the RETIRED path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.config import loader
from engine.core.errors import Refused, Uncertain
from engine.deliver import init as deliver_init
from engine.edit import master_config as edit_master
from engine.editorial import master_config as editorial_master
from engine.h3 import inputs as h3_inputs
from engine.qa import preflight_audio
from engine.voice import receipts as voice_receipts


@pytest.fixture
def roots(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """``old`` (retired, does not exist) -> ``new`` (current); the default machine.json names the pair."""
    old, new = tmp_path / "retired-drive" / "03 Voice", tmp_path / "current-drive" / "03 Voice"
    new.mkdir(parents=True)
    machine = {"legacy_roots": {str(old): str(new)}}
    machine_file = tmp_path / "machine.json"
    machine_file.write_text(json.dumps(machine), encoding="utf-8")
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", machine_file)

    def file(relative: str, payload: bytes = b"bytes") -> tuple[Path, Path]:
        """Write ``relative`` under the current root; return (retired path the data records, current path on disk)."""
        target = new / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return old / relative, target

    return SimpleNamespace(old=old, new=new, machine=machine, file=file)


def test_h3_template_graph_recorded_under_a_retired_root_is_found(roots: SimpleNamespace, tmp_path: Path) -> None:
    recorded, on_disk = roots.file("assets/template.api.json", b"{}")
    ctx = SimpleNamespace(root=tmp_path / "ep", machine=roots.machine)
    assert h3_inputs._template(ctx, "S01_A", str(recorded)) == on_disk
    with pytest.raises(Refused, match="template graph not found"):
        h3_inputs._template(ctx, "S01_A", str(roots.old / "assets" / "nowhere.api.json"))


@pytest.mark.parametrize("module", [edit_master, editorial_master], ids=["edit", "editorial"])
def test_master_config_absolute_reads_a_retired_clip_path_where_it_lives_now(roots: SimpleNamespace, tmp_path: Path, module) -> None:
    recorded, on_disk = roots.file("technical/seam/S01_A-hf8.mp4")
    assert module._absolute(str(recorded), tmp_path / "base") == on_disk
    assert module._check_file(module._absolute(str(recorded), tmp_path / "base"), hashlib.sha256(b"bytes").hexdigest(), "clip") is None
    (tmp_path / "base" / "rel").mkdir(parents=True)
    (tmp_path / "base" / "rel" / "a.mp4").write_bytes(b"x")
    assert module._absolute("rel/a.mp4", tmp_path / "base") == (tmp_path / "base" / "rel" / "a.mp4").resolve()   # relative: as before


def test_voice_receipt_path_recorded_under_a_retired_root_is_found(roots: SimpleNamespace, tmp_path: Path) -> None:
    recorded, on_disk = roots.file("voice/native/S01_A-native.wav")
    assert voice_receipts.resolve_described(str(recorded), episode_root=tmp_path / "ep", out=None) == on_disk
    with pytest.raises(Uncertain, match="not found"):
        voice_receipts.resolve_described("native/nowhere.wav", episode_root=tmp_path / "ep", out=None)


def test_deliver_machine_path_under_a_retired_root_is_found(roots: SimpleNamespace, tmp_path: Path) -> None:
    recorded, on_disk = roots.file("brand/intro-v001/props.json", b"{}")
    machine = {**roots.machine, "brand": {"kit": str(recorded.parent)}, "publish": {"film_library": str(recorded)}}
    assert deliver_init._machine_path(machine, ("brand", "kit"), tmp_path) == str(on_disk.parent)
    assert deliver_init._machine_path(machine, ("publish", "film_library"), tmp_path, file=True) == str(on_disk)
    assert deliver_init._machine_path(machine, ("brand", "nope"), tmp_path) == {"missing": "MISSING_MACHINE_KEY:brand.nope"}
    gone = {**machine, "brand": {"kit": str(roots.old / "brand" / "nowhere")}}
    assert deliver_init._machine_path(gone, ("brand", "kit"), tmp_path) == {"missing": "MISSING_PATH:brand.kit"}


def test_preflight_music_receipt_stem_recorded_under_a_retired_root_is_found(roots: SimpleNamespace, tmp_path: Path) -> None:
    recorded, on_disk = roots.file("audio/music-v001/bed-48k.wav", b"RIFF-not-really")
    receipt = tmp_path / "ep" / "audio" / "music-finalize.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"stem": {"path": str(recorded), "sha256": hashlib.sha256(b"RIFF-not-really").hexdigest(),
                                            "vocal_gate": {"status": "PASS"}}}), encoding="utf-8")
    fails, notes, info = preflight_audio.music_receipt(receipt, "PASS", False)
    assert fails == [] and notes == [] and info == {"vocal_gate": "PASS", "stem": on_disk.name}
    receipt.write_text(json.dumps({"stem": {"path": str(roots.old / "audio" / "nowhere.wav"), "sha256": "0" * 64,
                                            "vocal_gate": {"status": "PASS"}}}), encoding="utf-8")
    with pytest.raises(Uncertain, match="music stem not found"):
        preflight_audio.music_receipt(receipt, "PASS", False)
