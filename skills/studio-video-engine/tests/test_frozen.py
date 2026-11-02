from __future__ import annotations

import json
from pathlib import Path

from engine import frozen
from engine.core.io import sha256_bytes

PLAN_SHA = "4d5a7c529a4dec74175d071ff1c32fca1b006163ae9e56b88632b3a3d9ec05a0"
EXECUTOR_PREFIX = "b71ae5d47b88"


def _manifest(tmp_path: Path, content: bytes, expected: str | None = None) -> Path:
    (tmp_path / "f.txt").write_bytes(content)
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps({"files": [{"path": "f.txt", "sha256": expected or sha256_bytes(content)}]}),
        encoding="utf-8",
    )
    return path


def test_verify_match_and_mismatch_and_missing(tmp_path: Path, capsys) -> None:
    ok = _manifest(tmp_path, b"abc")
    assert frozen.run_verify(ok, tmp_path) == 0
    assert "MATCH" in capsys.readouterr().out
    bad = _manifest(tmp_path, b"abc", expected="0" * 64)
    assert frozen.run_verify(bad, tmp_path) == 1
    assert "MISMATCH" in capsys.readouterr().out
    (tmp_path / "f.txt").unlink()
    assert frozen.run_verify(ok, tmp_path) == 1
    assert "MISSING" in capsys.readouterr().out


def test_pid_alive_for_self_and_garbage() -> None:
    import os

    assert frozen.pid_alive(os.getpid())
    assert not frozen.pid_alive(0)
    assert not frozen.pid_alive(-5)


def test_read_pid(tmp_path: Path) -> None:
    (tmp_path / "x.pid").write_text("123\n", encoding="ascii")
    assert frozen.read_pid({"pid_file": "x.pid"}, tmp_path) == 123
    assert frozen.read_pid({"pid_file": "nope.pid"}, tmp_path) is None
    assert frozen.read_pid({}, tmp_path) is None


def test_recorded_manifest_pins_known_values() -> None:
    files = {Path(f["path"]).name: f["sha256"] for f in frozen.load_manifest()["files"]}
    assert files["PRODUCTION-PLAN.json"] == PLAN_SHA
    assert files["execute_seedvr2_production_v004.py"].startswith(EXECUTOR_PREFIX)
    assert set(files) >= {
        "prepare_seedvr2_production_v004.py",
        "upscale_seedvr2_chunked.py",
        "comfy_guarded_submit.py",
    }


def test_real_frozen_files_match_read_only() -> None:
    results = frozen.verify_files(frozen.load_manifest())
    assert all(r.match for r in results), [r for r in results if not r.match]


def test_byte_size_is_compared_when_recorded(tmp_path: Path, capsys) -> None:
    (tmp_path / "f.txt").write_bytes(b"abc")
    path = tmp_path / "m.json"
    sha = sha256_bytes(b"abc")
    path.write_text(json.dumps({"files": [{"path": "f.txt", "sha256": sha, "bytes": 4}]}), encoding="utf-8")
    assert frozen.run_verify(path, tmp_path) == 1
    assert "MISMATCH" in capsys.readouterr().out
    path.write_text(json.dumps({"files": [{"path": "f.txt", "sha256": sha, "bytes": 3}]}), encoding="utf-8")
    assert frozen.run_verify(path, tmp_path) == 0


def test_real_manifest_records_bytes_for_every_file() -> None:
    assert all(isinstance(f.get("bytes"), int) for f in frozen.load_manifest()["files"])
