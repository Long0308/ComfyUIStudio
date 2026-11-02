"""``jjv layout render``: refusals (no Blender run), GPU lock + VRAM gate, take folders, and ONE real headless Blender
render (CPU, tiny) that proves the pass code runs and its depth/mask make sense."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.comfy.lock import existence_lock
from engine.core.errors import Refused
from engine.layout import render
from images_fixtures import EXAMPLES, World

BRIEF = EXAMPLES / "scene-layout.example.ep04-S01_A.cartoon.json"
MACHINE_LOCK = "gpu_lock_path"
REAL_BLENDER = os.environ.get("JJV_BLENDER") or shutil.which("blender") or next(
    (str(p) for p in sorted(Path("C:/Program Files/Blender Foundation").glob("Blender*/blender.exe"))), None)


class FakeBlender:
    """Records the argv; writes the beauty guide a real run would, exits with a chosen code."""

    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = Path(argv[argv.index("--out-dir") + 1])
        if "--no-render" not in argv:
            (out / "S01_A-spatial-layout-guide.png").write_bytes(b"\x89PNG-fake")
        return subprocess.CompletedProcess(argv, self.code, stdout='{"ok": 1}', stderr="")


def machine(tmp_path: Path) -> dict:
    return {MACHINE_LOCK: str(tmp_path / "gpu.lock")}


def test_compose_script_is_base_plus_passes_code_and_compiles(tmp_path):
    script = render.compose_script(BRIEF, ["depth", "mask"], tmp_path / "o", "base", 500.0)
    compile(script, "scene-and-passes", "exec")
    assert "def passes_main" in script and "BLENDER_WORKBENCH" in script
    assert "__PASS_CONFIG_JSON_PLACEHOLDER__" not in script and "__BRIEF_JSON_PLACEHOLDER__" not in script
    assert not list(BRIEF.parent.glob(".*.emit.py"))     # nothing is written next to the (read-only) brief


def test_cpu_passes_need_neither_the_gpu_lock_nor_a_vram_reading(tmp_path):
    fake = FakeBlender()
    vram_calls: list[int] = []
    receipt = render.render_shot(BRIEF, "S01_A", tmp_path, ["depth", "mask"], blender="blender.exe", machine=machine(tmp_path),
                                 runner=fake, vram_free=lambda: vram_calls.append(1) or None)
    assert receipt["status"] == "rendered" and receipt["gpu"]["gpu_used"] is False
    assert "--no-render" in fake.calls[0] and not vram_calls and not (tmp_path / "gpu.lock").exists()
    assert receipt["take"] == "r001" and (tmp_path / "render" / "S01_A" / "r001" / "render-receipt.json").is_file()
    assert receipt["tool"]["bpy_layout_passes_template.py"]


def test_beauty_takes_the_lock_checks_vram_and_records_both(tmp_path):
    fake = FakeBlender()
    receipt = render.render_shot(BRIEF, "S01_A", tmp_path, ["beauty", "depth"], blender="b", machine=machine(tmp_path),
                                 runner=fake, vram_free=lambda: 9000)
    assert receipt["gpu"]["free_vram_mib"] == 9000 and receipt["gpu"]["gpu_used"] is True
    assert "--no-render" not in fake.calls[0] and receipt["beauty"]["sha256"]
    assert not (tmp_path / "gpu.lock").exists()                     # released


@pytest.mark.parametrize("free, why", [(512, "512 MiB"), (None, "could not be read")])
def test_beauty_is_refused_without_enough_free_vram_and_blender_never_starts(tmp_path, free, why):
    fake = FakeBlender()
    with pytest.raises(Refused, match=why):
        render.render_shot(BRIEF, "S01_A", tmp_path, ["beauty"], blender="b", machine=machine(tmp_path), runner=fake,
                           vram_free=lambda: free)
    assert not fake.calls and not (tmp_path / "gpu.lock").exists()
    assert not (tmp_path / "render" / "S01_A" / "r001").exists()   # no half take left behind


def test_beauty_is_refused_while_another_job_holds_the_gpu_lock(tmp_path):
    fake = FakeBlender()
    policy = {"layout": {"render": {"min_free_vram_mib": 1, "timeout_seconds": 5, "lock_timeout_seconds": 0}}}
    with existence_lock(tmp_path / "gpu.lock", timeout_seconds=1):
        with pytest.raises(Refused, match="lock is held"):
            render.render_shot(BRIEF, "S01_A", tmp_path, ["beauty"], blender="b", machine=machine(tmp_path), runner=fake,
                               vram_free=lambda: 9000, recipe=policy)
        assert (tmp_path / "gpu.lock").exists()                       # a foreign lock is never removed
    assert not fake.calls


def test_a_take_is_never_overwritten_and_a_draft_brief_is_refused(tmp_path):
    fake = FakeBlender()
    render.render_shot(BRIEF, "S01_A", tmp_path, ["depth"], blender="b", machine=machine(tmp_path), runner=fake, take="r007")
    with pytest.raises(Refused, match="already exists"):
        render.render_shot(BRIEF, "S01_A", tmp_path, ["depth"], blender="b", machine=machine(tmp_path), runner=fake, take="r007")
    draft = tmp_path / "draft.json"
    document = json.loads(BRIEF.read_text("utf-8"))
    draft.write_text(json.dumps({**document, "status": "draft"}), encoding="utf-8")
    with pytest.raises(Refused, match="draft"):
        render.render_shot(draft, "S01_A", tmp_path, ["depth"], blender="b", machine=machine(tmp_path), runner=fake)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**document, "camera": {**document["camera"], "lens_mm": -3}}), encoding="utf-8")
    with pytest.raises(Refused, match="invalid"):
        render.render_shot(bad, "S01_A", tmp_path, ["depth"], blender="b", machine=machine(tmp_path), runner=fake)
    assert len(fake.calls) == 1


def test_a_failing_blender_leaves_a_receipt_and_raises(tmp_path):
    with pytest.raises(Exception, match="Blender exit 3"):
        render.render_shot(BRIEF, "S01_A", tmp_path, ["depth"], blender="b", machine=machine(tmp_path), runner=FakeBlender(3))
    receipt = json.loads((tmp_path / "render" / "S01_A" / "r001" / "render-receipt.json").read_text("utf-8"))
    assert receipt["status"] == "assertion_failed" and receipt["exit_code"] == 3


def test_passes_argument_and_blender_lookup_are_strict(tmp_path, monkeypatch):
    assert render.parse_passes("beauty, depth") == ["beauty", "depth"]
    for bad in ("", "normal", "depth,,x"):
        with pytest.raises(Refused):
            render.parse_passes(bad)
    monkeypatch.delenv("BLENDER", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(Refused, match="Blender not found"):
        render.find_blender(None, {"tools": {"blender_exe": str(tmp_path / "nope.exe")}})
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"")
    assert render.find_blender(str(exe), {}) == str(exe)


@pytest.mark.skipif(REAL_BLENDER is None, reason="Blender is not installed here")
def test_real_headless_blender_writes_depth_and_mask_passes_that_match_the_brief(tmp_path):
    numpy = pytest.importorskip("numpy")
    from PIL import Image

    receipt = render.render_shot(BRIEF, "S01_A", tmp_path, ["depth", "mask"], blender=REAL_BLENDER, machine=machine(tmp_path),
                                 width=192, height=108)
    folder = tmp_path / "render" / "S01_A" / "r001"
    base = "S01_A-spatial-layout"
    assert receipt["status"] == "rendered" and receipt["gpu"]["gpu_used"] is False
    passes = json.loads((folder / f"{base}-passes.json").read_text("utf-8"))
    assert passes["width"] == 192 and passes["height"] == 108 and passes["hit_pixels"] > 0
    depth = numpy.array(Image.open(folder / f"{base}-depth.png"))
    assert depth.dtype == numpy.uint16 and depth.shape == (108, 192) and depth.max() == 65535
    raw = numpy.load(folder / f"{base}-depth-raw.npy")
    assert raw.shape == (108, 192) and 0 < raw[raw > 0].min() < raw.max()
    ident = numpy.array(Image.open(folder / f"{base}-mask-id.png")).astype(int)
    index = ident[..., 0] + 256 * ident[..., 1]
    legend = passes["mask"]["legend"]
    for who in ("ALICE", "MOTHER", "COW_A", "COW_B", "MILKMAID"):
        mask = numpy.array(Image.open(folder / f"{base}-mask-{who}.png"))
        assert mask.dtype == numpy.uint8 and set(numpy.unique(mask)) <= {0, 255}
        assert int((mask == 255).sum()) == legend[who]["pixels"] == int((index == legend[who]["index"]).sum()) > 0
    assert receipt["files"] and all(f["sha256"] for f in receipt["files"])
