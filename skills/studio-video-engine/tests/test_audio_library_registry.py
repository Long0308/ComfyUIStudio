"""The library registry: validation, file checks, versioned writes with a backup, idempotent ``used_in`` (no GPU)."""

from __future__ import annotations

import json

import pytest
from audio_fixtures import write_tone
from test_audio_library_support import SCHEMA, bed_row, make_library, registry_bytes, standard_rows

from engine.audio import library
from engine.core.errors import Refused


def lib_with_beds(tmp_path):
    return make_library(tmp_path, standard_rows(tmp_path / "lib"))


def test_a_registry_of_the_wrong_schema_or_with_incomplete_rows_is_refused(tmp_path) -> None:
    lib = lib_with_beds(tmp_path)
    document, sha = library.load_registry(lib, SCHEMA)
    assert [b["id"] for b in document["beds"]][:2] == ["B-PASTORAL", "B-GUITAR"] and len(sha) == 64
    with pytest.raises(Refused, match="not a other/v9 document"):
        library.load_registry(lib, "other/v9")
    broken = json.loads(registry_bytes(lib))
    del broken["beds"][0]["vocal_gate"]["pass"]
    library.registry_path(lib).write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(Refused, match="vocal_gate lacks"):
        library.load_registry(lib, SCHEMA)


def test_check_file_names_every_reason_a_bed_cannot_be_used(tmp_path) -> None:
    lib = lib_with_beds(tmp_path)
    document, _ = library.load_registry(lib, SCHEMA)
    row = document["beds"][0]
    assert library.check_file(lib, row, rate=48000) == []
    write_tone(library.bed_path(lib, row).with_name("x.wav"), 30.0, 0.3, 262.0)
    library.bed_path(lib, row).write_bytes(library.bed_path(lib, row).with_name("x.wav").read_bytes())  # other bytes, same name
    assert any("bytes differ" in p for p in library.check_file(lib, row, rate=48000))
    assert library.check_file(lib, row, rate=44100, hash_file=False)[0].startswith("format 48000 Hz")
    library.bed_path(lib, row).unlink()
    assert library.check_file(lib, row, rate=48000) == ["file missing: B-PASTORAL-bed-48k.wav"]
    with pytest.raises(Refused, match="plain file name"):
        library.bed_path(lib, {**row, "file": "../x.wav"})


def test_used_in_is_appended_once_and_the_input_document_is_not_mutated(tmp_path) -> None:
    lib = lib_with_beds(tmp_path)
    document, _ = library.load_registry(lib, SCHEMA)
    entry = {"film": "05-next", "where": "film bed"}
    new, added = library.with_used_in(document, "B-GUITAR", entry)
    assert added and new["beds"][1]["used_in"] == [entry] and document["beds"][1]["used_in"] == []
    again, added_again = library.with_used_in(new, "B-GUITAR", {"film": "05-next", "where": "other"})
    assert not added_again and again["beds"][1]["used_in"] == [entry]
    with pytest.raises(Refused, match="not in the registry"):
        library.with_used_in(document, "NOPE", entry)


def test_a_registry_write_keeps_a_backup_bumps_the_revision_and_refuses_a_concurrent_edit(tmp_path) -> None:
    lib = lib_with_beds(tmp_path)
    before = registry_bytes(lib)
    document, sha = library.load_registry(lib, SCHEMA)
    new, _ = library.with_used_in(document, "B-PASTORAL", {"film": "05-next", "where": "film bed"})
    info = library.write_registry(lib, new, read_sha256=sha, schema=SCHEMA)
    assert info["revision"] == 1 and open(info["backup"], "rb").read() == before
    after = json.loads(registry_bytes(lib))
    assert after["revision"] == 1 and after["beds"][0]["used_in"][0]["film"] == "05-next" and after["updated"] >= "2026-10-27"
    with pytest.raises(Refused, match="changed since it was read"):  # the stale sha again: the file moved on
        library.write_registry(lib, new, read_sha256=sha, schema=SCHEMA)
    assert len(list(library.beds_dir(lib).glob("REGISTRY.json.bak-*"))) == 1


def test_bed_ids_duplicates_and_the_write_once_bed_file(tmp_path) -> None:
    lib = lib_with_beds(tmp_path)
    document, _ = library.load_registry(lib, SCHEMA)
    assert library.next_bed_id(document, "NEW-") == "NEW-1"
    extra = bed_row("NEW-4", "x", 30.0, 500.0, lib)
    grown = library.with_bed(document, extra)
    assert library.next_bed_id(grown, "NEW-") == "NEW-5"
    with pytest.raises(Refused, match="already in the registry"):
        library.with_bed(grown, extra)
    sha = library.add_bed_file(lib, library.bed_path(lib, extra), "copy-48k.wav")
    assert sha == extra["sha256"] and library.add_bed_file(lib, library.bed_path(lib, extra), "copy-48k.wav") == sha
    write_tone(lib / "other.wav", 30.0, 0.1, 100.0)
    with pytest.raises(Refused, match="refusing to overwrite"):
        library.add_bed_file(lib, lib / "other.wav", "copy-48k.wav")
