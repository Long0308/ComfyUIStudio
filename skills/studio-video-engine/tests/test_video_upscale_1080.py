"""UPSCALE-1080-ADAPTER: adapter ``comfy-realesrgan-1080`` của group 04 (spec docs/specs/2026-10-31-video-1080-and-export-v002.md).

Không GPU, không mạng ngoài 127.0.0.1 (FakeComfy), ffprobe được thay bằng ``probe_media`` giả.  Adapter chỉ chạy khi
domain có qualification (nội dung đúng domain/backend) và route nêu ``crop_mode``; mã đáp xuống không bật production."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_comfy import FakeComfy
from test_video_cr_veng import native_path, rendered_world, upscale_args, why
from video_fixtures import CARTOON, SHOT, TOKEN, VideoWorld, run_video, sha_file, write_routes

from engine.core.errors import Refused
from engine.video import upscale as upscale_mod

NAME = "comfy-realesrgan-1080"
NATIVE = {"width": 864, "height": 480, "frames": 124, "fps": "24/1", "audio_streams": 1}
OUT = {"width": 1920, "height": 1080, "frames": 124, "fps": "24/1", "audio_streams": 1}


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def _qualification(tmp_path: Path, **override) -> Path:
    body = {"schema": "jjv/video-upscale-qualification/v1", "status": "qualified", "domain": CARTOON, "backend": NAME,
            "backend_contract": "comfy-realesrgan-1080/v1", "model": {"name": "RealESRGAN_x4plus.pth"}, **override}
    path = tmp_path / "qualification-1080.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _route(world: VideoWorld, tmp_path: Path, *, crop_mode: str | None = "center-crop", qualified: bool = True,
           **qual_override) -> None:
    entry = {}
    if qualified:
        qual = _qualification(tmp_path, **qual_override)
        entry = {NAME: {"path": str(qual), "sha256": sha_file(qual)}}
    write_routes(world.routes, {CARTOON: world.h3.template}, qualified={CARTOON: entry},
                 backends=["none", NAME])
    document = json.loads(world.routes.read_text("utf-8"))
    if crop_mode is not None:
        document["domains"][CARTOON]["upscale"]["crop_mode"] = crop_mode
    world.routes.write_text(json.dumps(document), encoding="utf-8")


def _comfy_makes_video(world: VideoWorld, fake: FakeComfy) -> None:
    """POST của graph upscale: ghi mp4 cho SaveVideo node '9'; POST của H3 (render) giữ nguyên bản cũ."""
    previous = fake.on_post
    output = world.h3.world.comfy_root / "output"

    def on_post(payload: dict, prompt_id: str):
        graph = payload["prompt"]
        if any(n["class_type"] == "UpscaleModelLoader" for n in graph.values()):
            name = f"{prompt_id}-up.mp4"
            (output / name).write_bytes(f"1080p-{prompt_id}".encode())
            return {"9": {"videos": [{"filename": name, "subfolder": "", "type": "output"}]}}
        return previous(payload, prompt_id)

    fake.on_post = on_post


def _probe(monkeypatch, *, output: dict | None = None) -> None:
    from engine.video import upscale_comfy

    def probe(path: Path) -> dict:
        return dict(output or OUT) if "1080p" in Path(path).name else dict(NATIVE)

    monkeypatch.setattr(upscale_comfy, "probe_media", probe)


def _ready(tmp_path, fake, monkeypatch, **route) -> VideoWorld:
    world = rendered_world(tmp_path, fake, monkeypatch)
    _route(world, tmp_path, **route)
    _comfy_makes_video(world, fake)
    return world


def _upscale(world: VideoWorld, *more: str):
    return run_video(upscale_args(world, native_path(world), "--backend", NAME, *more))


def _posts(fake: FakeComfy) -> int:
    return len(fake.posts_made())


def test_adapter_is_registered_and_shipped_route_still_runs_nothing() -> None:
    assert NAME in upscale_mod.REGISTRY
    routes = json.loads((Path(upscale_mod.__file__).parents[2] / "recipes" / "video" / "routes-v001.json").read_text("utf-8"))
    live = routes["domains"]["newtecons_live_action"]["upscale"]
    assert NAME in live["backends"] and live["default_backend"] == "none"
    assert live["qualified"] == {} and "crop_mode" in live and routes["take_gate"] == "first"


def test_unqualified_domain_refuses_and_sends_nothing(tmp_path, fake, monkeypatch) -> None:
    world = _ready(tmp_path, fake, monkeypatch, qualified=False)
    before = _posts(fake)
    code, result = _upscale(world, "--gpu-approved", TOKEN)
    assert code != 0 or result["gate"]["kind"] == "needs-gpu-pilot-approval", why(result)
    assert "UPSCALE_UNQUALIFIED" in why(result) and _posts(fake) == before
    assert world.state()["state"] == "rendered"


def test_qualification_of_another_domain_is_refused_before_submit(tmp_path, fake, monkeypatch) -> None:
    world = _ready(tmp_path, fake, monkeypatch, domain="newtecons_live_action")
    _probe(monkeypatch)
    before = _posts(fake)
    code, result = _upscale(world, "--gpu-approved", TOKEN)
    assert "domain" in why(result) and _posts(fake) == before and world.state()["state"] == "rendered"


def test_missing_crop_mode_is_refused_no_silent_default(tmp_path, fake, monkeypatch) -> None:
    world = _ready(tmp_path, fake, monkeypatch, crop_mode=None)
    _probe(monkeypatch)
    before = _posts(fake)
    code, result = _upscale(world, "--gpu-approved", TOKEN)
    assert "crop_mode" in why(result) and _posts(fake) == before and world.state()["state"] == "rendered"


def test_pad_mode_is_not_implemented_in_v1(tmp_path, fake, monkeypatch) -> None:
    world = _ready(tmp_path, fake, monkeypatch, crop_mode="pad")
    _probe(monkeypatch)
    before = _posts(fake)
    code, result = _upscale(world, "--gpu-approved", TOKEN)
    assert "crop_mode" in why(result) and _posts(fake) == before


def test_gpu_approval_is_required(tmp_path, fake, monkeypatch) -> None:
    world = _ready(tmp_path, fake, monkeypatch)
    _probe(monkeypatch)
    before = _posts(fake)
    code, result = _upscale(world)
    assert "GPU_APPROVAL_MISSING" in why(result) and _posts(fake) == before


def test_qualified_run_submits_one_pinned_graph_and_adopts_the_probed_output(tmp_path, fake, monkeypatch) -> None:
    world = _ready(tmp_path, fake, monkeypatch)
    _probe(monkeypatch)
    before = _posts(fake)
    code, result = _upscale(world, "--gpu-approved", TOKEN)
    assert code == 0 and result["gate"] is None, why(result)
    assert _posts(fake) == before + 1 and world.state()["state"] == "upscaled_1080"
    graph = fake.posts[-1]["prompt"]
    by_class = {n["class_type"]: n for n in graph.values()}
    assert by_class["UpscaleModelLoader"]["inputs"]["model_name"] == "RealESRGAN_x4plus.pth"
    scale = by_class["ImageScale"]["inputs"]
    assert (scale["width"], scale["height"], scale["crop"]) == (1920, 1080, "center")
    native = json.loads((world.out / SHOT / "render" / "r001" / "render-receipt.json").read_text("utf-8"))["native"]
    assert native["sha256"][:16] in by_class["LoadVideo"]["inputs"]["file"]
    assert (world.h3.settings().input_dir / by_class["LoadVideo"]["inputs"]["file"]).is_file()
    folder = world.out / SHOT / "upscale" / "r001"
    receipt = json.loads((folder / "upscale-receipt.json").read_text("utf-8"))
    assert receipt["backend"] == NAME and receipt["status"] == "verified" and receipt["shot"] == SHOT
    assert receipt["source"]["sha256"] == native["sha256"]
    out = Path(receipt["output"]["path"])
    assert out.is_file() and sha_file(out) == receipt["output"]["sha256"]
    assert (receipt["output"]["width"], receipt["output"]["height"], receipt["output"]["frames"]) == (1920, 1080, 124)
    assert receipt["qualification"]["sha256"] and receipt["geometry"]["crop_mode"] == "center-crop"
    assert receipt["execution"]["prompt_id"] and (folder / "workflow.api.json").is_file()
    assert (folder / "comfy" / "job.json").is_file()


@pytest.mark.parametrize("bad", [{"width": 1280}, {"frames": 123}, {"fps": "25/1"}, {"audio_streams": 0}])
def test_output_that_breaks_an_invariant_never_advances(tmp_path, fake, monkeypatch, bad) -> None:
    world = _ready(tmp_path, fake, monkeypatch)
    _probe(monkeypatch, output={**OUT, **bad})
    code, result = _upscale(world, "--gpu-approved", TOKEN)
    assert "UPSCALE_OUTPUT_INVALID" in why(result), why(result)
    assert world.state()["state"] == "rendered"
    assert not (world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").exists()


def test_wrapper_envelope_cannot_be_overridden_by_the_adapter(tmp_path, fake, monkeypatch) -> None:
    world = rendered_world(tmp_path, fake, monkeypatch)
    qual = _qualification(tmp_path, backend="evil")
    write_routes(world.routes, {CARTOON: world.h3.template},
                 qualified={CARTOON: {"evil": {"path": str(qual), "sha256": sha_file(qual)}}}, backends=["none", "evil"])

    class Evil:
        name, gpu = "evil", False

        def __init__(self, entry): ...

        def run(self, ctx, *, source, target, out_dir, shot, revision, gpu_approval, **_):
            out = out_dir / "o.mp4"
            out_dir.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x")
            return {"backend": "evil", "source": source, "output": {"path": str(out), "sha256": sha_file(out)},
                    "shot": "OTHER", "episode_id": "forged", "target": "1x1"}

    monkeypatch.setitem(upscale_mod.REGISTRY, "evil", Evil)
    code, result = run_video(upscale_args(world, native_path(world), "--backend", "evil"))
    assert code == 0, why(result)
    receipt = json.loads((world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").read_text("utf-8"))
    assert (receipt["shot"], receipt["target"]) == (SHOT, "1920x1080") and receipt["episode_id"] != "forged"


def test_adapter_refuses_without_comfy_handles(tmp_path) -> None:
    from engine.video import upscale_comfy

    backend = upscale_comfy.ComfyRealEsrgan1080({"path": str(_qualification(tmp_path)), "sha256": "0" * 64,
                                                 "route": {"crop_mode": "center-crop"}})
    with pytest.raises(Refused, match="NO_COMFY_HANDLES"):
        backend.run(None, source={}, target="1920x1080", out_dir=tmp_path, shot="S", revision=1, gpu_approval=None,
                    comfy=None, render_receipt={}, receipt_root=tmp_path)
