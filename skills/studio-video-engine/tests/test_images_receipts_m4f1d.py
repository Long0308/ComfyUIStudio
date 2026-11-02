"""M4-f1d: one receipt definition (``receipts.build_candidate``) and post-link rollback for ``register`` and ``native``.

If the receipt write fails after the final png was linked, the final png is removed, but only when this call created
it. A file that already sat at the final name is never removed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.errors import Refused
from engine.core.io import write_json_once
from engine.images import common, receipts, workflow_publish
from images_fixtures import make_png
from test_images_manifest_append_m4f1 import adopt_args, approve_candidate
from test_images_workflow_publish import Flow

FIXED_TIME = 1_700_000_000.25
SHOT = "S01_A"


def _ctx():
    return SimpleNamespace(episode_id="ep-m4f1d", domain_id="test-domain")


def _inputs(tmp_path):
    guide = {"role": "guide", "path": (tmp_path / "guide.png").as_posix(), "sha256": "g" * 64}
    placement = {"role": "placement", "path": (tmp_path / "placement.txt").as_posix(), "sha256": "p" * 64}
    refs = [{"role": "cast", "path": (tmp_path / "cast.png").as_posix(), "sha256": "c" * 64}]
    return {"guide": guide, "placement": placement, "refs": refs, "plan_sha256": "1" * 64}


def _body():
    # register() pops ref_hashes from the body, so every call gets a fresh dict.
    return {"route": "codex-builtin", "prompt_sha256": "b" * 64, "ref_hashes": [{"role": "cast", "sha256": "c" * 64}]}


def _register(tmp_path, source, out, inputs, body):
    return common.register(_ctx(), out, SHOT, source, inputs, body)


def test_register_receipt_bytes_equal_build_candidate_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "time", SimpleNamespace(time=lambda: FIXED_TIME))
    monkeypatch.setattr(workflow_publish, "publish_candidate", lambda *a, **k: {"stub": True})
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    out = tmp_path / "images"
    inputs = _inputs(tmp_path)

    # Way 1: the real register() writes the receipt to disk.
    registered = _register(tmp_path, source, out, inputs, _body())
    on_disk = (out / SHOT / "candidates" / f"{registered['output']['sha256'][:12]}.receipt.json").read_bytes()

    # Way 2: build_candidate() from the same inputs, serialised by the same writer.
    sha = registered["output"]["sha256"]
    final = out / SHOT / "candidates" / f"{sha[:12]}.png"
    body = _body()
    ref_hashes = body.pop("ref_hashes")  # register() takes ref_hashes out of the body and binds them in its place
    built = receipts.build_candidate(
        episode_id="ep-m4f1d", domain="test-domain", shot=SHOT, plan_sha256=inputs["plan_sha256"],
        created_at=FIXED_TIME, fields={**body, "guide": inputs["guide"], "placement": inputs["placement"],
                                       "ref_hashes": ref_hashes},
        output_path=final, sha256=sha, info=receipts.png_info(source))
    write_json_once(tmp_path / "expected.receipt.json", built, mode="ascii", stamp=True)
    expected = (tmp_path / "expected.receipt.json").read_bytes()

    assert on_disk == expected
    assert on_disk.startswith(b"{")  # ascii pretty JSON, same writer as every other receipt


def test_receipt_write_failure_after_link_removes_the_created_final(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "time", SimpleNamespace(time=lambda: FIXED_TIME))
    monkeypatch.setattr(workflow_publish, "publish_candidate", lambda *a, **k: {"stub": True})
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    out = tmp_path / "images"
    folder = out / SHOT / "candidates"
    folder.mkdir(parents=True)
    unrelated = make_png(folder / "unrelated.png", (250, 0, 0), (8, 8))
    unrelated_bytes = unrelated.read_bytes()
    sha = common.sha256_file(source)
    final = folder / f"{sha[:12]}.png"

    def refuse(*args, **kwargs):
        raise Refused("forced receipt failure")

    monkeypatch.setattr(common, "write_json_once", refuse)
    with pytest.raises(Refused, match="forced receipt failure"):
        _register(tmp_path, source, out, _inputs(tmp_path), _body())

    assert not final.exists(), "the final png this call linked must be removed again"
    assert not list(folder.glob("*.receipt.json"))
    assert unrelated.read_bytes() == unrelated_bytes
    assert not list(folder.glob(".*.tmp")), "temps of the attempt are removed too"


def test_receipt_failure_keeps_a_final_png_that_was_there_before(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "time", SimpleNamespace(time=lambda: FIXED_TIME))
    monkeypatch.setattr(workflow_publish, "publish_candidate", lambda *a, **k: {"stub": True})
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    out = tmp_path / "images"
    folder = out / SHOT / "candidates"
    folder.mkdir(parents=True)
    sha = common.sha256_file(source)
    final = folder / f"{sha[:12]}.png"
    final.write_bytes(source.read_bytes())  # same bytes, placed by someone else before this call
    before = final.read_bytes()

    def refuse(*args, **kwargs):
        raise OSError("disk full (forced)")

    monkeypatch.setattr(common, "write_json_once", refuse)
    with pytest.raises(OSError, match="disk full"):
        _register(tmp_path, source, out, _inputs(tmp_path), _body())

    assert final.is_file() and final.read_bytes() == before, "a pre-existing file is never removed"


def test_native_receipt_failure_after_link_removes_only_the_created_anchor(tmp_path, monkeypatch):
    flow = Flow(tmp_path)
    args, _ = adopt_args(flow, "native-rollback.png", color=(45, 70, 95))
    code, adopted = flow.run(*args)
    assert code == 0
    approve_candidate(flow, adopted["sha256"])

    native_dir = flow.out / SHOT / "native"
    native_dir.mkdir(parents=True, exist_ok=True)
    unrelated = make_png(native_dir / "unrelated-anchor.png", (0, 0, 255), (8, 8))
    unrelated_bytes = unrelated.read_bytes()

    def refuse(*args, **kwargs):
        raise Refused("forced native receipt failure")

    monkeypatch.setattr(common, "write_json_once", refuse)
    code, summary = flow.run("native", "--shot", SHOT, "--sha", adopted["sha256"][:12])

    assert code == 1 and "forced native receipt failure" in summary["error"]
    assert not list(native_dir.glob("S01_A-native*.png")), "the anchor this call linked must be removed"
    assert not list(native_dir.glob("*.receipt.json"))
    assert unrelated.read_bytes() == unrelated_bytes
    assert json.dumps(sorted(p.name for p in native_dir.iterdir())) == json.dumps(["unrelated-anchor.png"])


def _real_link():
    return os.link


def test_concurrent_identical_file_between_check_and_link_is_not_removed_by_rollback(tmp_path, monkeypatch):
    """Another writer puts an identical file at the final name after our pre-check, right before our os.link.

    Our link fails with FileExistsError and the file is not ours, so a receipt failure must leave it in place.
    """
    monkeypatch.setattr(common, "time", SimpleNamespace(time=lambda: FIXED_TIME))
    monkeypatch.setattr(workflow_publish, "publish_candidate", lambda *a, **k: {"stub": True})
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    out = tmp_path / "images"
    folder = out / SHOT / "candidates"
    folder.mkdir(parents=True)
    sha = common.sha256_file(source)
    final = folder / f"{sha[:12]}.png"
    real_link = _real_link()

    def concurrent_writer_wins(src, dst, *args, **kwargs):
        if Path(dst) == final:
            final.write_bytes(source.read_bytes())  # identical bytes, placed by the other writer
            raise FileExistsError(17, "File exists", str(dst))
        return real_link(src, dst, *args, **kwargs)

    def refuse(*args, **kwargs):
        raise Refused("forced receipt failure")

    monkeypatch.setattr(os, "link", concurrent_writer_wins)
    monkeypatch.setattr(common, "write_json_once", refuse)
    with pytest.raises(Refused, match="forced receipt failure"):
        _register(tmp_path, source, out, _inputs(tmp_path), _body())

    assert final.is_file() and final.read_bytes() == source.read_bytes(), "a file this call did not link is never removed"


def test_link_owned_returns_true_only_when_this_call_created_the_target(tmp_path):
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    sha = common.sha256_file(source)
    target = tmp_path / "out" / "x.png"
    assert common.link_new_file_owned(source, target, sha, "candidate image") is True
    assert target.read_bytes() == source.read_bytes()
    assert not list(target.parent.glob(".*.tmp")), "the temp copy is removed"


def test_link_owned_returns_false_for_an_identical_existing_target_and_keeps_it(tmp_path):
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    sha = common.sha256_file(source)
    target = tmp_path / "x.png"
    target.write_bytes(source.read_bytes())
    assert common.link_new_file_owned(source, target, sha, "candidate image") is False
    assert target.read_bytes() == source.read_bytes()


def test_link_owned_refuses_a_different_existing_target(tmp_path):
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    other = make_png(tmp_path / "other.png", (250, 0, 0), (8, 8))
    sha = common.sha256_file(source)
    target = tmp_path / "x.png"
    target.write_bytes(other.read_bytes())
    with pytest.raises(Refused, match="hash mismatch"):
        common.link_new_file_owned(source, target, sha, "candidate image")
    assert target.read_bytes() == other.read_bytes()


def test_rollback_unlink_failure_does_not_mask_the_original_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "time", SimpleNamespace(time=lambda: FIXED_TIME))
    monkeypatch.setattr(workflow_publish, "publish_candidate", lambda *a, **k: {"stub": True})
    source = make_png(tmp_path / "src.png", (10, 200, 30), (64, 40))
    out = tmp_path / "images"
    folder = out / SHOT / "candidates"
    folder.mkdir(parents=True)
    sha = common.sha256_file(source)
    final = folder / f"{sha[:12]}.png"
    real_unlink = Path.unlink

    def locked_final(self, *args, **kwargs):
        if self == final:
            raise PermissionError("locked by another process (forced)")
        return real_unlink(self, *args, **kwargs)

    def refuse(*args, **kwargs):
        raise Refused("forced receipt failure")

    monkeypatch.setattr(Path, "unlink", locked_final)
    monkeypatch.setattr(common, "write_json_once", refuse)
    with pytest.raises(Refused, match="forced receipt failure") as info:
        _register(tmp_path, source, out, _inputs(tmp_path), _body())

    assert any("locked by another process" in note for note in getattr(info.value, "__notes__", [])), \
        "the rollback failure is recorded on the original exception"


def test_build_candidate_refuses_fields_that_overwrite_identity_keys():
    base = dict(episode_id="ep", domain="d", shot=SHOT, plan_sha256="1" * 64, created_at=FIXED_TIME,
                output_path=Path("x.png"), sha256="a" * 64, info={"width": 1, "height": 1, "bytes": 1})
    for key in ("schema", "episode_id", "domain", "shot", "status", "created_at", "plan_sha256", "output"):
        with pytest.raises(Refused, match=key):
            receipts.build_candidate(**base, fields={key: "clash", "route": "r"})


def test_build_candidate_names_every_clashing_key():
    base = dict(episode_id="ep", domain="d", shot=SHOT, plan_sha256="1" * 64, created_at=FIXED_TIME,
                output_path=Path("x.png"), sha256="a" * 64, info={"width": 1, "height": 1, "bytes": 1})
    with pytest.raises(Refused) as info:
        receipts.build_candidate(**base, fields={"status": "x", "schema": "y", "route": "ok"})
    assert "schema" in str(info.value) and "status" in str(info.value)
    assert "route" not in str(info.value)
