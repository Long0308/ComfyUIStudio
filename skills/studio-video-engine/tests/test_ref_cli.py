"""``jjv ref``: local filters, one-image fetch, host guard and receipt-backed rate limit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]


def _jjv():
    spec = importlib.util.spec_from_file_location("jjv_ref_cli", SKILL / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _index(library: Path, ref_type: str, group: str, header: str, rows: list[str]) -> None:
    folder = library / "by-type" / ref_type / group
    folder.mkdir(parents=True)
    (folder / "INDEX.csv").write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    _index(root, "costume", "spring", "id,source_url,tags_en,thumb", [
        "AUT-0001,https://ai-costume-gallery.pages.dev/png/AUT-0001.png,black;dress,True",
        "AUT-0002,https://ai-costume-gallery.pages.dev/png/AUT-0002.png,white;dress,True",
    ])
    _index(root, "pose", "standing", "full_png,id,pose_id,series_ja,source_url,thumb", [
        "True,P001_front,P001,standing,https://ai-pose-gallery.pages.dev/img/P001_front.png,True",
    ])
    return root


class _Response:
    def __init__(self, request, payload: bytes):
        self._request = request
        self._payload = payload
        self.headers = {"Content-Type": "image/png"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self._request.full_url

    def read(self):
        return self._payload


def test_search_filters_group_tag_and_limit_without_network(library, monkeypatch, capsys) -> None:
    import urllib.request

    def no_network(*_args, **_kwargs):
        raise AssertionError("search must not use the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    code = _jjv().main([
        "ref", "search", "--type", "costume", "--group", "spring", "--tag", "black",
        "--limit", "1", "--library-root", str(library),
    ])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["ids"] == ["AUT-0001"]
    assert out["count"] == 1


def test_single_fetch_writes_image_and_receipt(library, tmp_path, monkeypatch, capsys) -> None:
    import engine.ref.fetch as fetch_mod

    payload = b"\x89PNG\r\n\x1a\nreference"
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return _Response(request, payload)

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", opener)
    out_dir = tmp_path / "fetch-out"
    code = _jjv().main([
        "ref", "fetch", "--id", "AUT-0001", "--reason", "single wardrobe reference",
        "--out", str(out_dir), "--library-root", str(library),
    ])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    saved = out_dir / "AUT-0001.png"
    assert saved.read_bytes() == payload
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert len(calls) == 1
    assert calls[0][1] == 30
    assert calls[0][0].get_header("User-agent").startswith("jjv-ref/")

    receipt_lines = (out_dir / "ref-fetch-receipts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(receipt_lines) == 1
    receipt = json.loads(receipt_lines[0])
    assert set(receipt) == {"id", "url", "sha256", "bytes", "utc_time", "reason"}
    assert receipt["id"] == "AUT-0001"
    assert receipt["bytes"] == len(payload)
    assert receipt["reason"] == "single wardrobe reference"


def test_second_id_is_refused_before_network(library, tmp_path, monkeypatch, capsys) -> None:
    import urllib.request

    def no_network(*_args, **_kwargs):
        raise AssertionError("a multi-id request must be refused before the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    code = _jjv().main([
        "ref", "fetch", "--id", "AUT-0001", "--id", "AUT-0002",
        "--reason", "two references", "--out", str(tmp_path / "out"), "--library-root", str(library),
    ])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "exactly one --id" in out["error"]


def test_foreign_host_is_refused(tmp_path, monkeypatch, capsys) -> None:
    library = tmp_path / "library"
    _index(library, "costume", "foreign", "id,source_url,tags_en,thumb", [
        "BAD-1,https://example.com/BAD-1.png,black,True",
    ])
    import urllib.request

    def no_network(*_args, **_kwargs):
        raise AssertionError("a foreign host must be refused before the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    code = _jjv().main([
        "ref", "fetch", "--id", "BAD-1", "--reason", "test",
        "--out", str(tmp_path / "out"), "--library-root", str(library),
    ])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "not allowed" in out["error"]


def test_rate_limit_refuses_immediate_repeat(library, tmp_path, monkeypatch, capsys) -> None:
    import engine.ref.fetch as fetch_mod

    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return _Response(request, b"\x89PNG\r\n\x1a\nreference")

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", opener)
    argv = [
        "ref", "fetch", "--id", "AUT-0001", "--reason", "first",
        "--out", str(tmp_path / "out"), "--library-root", str(library),
    ]
    cli = _jjv()
    assert cli.main(argv) == 0
    capsys.readouterr()
    assert cli.main(argv) == 1
    out = json.loads(capsys.readouterr().out)
    assert "less than 10 seconds ago" in out["error"]
    assert len(calls) == 1
