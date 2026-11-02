"""Một shot = một pipeline đủ 10 bước cho panel ComfyUI (``shots[].pipeline`` trong ``jjv/video-ui-state/v1``) — chỉ đọc.

Mỗi bước: ``in`` -> ``out`` (file + sha256 + url xem được), ``status`` (``missing`` | ``generated`` | ``pending-review`` |
``approved`` | ``refused`` + ``reason``), ``approval`` (lệnh duyệt THẬT) và ``next`` (lệnh chạy bước sau THẬT).  Số liệu và lệnh
đều do engine dựng từ receipt/routes hiện tại; JS chỉ hiển thị.  Bước thiếu ⇒ ``missing`` + lệnh kế tiếp chính xác.

Nguồn bước 03/06/07/08/09 là receipt do caller khai trong target config (``ui_refresh``: ``pipeline.evidence``), mỗi dòng
``{"stage", "shot", "kind", "path"}``.  ``kind``: ``dialogue-doc`` (03), ``chunk-receipts`` (06), ``composite-receipt`` (07),
``captions-receipt`` / ``word-timing`` (08), ``mix-receipt`` (09), ``candidates-dir`` (02).  Code không nêu tên domain.
Không có nút/ lệnh nào gửi GPU: lệnh GPU chỉ là chữ để chép, kèm ``gpu: true``.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ..core.errors import EngineError
from ..core.io import read_json, sha256_file
from ..layout.context import REPO_ROOT, Context

SCHEMA = "jjv/video-ui-pipeline/v1"
STAGES = (("01", "shotlist", "Shotlist / thoại"), ("02", "anchor", "Ảnh neo + trang phục"), ("03", "voice", "Giọng WAV"),
          ("04", "prompt", "Prompt"), ("05", "h3", "H3 native"), ("06", "upscale", "SeedVR2 1440"),
          ("07", "logo", "Logo composite"), ("08", "captions", "Phụ đề / karaoke"), ("09", "audio", "Âm thanh"),
          ("10", "review", "Duyệt cuối"))
PERSON, NOTE = "<tên-người-duyệt>", "<ghi-chú-đã-xem/nghe>"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_CANDIDATES = 8
VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov")


def cmd(*parts: Any, gpu: bool = False) -> dict[str, Any]:
    """Lệnh jjv chép được: ``text`` + ``placeholders`` (chỉ ô người phải tự điền: tên, ghi chú, token GPU)."""
    tokens = [str(p) for p in parts if p is not None]
    text = "python -I .agents/skills/studio-video-engine/bin/jjv.py " + " ".join(
        t if (t.startswith("<") and t.endswith(">")) else shlex.quote(t) if any(c in t for c in ' "\'') else t for t in tokens)
    return {"text": text, "gpu": gpu, "placeholders": [t for t in tokens if t.startswith("<") and t.endswith(">")]}


def _abs(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _approved(status: Any) -> bool:
    return isinstance(status, str) and status.upper().startswith("APPROVED")


def _read(path: Path) -> Any:
    try:
        return read_json(path)
    except (EngineError, OSError, ValueError):
        return None


def _file(path: str | Path | None, url: str | None = None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    exists = p.is_file()
    return {"path": str(p), "name": p.name, "exists": exists, "sha256": sha256_file(p) if exists else None, "url": url}


def _stage(code: str, key: str, label: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, "key": key, "label": label, "status": status, "reason": None, "in": [], "out": [], "detail": {},
            "approval": None, "next": None, **fields}


def _evidence(cfg: dict[str, Any], stage: str, shot: str, kind: str) -> list[Path]:
    rows = (cfg.get("evidence") or [])
    return [_abs(r["path"]) for r in rows if isinstance(r, dict) and r.get("stage") == stage and r.get("shot") in (shot, "*")
            and r.get("kind") == kind and isinstance(r.get("path"), str)]


def _base(ep: str, cfg: dict[str, Any]) -> list[str]:
    return ["--episode", cfg.get("episode_arg") or ep]


def build_pipeline(*, episode: str, shot: str, script_row: dict[str, Any] | None, script_ref: dict[str, Any] | None,
                   ui_shot: dict[str, Any], upscale_policy: dict[str, Any] | None, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """10 bước của MỘT shot; ``ui_shot`` là hàng ``ui_state._shot`` (đã gồm anchor_pack/evidence/status)."""
    names = {k: (c, label) for c, k, label in STAGES}
    out_dir, voice_out, images_out = cfg.get("video_out"), cfg.get("voice_out"), cfg.get("images_out")
    video_base = ["--episode", cfg.get("episode_arg") or episode, "--out", out_dir or "<video-out>"]
    stages: list[dict[str, Any]] = []

    def mk(key: str, status: str, **fields: Any) -> dict[str, Any]:
        code, label = names[key]
        item = _stage(code, key, label, status, **fields)
        stages.append(item)
        return item

    # 01 shotlist ---------------------------------------------------------------------------------------
    if script_row:
        mk("shotlist", "approved" if _approved((script_ref or {}).get("status")) else "generated",
           reason=None if _approved((script_ref or {}).get("status")) else f"script status {(script_ref or {}).get('status')!r}",
           **{"in": [], "out": [{"kind": "text", "text": script_row.get("speech_text"), "speaker": script_row.get("speaker"),
                                 "seconds": script_row.get("duration_s"), "file": script_ref}]})
    else:
        mk("shotlist", "missing", reason="shot không có dòng thoại trong script", next=None)

    # 02 anchor + wardrobe ------------------------------------------------------------------------------
    pack = ui_shot.get("anchor_pack")
    cands = [c for p in _evidence(cfg, "anchor", shot, "candidates-dir") if p.is_dir()
             for c in sorted(x for x in p.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXT)][:MAX_CANDIDATES]
    required = [str(x) for x in (cfg.get("required_ref_prefixes") or [])]
    if pack:
        refs = [r for group in ("face", "body", "wardrobe", "location") for r in (pack.get(group) or []) if isinstance(r, dict)]
        have = sorted({r.get("sha256", "") for r in refs} | {r.get("sha256", "") for r in (ui_shot.get("wardrobe") or {}).get("refs") or []})
        checks = [{"prefix": p, "present": any(h.startswith(p) for h in have)} for p in required]
        approved = pack.get("status") == "approved"
        mk("anchor", "approved" if approved else "pending-review",
           reason=None if approved else f"anchor pack status {pack.get('status')!r}; ready_for_graph={pack.get('ready_for_graph')}",
           out=[{"kind": "image", "name": r.get("name"), "sha256": r.get("sha256"), "url": r.get("url"),
                 "approval": r.get("approval")} for r in refs] + [
               {"kind": "image", "name": f"ứng viên: {c.name}", "sha256": sha256_file(c), "url": None, "approval": "candidate"} for c in cands],
           detail={"wardrobe_checks": checks, "pack": {"file": pack.get("file"), "sha256": pack.get("sha256")},
                   "candidates": [_file(c) for c in cands]},
           approval=None if approved else cmd("images", "approve", *_base(episode, cfg), "--out", images_out or "<images-dir>",
                                                               "--shot", shot, "--sha", "<sha-ảnh-đã-xem>",
                                                               "--reviewer", PERSON, "--scope", "<phạm-vi>"),
           next=cmd("video", "anchor-stage", *video_base, "--shot", shot))
    else:
        mk("anchor", "pending-review" if cands else "missing",
           reason="chỉ có ảnh ứng viên, chưa có anchor pack" if cands else "ANCHOR_PACK_MISSING",
           out=[{"kind": "image", "name": c.name, "sha256": sha256_file(c), "url": None} for c in cands],
           detail={"wardrobe_checks": [{"prefix": p, "present": False} for p in required],
                   "candidates": [_file(c) for c in cands]},
           approval=cmd("images", "approve", *_base(episode, cfg), "--out", images_out or "<images-dir>", "--shot", shot,
                                                    "--sha", "<sha-ảnh-đã-xem>", "--reviewer", PERSON, "--scope", "<phạm-vi>"),
           next=cmd("video", "anchor-pack", *video_base, "--shot", shot, "--selection", "<selection.json>",
                    "--shotlist", cfg.get("shotlist") or "<shotlist>", "--library", "<library>"))

    # 03 voice -----------------------------------------------------------------------------------------
    voice = None
    for path in _evidence(cfg, "voice", shot, "dialogue-doc"):
        doc = _read(path) or {}
        voice = next((d for d in doc.get("dialogue") or [] if str(d.get("id", "")).startswith(shot)), voice)
    takes = [p for p in _evidence(cfg, "voice", shot, "wav-file") if p.is_file()]
    if voice is None and takes:  # WAV rời (take đang chờ nghe): thoại lấy từ script
        voice = {"id": shot, "speaker": (script_row or {}).get("speaker"), "speech_text": (script_row or {}).get("speech_text"),
                 "audio": {"path": str(takes[-1]), "sha256": sha256_file(takes[-1]), "duration_seconds": None}}
    if voice:
        audio = voice.get("audio") or {}
        wav = _file(audio.get("path"))
        mk("voice", "pending-review", reason="WAV có, chưa có bản ghi duyệt nghe", **{"in": [{"kind": "text", "text": voice.get("speech_text")}]},
           out=[{"kind": "audio", "path": audio.get("path"), "sha256": audio.get("sha256"), "exists": bool((wav or {}).get("exists")),
                 "seconds": audio.get("duration_seconds")}],
           detail={"speaker": voice.get("speaker"), "frames": [voice.get("start_frame"), voice.get("end_frame_exclusive")],
                   "sha_matches_disk": bool(wav and wav["sha256"] == audio.get("sha256"))},
           approval=cmd("voice", "approve", *_base(episode, cfg), "--out", voice_out or "<voice-dir>", "--job",
                                                   f"dialogue:{voice.get('id')}", "--sha256", audio.get("sha256"),
                                                   "--by", PERSON, "--note", NOTE),
           next=cmd("h3", "inputs", *_base(episode, cfg), "--spec", "<h3-spec.json>", "--images", "<images-dir>",
                    "--voice", voice_out or "<voice-dir>", "--out", f"{out_dir or '<video-out>'}/h3-inputs.json"))
    else:
        mk("voice", "missing", reason="chưa có WAV thoại cho shot", next=cmd("voice", "plan", *_base(episode, cfg), "--out", voice_out or "<voice-out>", "--script", cfg.get("shotlist") or "<script>"))

    # 04 prompt ----------------------------------------------------------------------------------------
    prompt = ui_shot.get("prompt")
    mk("prompt", "generated" if prompt else "missing", reason=None if prompt else "prompt chưa đóng băng",
       out=[{"kind": "text", "text": prompt, "chars": len(prompt)}] if prompt else [],
       next=None if prompt else cmd("video", "prompt", *video_base))

    # 05 H3 native ---------------------------------------------------------------------------------------
    status = ui_shot.get("status")
    ev = (ui_shot.get("evidence") or {}).get("native") or {}
    native_url = ui_shot.get("native_url")
    if native_url or ev.get("exists"):
        accepted = status == "accepted"
        mk("h3", "approved" if accepted else "pending-review", reason=None if accepted else f"trạng thái {status}: chưa có quyết định pick",
           out=[{"kind": "video", "name": ev.get("name"), "sha256": ev.get("sha256"), "url": native_url, "path": ev.get("path")}],
           detail={"geometry": ui_shot.get("geometry"), "frames": ev.get("frames"), "fps": ev.get("fps")},
           approval=None if accepted else cmd("video", "accept", *video_base, "--shot", shot, "--pick",
                                                              "--sha256", ev.get("sha256") or "<sha-take-đã-xem>", "--by", PERSON, "--reason", NOTE),
           next=cmd("video", "upscale", *video_base, "--shot", shot, "--source", ev.get("path") or "<native.mp4>",
                    "--target", (upscale_policy or {}).get("target") or "<WxH>", "--backend", "<backend>",
                    "--gpu-approved", "<token:lời-user>", gpu=True))
    else:
        mk("h3", "missing", reason="chưa render H3 cho shot",
           next=cmd("video", "render", *video_base, "--shot", shot, "--revision", "<rev>", "--route", "<route>",
                    "--gpu-approved", "<token:lời-user>", gpu=True))

    # 06 SeedVR2 (cổng chất lượng) ------------------------------------------------------------------------
    qualified = (upscale_policy or {}).get("qualified") or {}
    chunks: list[dict[str, Any]] = []
    for path in _evidence(cfg, "upscale", shot, "chunk-receipts"):
        doc = _read(path)
        rows = doc.get("chunks") if isinstance(doc, dict) else doc  # receipt theo shot = dict {chunks:[…]}; bản cũ = list trần
        chunks += [c for c in (rows if isinstance(rows, list) else []) if isinstance(c, dict)]
    gate = None if qualified else ("NOT QUALIFIED: routes upscale.qualified trống - cần receipt pilot do user cho phép "
                                   "(path + sha256) trước khi bước 04 chạy; `jjv video upscale` dừng ở cổng này")
    mk("upscale", "refused" if gate else ("approved" if ui_shot.get("hd_url") else "missing"), reason=gate,
       out=([{"kind": "video", "url": ui_shot["hd_url"]}] if ui_shot.get("hd_url") else []),
       detail={"target": (upscale_policy or {}).get("target"), "qualified_backends": sorted(qualified),
               "pilot_chunks": [{"chunk": c.get("chunk"), "sha256": c.get("out_sha256"), "frames": c.get("out_frames")} for c in chunks],
               "unblocks": "user cho phép pilot + qualification receipt (chưa có verb ghi: ghi tay vào routes sau khi user duyệt)"})

    # 07 logo ---------------------------------------------------------------------------------------------
    logo = None
    for path in _evidence(cfg, "logo", shot, "composite-receipt"):
        doc = _read(path)
        if isinstance(doc, dict) and doc.get("outputs"):
            logo = (path, doc)
    if logo:
        path, doc = logo
        master = (doc.get("outputs") or {}).get("master") or {}
        file = _file(path.parent / str(master.get("path") or ""))
        mk("logo", "pending-review", reason=f"receipt status {doc.get('status')!r}; chưa có bản ghi duyệt của user",
           **{"in": [{"kind": "video", "sha256": (doc.get("input") or {}).get("sha256")}]},
           out=[{"kind": "video", "path": (file or {}).get("path"), "sha256": master.get("sha256"), "exists": bool((file or {}).get("exists"))}],
           detail={"receipt": {"path": str(path), "sha256": sha256_file(path)}, "status": doc.get("status"),
                   "track_gate": doc.get("track_gate"), "edge_check": doc.get("edge_check"), "tool": doc.get("tool")},
           approval=None, next=None)
        stages[-1]["detail"]["approval_note"] = "engine chưa có verb duyệt logo (chỉ đọc receipt); user duyệt bằng mắt rồi báo root"
    else:
        mk("logo", "missing", reason="chưa có receipt composite logo")

    # 08 phụ đề / karaoke ---------------------------------------------------------------------------------
    caps = next(((p, _read(p)) for p in _evidence(cfg, "captions", shot, "captions-receipt") if isinstance(_read(p), dict)), None)
    timing = next((p for p in _evidence(cfg, "captions", shot, "word-timing") if p.is_file()), None)
    text = (script_row or {}).get("speech_text")
    if caps:
        path, doc = caps
        mk("captions", "pending-review", reason="phụ đề đã dựng, chưa duyệt", **{"in": [{"kind": "text", "text": text}]},
           out=[f for f in (_file(doc.get("ass", {}).get("path") if isinstance(doc.get("ass"), dict) else None),
                            _file(doc.get("srt", {}).get("path") if isinstance(doc.get("srt"), dict) else None)) if f],
           detail={"speech_text": text, "receipt": {"path": str(path), "sha256": sha256_file(path)}, "schema": doc.get("schema")},
           next=cmd("captions", "burn", *_base(episode, cfg), "--timing", str(timing or "<WORD-TIMING.json>"), "--subtitles", "<srt>",
                    "--font", "<font>", "--video", "<video>", "--ass", "<ass>", "--wav", "<wav>", "--out", "<out>"))
    else:
        mk("captions", "missing", reason="chưa dựng phụ đề (cần WORD-TIMING.json)" if not timing else "có word timing, chưa dựng .ass",
           **{"in": [{"kind": "text", "text": text}]},
           detail={"speech_text": text, "word_timing": _file(timing)},
           next=cmd("captions", "build", *_base(episode, cfg), "--timing", str(timing or "<WORD-TIMING.json>"),
                    "--out", f"<captions-dir>/{shot}"))

    # 09 âm thanh -----------------------------------------------------------------------------------------
    mix = next(((p, _read(p)) for p in _evidence(cfg, "audio", shot, "mix-receipt") if isinstance(_read(p), dict)), None)
    if mix:
        path, doc = mix
        mk("audio", "pending-review", reason=(doc.get("label") or "mix preview, chưa duyệt"),
           detail={"sfx_enabled": doc.get("sfx_enabled"), "cues": len(doc.get("cues") or []),
                   "lufs": (doc.get("ebur128_mp4_audio") or {}).get("I_lufs"), "receipt": {"path": str(path), "sha256": sha256_file(path)}})
    else:
        mk("audio", "missing", reason="chưa có receipt mix", detail={"sfx_enabled": None},
           next=cmd("audio", "mix", *_base(episode, cfg), "--out", "<audio-out>", "--review-config", "<review-config.json>"))

    # 10 duyệt cuối ---------------------------------------------------------------------------------------
    done = status == "accepted"
    mk("review", "approved" if done else ("pending-review" if status in ("rendered", "upscaled_1080") else "missing"),
       reason=None if done else "chưa có quyết định pick/final trong state jjv video",
       approval=None if done else cmd("video", "accept", *video_base, "--final", "--by", PERSON, "--note", NOTE))
    return stages


def route_row(ctx: Context) -> dict[str, Any] | None:
    from . import routes as routes_mod  # trễ: routes nhập comfy.staging, tránh vòng nhập khi ui_state chạy riêng

    try:
        return routes_mod.domain_route(ctx, routes_mod.load_routes())
    except EngineError:
        return None  # domain không thuộc `jjv video` ⇒ không có cỡ/chính sách upscale để hiện


def upscale_policy(ctx: Context) -> dict[str, Any] | None:
    row = route_row(ctx)
    return row["upscale"] if row else None


def planned_sizes(ctx: Context) -> tuple[dict[str, int] | None, dict[str, int] | None]:
    """``(native, export)`` KẾ HOẠCH từ routes (geometry H3 + upscale.target); thiếu ⇒ ``None`` để dùng số đo/receipt."""
    from . import routes as routes_mod

    row = route_row(ctx)
    if not row:
        return None, None
    geometry = routes_mod.geometry_for(row)
    target = str((row.get("upscale") or {}).get("target") or "")
    wh = target.split("x")
    export = {"w": int(wh[0]), "h": int(wh[1])} if len(wh) == 2 and all(v.isdigit() for v in wh) else None
    return ({"w": geometry["width"], "h": geometry["height"]} if geometry else None), export


def with_pipeline(ctx: Context, shots: list[dict[str, Any]], doc: dict[str, Any], shotlist: Path,
                   cfg: dict[str, Any]) -> list[dict[str, Any]]:
    rows = {r.get("id"): r for r in doc.get("shots") or [] if isinstance(r, dict)}
    ref = {"path": str(shotlist), "sha256": sha256_file(shotlist), "status": doc.get("status")}
    policy = upscale_policy(ctx)
    return [{**s, "pipeline": {"schema": SCHEMA, "stages": build_pipeline(
        episode=ctx.episode_id, shot=s["id"], script_row=rows.get(s["id"]), script_ref=ref, ui_shot=s, upscale_policy=policy,
        cfg={**cfg, "shotlist": str(shotlist)})}} for s in shots]


__all__ = ["SCHEMA", "STAGES", "build_pipeline", "cmd", "with_pipeline", "planned_sizes", "upscale_policy", "route_row"]
