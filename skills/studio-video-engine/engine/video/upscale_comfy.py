"""Adapter ``comfy-realesrgan-1080`` của group ``04 LÊN 1080P`` (spec docs/specs/2026-10-31-video-1080-and-export-v002.md §2).

Domain-neutral, KHÔNG qualified cho domain nào: factory chỉ được gọi khi ``routes upscale.qualified`` của ĐÚNG domain
trỏ tới receipt qualification (path + sha256) và nội dung receipt khớp domain/backend.  Graph API ghim take native của
render receipt theo sha: LoadVideo -> GetVideoComponents -> RealESRGAN x4 -> ImageScale 1920x1080 -> CreateVideo ->
SaveVideo.  Gửi qua ĐÚNG đường guarded của H3 (``comfy.dispatch``: khoá submit, hàng đợi rỗng, intent O_EXCL, container
identity) dưới khoá EXECUTOR do wrapper ``upscale()`` giữ; adopt output sau khi ffprobe khớp mọi bất biến.
"""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..comfy import commands
from ..comfy.dispatch import SUBMITTED_FILE, dispatch
from ..comfy.staging import link_new_file, require_hash, stage_input
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..h3.submit import COMFY_DIR, container_instance
from . import state as state_mod
from . import tiers

NAME = "comfy-realesrgan-1080"
CONTRACT = "comfy-realesrgan-1080/v1"
QUALIFICATION_SCHEMA = "jjv/video-upscale-qualification/v1"
TARGET = "1920x1080"
CROP_MODES = {"center-crop": "center"}  # route crop_mode -> ImageScale.crop; "pad" là recipe khác, chưa có
SAVE_NODE = "9"
CLIENT_PREFIX = "jjv-up-"


def probe_media(path: Path) -> dict[str, Any]:
    """ffprobe (đếm frame thật): ``width,height,frames,fps(rational rút gọn),audio_streams``.  Thiếu số liệu ⇒ Refused."""
    command = ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)]
    try:
        raw = subprocess.run(command, capture_output=True, text=True, timeout=600, check=True).stdout
        streams = json.loads(raw)["streams"]
        video = next(s for s in streams if s.get("codec_type") == "video")
        fps = Fraction(video["r_frame_rate"])
        return {"width": int(video["width"]), "height": int(video["height"]), "frames": int(video["nb_read_frames"]),
                "fps": f"{fps.numerator}/{fps.denominator}",
                "audio_streams": sum(1 for s in streams if s.get("codec_type") == "audio")}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration, ZeroDivisionError) as error:
        raise Refused(f"MEDIA_PROBE_FAILED: ffprobe could not measure {path}: {error!r}; nothing is adopted") from error


def build_graph(input_name: str, model_name: str, crop: str, width: int, height: int, prefix: str) -> dict[str, Any]:
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"file": input_name}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model_name}},
        "4": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["3", 0], "image": ["2", 0]}},
        "5": {"class_type": "ImageScale", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "width": width,
                                                     "height": height, "crop": crop}},
        "6": {"class_type": "CreateVideo", "inputs": {"images": ["5", 0], "fps": ["2", 2], "audio": ["2", 1]}},
        SAVE_NODE: {"class_type": "SaveVideo", "inputs": {"video": ["6", 0], "filename_prefix": prefix,
                                                          "format": "mp4", "format.codec": "h264"}},
    }


class ComfyRealEsrgan1080:
    name = NAME
    gpu = True

    def __init__(self, entry: dict[str, Any]) -> None:
        self.entry = entry

    # ---- preflight: mọi từ chối TRƯỚC khi gửi -------------------------------------------------------------
    def _crop(self) -> str:
        mode = (self.entry.get("route") or {}).get("crop_mode")
        if mode not in CROP_MODES:
            raise Refused(f"UPSCALE_CROP_MODE: routes upscale.crop_mode must be one of {sorted(CROP_MODES)}, got "
                          f"{mode!r}; there is no default crop/pad (user must choose the framing); nothing was sent")
        return CROP_MODES[mode]

    def _qualification(self, domain: str) -> dict[str, Any]:
        body = read_json(Path(self.entry["path"]))
        problems = [f"{key}={body.get(key)!r}" for key, want in (("schema", QUALIFICATION_SCHEMA), ("status", "qualified"),
                                                                 ("backend", NAME), ("backend_contract", CONTRACT),
                                                                 ("domain", domain)) if body.get(key) != want]
        model = (body.get("model") or {}).get("name")
        if not isinstance(model, str) or not model:
            problems.append("model.name missing")
        if problems:
            raise Refused(f"UPSCALE_QUALIFICATION_INVALID: qualification receipt for domain {domain!r} is not valid for "
                          f"{NAME}: {problems}; nothing was sent")
        return body

    def _provenance(self, render: dict[str, Any], root: Path) -> dict[str, Any]:
        if render.get("promotion"):
            raise Refused("TIER_CONTEXT_REQUIRED: promoted source provenance must be checked against the episode")
        preparation = state_mod.verify_ref(root, render.get("preparation"), "preparation")
        wav = preparation.get("wav") or {}
        wav_path = Path(str(wav.get("path")))
        require_hash(wav_path if wav_path.is_absolute() else root / wav_path, str(wav.get("sha256")), "conditioning WAV")
        return {"preparation_receipt": {"path": render["preparation"]["path"], "sha256": render["preparation"]["sha256"]},
                "conditioning_wav": {"path": str(wav.get("path")), "sha256": wav["sha256"]}}

    def run(self, ctx: Any, *, source: dict[str, Any], target: str, out_dir: Path, shot: str, revision: int,
            gpu_approval: dict[str, Any] | None, comfy: Any, render_receipt: dict[str, Any],
            receipt_root: Path) -> dict[str, Any]:
        if target not in (TARGET, tiers.profile('2k')['target']):
            raise Refused(f"UPSCALE_TARGET: {NAME} only supports {TARGET}, got {target!r}; nothing was sent")
        crop = self._crop()
        if comfy is None:
            raise Refused("NO_COMFY_HANDLES: GPU upscale needs injected ComfyHandles; nothing was sent")
        qualification = self._qualification(ctx.domain_id)
        if target != TARGET and target not in qualification.get("targets", []):
            raise Refused("UPSCALE_TARGET_UNQUALIFIED: 2k needs its own target in this domain's qualification receipt")
        if target == tiers.profile('2k')['target'] and not render_receipt.get("promotion"):
            raise Refused("TIER_APPROVAL_REQUIRED: 2k upscale needs a frozen plan and approved Full HD promotion")
        if render_receipt.get("promotion"):
            plan = state_mod.read_plan(receipt_root)
            sources = tiers.validate(ctx, plan)
            if plan['resolution']['target'] != target:
                raise Refused("TIER_PLAN_DRIFT: upscale target must match the frozen promotion plan")
            if sources.get(shot) != render_receipt["promotion"].get("source") or sources.get(shot) != {
                    key: source.get(key) for key in ("path", "sha256")}:
                raise Refused("TIER_SOURCE_DRIFT: upscale must consume the approved previous-tier clip")
            provenance = {"tier_approval": plan["resolution"]["approval"], "approved_source": sources[shot],
                          "audio_rule": "preserve the approved clip audio; no conditioning WAV replacement or trim"}
        else:
            provenance = self._provenance(render_receipt, Path(receipt_root))
        native = Path(source["path"])
        require_hash(native, source["sha256"], "native take")
        measured = probe_media(native)
        out_dir = Path(out_dir)
        settings, client = comfy.settings, comfy.client
        ready_report, ready = commands.cmd_check(client, settings, ps=comfy.ps)
        if not ready:
            raise Refused(f"ComfyUI is not ready for {shot} upscale: {ready_report['problems']}; nothing was sent")
        width, height = (int(v) for v in target.split("x"))
        input_name = f"jjv-up-{source['sha256'][:16]}{native.suffix or '.mp4'}"
        graph = build_graph(input_name, qualification["model"]["name"], crop, width, height,
                            f"jjv-up/{shot}-{state_mod.rev(revision)}-{source['sha256'][:12]}")
        out_dir.mkdir(parents=True, exist_ok=True)
        graph_file = out_dir / "workflow.api.json"
        write_json_once(graph_file, graph, mode="utf8")
        stage_input(native, settings.input_dir, input_name, source["sha256"])
        comfy_dir = out_dir / COMFY_DIR
        if not (comfy_dir / SUBMITTED_FILE).is_file():  # đã POST rồi thì chỉ chờ, không bao giờ POST lại
            identity = {"kind": "video-upscale", "stage": "video-upscale", "shot": shot, "episode_id": ctx.episode_id,
                        "source_sha256": source["sha256"]}
            dispatch(client, settings, graph=graph, receipt_dir=comfy_dir, identity=identity, client_prefix=CLIENT_PREFIX,
                     container_instance=container_instance(comfy.probe, settings.container))
        commands.cmd_wait(client, settings, receipt_dir=comfy_dir, timeout_seconds=settings.history_timeout_seconds)
        job = read_json(comfy_dir / commands.JOB_FILE)
        saved = [o for o in job["outputs"] if o.get("node_id") == SAVE_NODE and o.get("exists")]
        if len(saved) != 1:
            raise Refused(f"{shot}: upscale job produced {len(saved)} SaveVideo outputs (need exactly one); not adopted")
        output = link_new_file(Path(saved[0]["path"]), out_dir / f"{shot}-{height}p.mp4", saved[0]["sha256"], "upscale output")
        probed = probe_media(output)
        checks = {"size": (probed["width"], probed["height"]) == (width, height),
                  "frames": probed["frames"] == measured["frames"], "fps": probed["fps"] == measured["fps"],
                  "audio_streams": probed["audio_streams"] == measured["audio_streams"]}
        failed = sorted(name for name, ok in checks.items() if not ok)
        if failed:
            raise Refused(f"UPSCALE_OUTPUT_INVALID: {shot}: output {output.name} breaks {failed} (source {measured}, "
                          f"output {probed}); no receipt, state not advanced")
        return {"backend": NAME, "backend_contract": CONTRACT, "status": "verified",
                "source": {**source, **measured}, "output": {"path": str(output), "sha256": sha256_file(output), **probed},
                "geometry": {"crop_mode": self.entry["route"]["crop_mode"], "comfy_crop": crop, "target": target,
                             "scale": "x4 then lanczos ImageScale"},
                "qualification": {"path": self.entry["path"], "sha256": sha256_file(Path(self.entry["path"]))},
                "workflow_api": {"path": str(graph_file), "sha256": sha256_file(graph_file)},
                "execution": {"prompt_id": job["prompt_id"], "graph_sha256": job["graph_sha256"],
                              "vram_peak": None, "not_measured_reason": "no telemetry in this adapter"},
                "checks": checks, **provenance}


__all__ = ["NAME", "CONTRACT", "ComfyRealEsrgan1080", "build_graph", "probe_media"]
