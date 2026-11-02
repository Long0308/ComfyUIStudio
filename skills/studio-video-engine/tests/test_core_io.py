from __future__ import annotations

from pathlib import Path

import pytest

from engine.core import errors, io, paths


def test_sha256_known_vector(tmp_path: Path) -> None:
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert io.sha256_bytes(b"") == empty
    target = tmp_path / "a.bin"
    target.write_bytes(b"abc")
    assert io.sha256_file(target) == io.sha256_bytes(b"abc")


def test_canonical_modes_differ_only_for_non_ascii() -> None:
    plain = {"b": 1, "a": [True, None, 1.5]}
    assert io.canonical_json(plain, mode="ascii") == b'{"a":[true,null,1.5],"b":1}'
    assert io.canonical_json(plain, mode="ascii") == io.canonical_json(plain, mode="utf8")
    fancy = {"t": "a—b"}
    assert io.canonical_json(fancy, mode="ascii") == b'{"t":"a\\u2014b"}'
    assert io.canonical_json(fancy, mode="utf8") == '{"t":"a—b"}'.encode()
    assert io.canonical_sha256(fancy, mode="ascii") != io.canonical_sha256(fancy, mode="utf8")


def test_mode_is_explicit_and_validated() -> None:
    with pytest.raises(TypeError):
        io.canonical_json({})  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        io.canonical_json({}, mode="latin1")  # type: ignore[arg-type]


def test_key_order_does_not_change_hash() -> None:
    one, two = {"x": 1, "y": {"b": 1, "a": 2}}, {"y": {"a": 2, "b": 1}, "x": 1}
    assert io.canonical_sha256(one, mode="ascii") == io.canonical_sha256(two, mode="ascii")


def test_pretty_json_has_trailing_newline() -> None:
    assert io.pretty_json({"a": 1}, mode="ascii") == b'{\n  "a": 1\n}\n'


def test_write_once_creates_and_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "dir" / "r.json"
    digest = io.write_once(target, b"hello")
    assert target.read_bytes() == b"hello" and digest == io.sha256_bytes(b"hello")
    assert io.write_once(target, b"hello") == digest


def test_write_once_refuses_different_bytes_and_keeps_original(tmp_path: Path) -> None:
    target = tmp_path / "r.json"
    io.write_once(target, b"first")
    with pytest.raises(errors.Refused):
        io.write_once(target, b"second")
    assert target.read_bytes() == b"first"
    assert [p.name for p in tmp_path.iterdir()] == ["r.json"]


def test_write_once_refuses_directory_in_the_way(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    with pytest.raises(errors.Refused):
        io.write_once(tmp_path / "d", b"x")


def test_write_json_once(tmp_path: Path) -> None:
    target = tmp_path / "j.json"
    io.write_json_once(target, {"k": "—"}, mode="ascii")
    assert b"\\u2014" in target.read_bytes()
    with pytest.raises(errors.Refused):
        io.write_json_once(target, {"k": "other"}, mode="ascii")


def test_read_json_bom_and_failures(tmp_path: Path) -> None:
    good = tmp_path / "g.json"
    good.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
    assert io.read_json(good) == {"a": 1}
    bad = tmp_path / "b.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(errors.Uncertain):
        io.read_json(bad)
    with pytest.raises(errors.Uncertain):
        io.read_json(tmp_path / "missing.json")


def test_require_inside(tmp_path: Path) -> None:
    inner = tmp_path / "a" / "b.txt"
    assert paths.require_inside(inner, tmp_path, "x") == inner.resolve()
    assert paths.require_inside(tmp_path, tmp_path, "x") == tmp_path.resolve()
    with pytest.raises(errors.Refused):
        paths.require_inside(tmp_path / ".." / "out.txt", tmp_path, "x")
    with pytest.raises(errors.Refused):
        paths.require_inside(tmp_path.parent, tmp_path, "x")


def test_exit_codes_and_never_one_after_post() -> None:
    assert errors.Refused.exit_code == 1
    assert errors.Uncertain.exit_code == 2
    assert errors.WaitTimeout.exit_code == 3
    assert errors.Failed.exit_code == 4
    assert errors.exit_code_for(errors.Refused("x")) == 1
    assert errors.exit_code_for(errors.Refused("x"), posted=True) == 2
    assert errors.exit_code_for(errors.Failed("x"), posted=True) == 4
    assert errors.exit_code_for(RuntimeError("boom")) == 2
    assert errors.exit_code_for(RuntimeError("boom"), posted=True) == 2
