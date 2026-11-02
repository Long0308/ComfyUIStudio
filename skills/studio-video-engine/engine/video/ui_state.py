"""Trạng thái VIDEO theo shot cho panel ComfyUI (``jjv/video-ui-state/v1``) — chỉ đọc, không gửi gì, không GPU.

Nguồn (đường dẫn do caller truyền; code không nêu tên domain, cổng hay ổ đĩa): (1) state ``jjv video`` (``<video_out>/<shot>/
state.json``, chuỗi receipt băm) thắng mọi nguồn; (2) thư mục receipt H3 theo layout đã dùng thật: engine (``preparation.json``
+ ``comfy/job.json`` + ``adopt.json`` + ``acceptance/``), legacy (``<version>/<shot>/{preparation,job,history}.json``), pilot
(``pilot-preparation.json`` hoặc ``workflow.api.json`` + ``dispatch/submitted.json``); (3) shots doc ``jjv/shots/v1`` (clip đã
vào dựng, sha256 kiểm trên đĩa) ⇒ ``accepted``; (4) ``--anchor-dir``: bộ neo ảnh cảnh ``jjv/shot-anchor-pack/v1`` (``anchor_pack_ui``,
sha băm lại).  Status không suy đoán: không receipt ⇒ ``planned``; hỏng ⇒ ``null`` + ``problems``; ``upscaled_1080`` chỉ từ state
``jjv video``.  ``refs`` (ảnh tham chiếu hiện cho shot) CHỈ từ pack đã kiểm (``anchor_pack_ui``); ảnh LoadImage của graph pilot cũ và
ảnh nhân vật stage ``h3-<sha>`` nằm riêng ở ``legacy_refs`` với ``blocked`` (luật user 31/10: không hiện người khác); tên nhân vật
của shotlist ở ``cast``.  URL ``/view?...`` chỉ cho file CÓ THẬT trong ComfyUI input/output.  CLI: ``python -m engine.video.ui_state --help``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from ..comfy.settings import ComfySettings, settings_from_machine
from ..core.errors import EngineError, Refused
from ..core.io import read_json, sha256_file, write_json_atomic
from ..core.paths import resolve_data_path
from ..layout.context import Context
from . import anchor_pack_ui, state as state_mod
from . import ui_pipeline, ui_wardrobe
from .ui_wardrobe import view_url

SCHEMA = "jjv/video-ui-state/v1"
INDEX_SCHEMA = "jjv/video-ui-index/v1"
SHOTLIST_SCHEMAS = ("jjv/script/v1", "jjv/shotlist-draft/v1")
PREPARATION_FILES = ("preparation.json", "pilot-preparation.json")
GRAPH_FILES = ("graph.api.json", "workflow.api.json")
RECEIPT_SUBDIRS = ("comfy", "dispatch", "")
VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
RANK = {name: index for index, name in enumerate(state_mod.STATES)}
LEGACY_BLOCK = "NOT_APPROVED_LEGACY_PILOT_INPUT"  # ảnh graph pilot / ảnh stage h3-<sha>: không phải tham chiếu đã duyệt


# ---- helpers --------------------------------------------------------------------------------------------
def _read(path: Path) -> dict[str, Any] | None:
    try:
        document = read_json(path)
    except EngineError:
        return None
    return document if isinstance(document, dict) else None


# ---- shotlist (01 ĐỌC SHOTLIST) ------------------------------------------------------------------------
def _blank(shot_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": shot_id, "kind": None, "scene": None, "speaker": None, "size": None, "angle": None, "move": None,
            "seconds": None, "camera_id": None, "context": None, ui_wardrobe.PER_CHARACTER_KEY: None, "refs": [], **fields}


def _script_ref(table: dict[str, Any], role: str | None, settings: ComfySettings) -> list[dict[str, Any]]:
    entry = table.get(role) if role else None
    if not isinstance(entry, dict):
        return [{"name": role, "url": None}] if role else []
    staged = settings.input_dir / f"h3-{entry.get('canonical_sha256')}{Path(str(entry.get('canonical_path') or '')).suffix.lower()}"
    return [{"name": entry.get("bible_name") or role, "url": view_url(staged, settings.input_dir, "input")}]


def _script_rows(doc: dict[str, Any], settings: ComfySettings, fps: Any) -> list[dict[str, Any]]:
    """``shots[]`` của script (``id``, ``duration_s``) hoặc của shots doc ``jjv/shots/v1`` (``shot``, ``clip.frames``)."""
    table = doc.get("character_references") or {}
    structure = doc.get("structure") or {}
    rows = []
    intro = structure.get("intro") if isinstance(structure.get("intro"), dict) else None
    if intro and intro.get("source_scene_id"):
        rows.append(_blank(intro["source_scene_id"], kind="intro", scene=intro["source_scene_id"], seconds=intro.get("duration_s")))
    for shot in doc.get("shots") or []:
        source, continuity, clip = shot.get("source") or {}, shot.get("continuity") or {}, shot.get("clip") or {}
        seconds = shot.get("duration_s")
        if seconds is None and isinstance(clip.get("frames"), int) and isinstance(fps, (int, float)) and fps:
            seconds = round(clip["frames"] / fps, 3)  # frame native đã nhận vào dựng / fps native của domain
        refs = _script_ref(table, shot.get("speaker"), settings) + _script_ref(table, shot.get("listener"), settings)
        rows.append(_blank(shot.get("id") or shot["shot"], kind="dialogue", scene=source.get("scene_id"), speaker=shot.get("speaker"),
                           seconds=seconds, camera_id=continuity.get("camera_id"), context=ui_wardrobe.context_of(shot), refs=refs,
                           **{ui_wardrobe.PER_CHARACTER_KEY: shot.get(ui_wardrobe.PER_CHARACTER_KEY)}))
    outro = structure.get("outro") if isinstance(structure.get("outro"), dict) else None
    if outro and outro.get("source_scene_id"):
        rows.append(_blank(outro["source_scene_id"], kind="outro", scene=outro["source_scene_id"], seconds=outro.get("duration_s")))
    return rows


def _draft_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [_blank(row["id"], **{k: row.get(k) for k in ("kind", "scene", "speaker", "size", "angle", "move", "seconds",
                                                           "camera_id", ui_wardrobe.PER_CHARACTER_KEY)}, context=ui_wardrobe.context_of(row),
                   refs=[{"name": r if isinstance(r, str) else (r or {}).get("name"), "url": None} for r in row.get("refs") or []])
            for row in doc.get("rows") or []]


def load_shotlist(ctx: Context, path: Path, settings: ComfySettings) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Shot plan của ĐÚNG episode (và domain nếu doc khai); ``jjv/script/v1`` thêm intro/outro từ ``structure``."""
    doc = read_json(path)
    if not isinstance(doc, dict):
        raise Refused(f"{path}: shotlist is not a JSON object")
    ident = doc.get("film_id") or doc.get("episode") or doc.get("episode_id")
    if ident != ctx.episode_id:
        raise Refused(f"{path}: shotlist belongs to episode {ident!r}, not {ctx.episode_id!r}; episodes are never mixed")
    if doc.get("domain") not in (None, ctx.domain_id):
        raise Refused(f"{path}: shotlist domain {doc.get('domain')!r} is not {ctx.domain_id!r}; domains are never mixed")
    rows = _draft_rows(doc) if isinstance(doc.get("rows"), list) else _script_rows(doc, settings, (ctx.domain.get("frame_rates") or {}).get("native_fps"))
    ids = [r["id"] for r in rows]
    if not ids or len(set(ids)) != len(ids):
        raise Refused(f"{path}: shotlist needs non-empty, unique shot ids (rows[] or shots[]); got {ids}")
    return doc, rows


# ---- receipts (03/04/05) ------------------------------------------------------------------------------
def _graph_facts(graph: dict[str, Any], settings: ComfySettings) -> dict[str, Any]:
    """Prompt đóng băng, kích thước native và ảnh LoadImage (URL khi file có trong ComfyUI input) của graph API."""
    prompt, geometry, refs = None, None, []
    for node_id, node in graph.items():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        value = inputs.get("prompt")
        if prompt is None and isinstance(value, str) and value.strip():
            prompt = value
        elif prompt is None and isinstance(value, list) and len(value) == 2 and str(value[0]) in graph:
            source = (graph[str(value[0])].get("inputs") or {})
            prompt = next((source[k] for k in ("value", "text", "string") if isinstance(source.get(k), str) and source[k].strip()), None)
        if geometry is None and isinstance(inputs.get("width"), int) and isinstance(inputs.get("height"), int):
            geometry = {"w": inputs["width"], "h": inputs["height"]}
        if node.get("class_type") == "LoadImage" and isinstance(inputs.get("image"), str):
            title = (node.get("_meta") or {}).get("title") or f"LoadImage {node_id}"
            refs.append({"name": title, "url": view_url(settings.input_dir / inputs["image"], settings.input_dir, "input")})
    return {"prompt": prompt, "geometry": geometry, "refs": refs}


def _node_rows(outputs: Any) -> list[dict[str, Any]]:
    """Bản ghi output kiểu ``/history`` (theo node: images/gifs/videos/audio) → hàng filename/subfolder/type."""
    return [{**e, "node_id": str(node_id)} for node_id, out in (outputs.items() if isinstance(outputs, dict) else [])
            for kind in ("images", "gifs", "videos", "audio") for e in ((out or {}).get(kind) or [])
            if isinstance(e, dict) and e.get("filename")]


def _job(folder: Path) -> dict[str, Any] | None:
    """job.json (engine ``comfy/``, guarded ``dispatch/``, legacy root) + history.json, hoặc submitted.json ⇒ SUBMITTED."""
    for sub in RECEIPT_SUBDIRS:
        base = folder / sub if sub else folder
        job = _read(base / "job.json")
        if job is not None:
            rows = [r for r in (job.get("outputs") if isinstance(job.get("outputs"), list) else []) if isinstance(r, dict) and r.get("filename")]
            history = _read(base / "history.json") or {}  # bản ghi /history thật của prompt (legacy v002–v006)
            rows += _node_rows((job.get("response") or {}).get("outputs")) + _node_rows((history.get(str(job.get("prompt_id"))) or history).get("outputs"))
            return {"file": str(base / "job.json"), "status": job.get("status"), "prompt_id": job.get("prompt_id"), "outputs": rows}
        submitted = _read(base / "submitted.json")
        if submitted is not None:
            return {"file": str(base / "submitted.json"), "status": "SUBMITTED", "prompt_id": submitted.get("prompt_id"), "outputs": []}
    return None


def _output(rows: list[dict[str, Any]], settings: ComfySettings, *, prefer: str | None, exts: tuple[str, ...]) -> dict | None:
    """Output ``type=output`` của node ``prefer`` (hoặc file đầu tiên có đuôi ``exts``), kèm path thật + tồn tại."""
    wanted = [r for r in rows if r.get("type", "output") == "output" and Path(r["filename"]).suffix.lower() in exts]
    wanted.sort(key=lambda r: 0 if prefer and str(r.get("node_id")) == str(prefer) else 1)
    first = None
    for row in wanted:
        path = Path(row["path"]) if isinstance(row.get("path"), str) else settings.output_dir / (row.get("subfolder") or "") / row["filename"]
        exists = path.is_file()
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        found = {"name": row["filename"], "node_id": str(row.get("node_id")), "path": str(path), "exists": exists,
                 "url": view_url(path, settings.output_dir, "output"), "sha256": sha256_file(path) if exists else row.get("sha256"),
                 "w": meta.get("width"), "h": meta.get("height"), "frames": meta.get("frame_count"), "fps": meta.get("fps")}
        if exists:
            return found
        first = first or found
    return first


def _acceptance(folder: Path, sha: str | None) -> str | None:
    """Quyết định mới nhất của ``acceptance/NNN-*.json`` cho đúng sha take (pick|reject), nếu có."""
    records = sorted((folder / "acceptance").glob("*.json")) if sha and (folder / "acceptance").is_dir() else []
    hits = [f"{body['decision']} {record.name}" for record in records for body in [_read(record) or {}]
            if (body.get("subject") or {}).get("sha256") == sha and body.get("decision") in ("pick", "reject")]
    return hits[-1] if hits else None


def inspect_receipts(folder: Path, ctx: Context, settings: ComfySettings) -> dict[str, Any]:
    """Bằng chứng thật trong MỘT thư mục receipt của shot; receipt của episode khác bị bỏ qua (ghi problem)."""
    ev: dict[str, Any] = {"receipt_dir": str(folder), "preparation": None, "job": None, "native": None, "thumb": None,
                          "prompt": None, "geometry": None, "refs": [], "acceptance": None, "problems": []}
    prep_file = next((folder / n for n in PREPARATION_FILES if (folder / n).is_file()), None)
    prep = _read(prep_file) if prep_file else None
    graph_path = next((folder / n for n in GRAPH_FILES if (folder / n).is_file()), None)
    sinks: dict[str, Any] = {}
    if prep is not None:
        episode = prep.get("episode_id") or prep.get("film_id")
        if episode != ctx.episode_id:
            ev["problems"].append(f"{prep_file}: episode {episode!r} is not {ctx.episode_id!r}; receipt ignored")
            return ev
        ev["preparation"] = {"file": prep_file.name, "schema": prep.get("schema"), "status": prep.get("status"),
                             "version": prep.get("version")}
        sinks = dict(prep.get("sinks") or {})
        if prep.get("editorial_node"):
            sinks["editorial"] = prep["editorial_node"]
        api = (prep.get("api") or {}).get("path")
        if graph_path is None and isinstance(api, str):
            given = Path(api)
            graph_path = resolve_data_path(given if given.is_absolute() else folder / given, ctx.machine)
    graph = _read(graph_path) if graph_path else None
    if graph is not None:
        ev.update(_graph_facts(graph, settings))
    elif graph_path is not None:
        ev["problems"].append(f"prepared graph missing or unreadable: {graph_path}")
    job = _job(folder)
    if job is not None:
        ev["job"] = {"status": job["status"], "prompt_id": job["prompt_id"]}
        ev["native"] = _output(job["outputs"], settings, prefer=sinks.get("editorial"), exts=VIDEO_EXT)
        ev["thumb"] = _output(job["outputs"], settings, prefer=sinks.get("carry"), exts=IMAGE_EXT)
        if job["status"] == "COMPLETED" and not (ev["native"] or {}).get("exists"):
            ev["problems"].append(f"{job['file']}: job COMPLETED but its video output is missing on disk")
    ev["acceptance"] = _acceptance(folder, (ev["native"] or {}).get("sha256"))  # sha take = sha file thật đã băm
    return ev


def _status_of(ev: dict[str, Any], clip: dict[str, Any] | None, root: Path) -> tuple[str | None, str | None, list[str]]:
    problems: list[str] = []
    if ev["acceptance"] and ev["acceptance"].startswith("pick"):
        return "accepted", f"h3 acceptance {ev['acceptance']}", problems
    if isinstance(clip, dict) and isinstance(clip.get("path"), str):
        path = resolve_data_path(root / clip["path"], None)
        if path.is_file() and sha256_file(path) == clip.get("sha256"):
            return "accepted", "shots doc clip sha256 verified on disk", problems
        problems.append(f"shots doc clip {clip['path']} is missing or its sha256 differs; not counted as accepted")
    if (ev.get("job") or {}).get("status") == "COMPLETED" and (ev.get("native") or {}).get("exists"):
        return "rendered", "job COMPLETED + native output on disk", problems
    if ev.get("prompt") is not None:
        return "prompted", f"{(ev.get('preparation') or {}).get('file') or 'graph'} prompt frozen", problems
    return None, None, problems


def _video_state(out: Path, shot: str, ctx: Context, settings: ComfySettings) -> dict[str, Any] | None:
    """State ``jjv video`` của shot (nếu có): status + receipt chain phải còn đúng byte, sai ⇒ status null."""
    if not (state_mod.shot_dir(out, shot) / state_mod.STATE_FILE).is_file():
        return None
    result: dict[str, Any] = {"source": "jjv video state.json", "status": None, "prompt": None, "native": None, "hd": None}
    try:
        state = state_mod.read_state(out, shot)
        if (state.get("episode_id"), state.get("domain")) != (ctx.episode_id, ctx.domain_id):
            raise Refused(f"{shot}: video state belongs to another episode/domain; ignored")
        receipts = {key: state_mod.verify_ref(out, entry, key) for key, entry in state["receipts"].items()}
    except EngineError as error:
        return {**result, "problems": [str(error)]}
    result.update(status=state["state"], revision=state["revision"], problems=[])
    if "prompt" in receipts:
        text = state_mod.ref_path(out, state["receipts"]["prompt"]).parent / receipts["prompt"]["prompt"]["path"]
        if text.is_file() and sha256_file(text) == receipts["prompt"]["prompt"]["sha256"]:
            result["prompt"] = text.read_text(encoding="utf-8").strip()
    for key, field, slot in (("render", "native", "native"), ("upscale", "output", "hd")):
        media = (receipts.get(key) or {}).get(field)
        if isinstance(media, dict) and isinstance(media.get("path"), str):
            result[slot] = {"path": media["path"], "sha256": media.get("sha256"), "exists": Path(media["path"]).is_file(),
                            "url": view_url(Path(media["path"]), settings.output_dir, "output")}
    return result


# ---- build ----------------------------------------------------------------------------------------------
def _shots_doc(ctx: Context, path: Path | None) -> tuple[dict[str, Any] | None, dict[str, dict], list[str]]:
    declared = (ctx.episode.get("files") or {}).get("shots")
    file = Path(path) if path else (ctx.root / "engine" / declared if isinstance(declared, str) else None)
    if file is None or not file.is_file():
        return None, {}, []
    doc = _read(file)
    if doc is None or doc.get("episode_id") not in (None, ctx.episode_id):
        return None, {}, [f"{file}: shots doc belongs to episode {(doc or {}).get('episode_id')!r}; ignored"]
    return ({"path": str(file), "sha256": sha256_file(file), "schema": doc.get("schema")},
            {r["shot"]: r for r in doc.get("shots") or [] if isinstance(r, dict) and r.get("shot")}, [])


def _candidates(shot: str, explicit: dict[str, Path], doc_row: dict | None, h3_dirs: list[Path], root: Path) -> list[Path]:
    found = [Path(explicit[shot])] if shot in explicit else []
    if doc_row and isinstance(doc_row.get("receipt_dir"), str):
        found.append(root / doc_row["receipt_dir"])
    found += [Path(d) / shot for d in h3_dirs]
    return list(dict.fromkeys(p for p in found if p.is_dir()))


def _shot(row: dict[str, Any], ctx: Context, settings: ComfySettings, *, video_out: Path | None, explicit: dict[str, Path],
          doc_row: dict | None, h3_dirs: list[Path], anchors: dict[str, Any] | None) -> dict[str, Any]:
    shot, problems, clip = row["id"], [], (doc_row or {}).get("clip")
    best: tuple[int, str | None, str | None, dict | None] = (-1, "planned", "shotlist only (no receipt)", None)
    for folder in _candidates(shot, explicit, doc_row, h3_dirs, ctx.root):
        ev = inspect_receipts(folder, ctx, settings)
        status, source, extra = _status_of(ev, clip, ctx.root)
        problems += ev["problems"] + extra
        if status is not None and RANK[status] > best[0]:
            best = (RANK[status], status, source, ev)
    if best[3] is None and clip:  # clip đã vào dựng nhưng không còn thư mục receipt
        status, source, extra = _status_of({"acceptance": None}, clip, ctx.root)
        problems += extra
        best = (RANK[status], status, source, None) if status else best
    _, status, source, ev = best
    ev = ev or {}
    native, thumb, prompt, hd = ev.get("native"), ev.get("thumb"), ev.get("prompt"), None
    video = _video_state(video_out, shot, ctx, settings) if video_out else None
    if video is not None:  # state của jjv video thắng: receipt chain băm; hỏng ⇒ null, không bịa
        status, source, problems = video["status"], video["source"], problems + video["problems"]
        prompt, native, hd = video["prompt"] or prompt, video["native"] or native, video["hd"]
        ev = {**ev, "video_state": {k: video.get(k) for k in ("status", "revision")}}
    geometry = ev.get("geometry") or ({"w": native["w"], "h": native["h"]} if native and native.get("w") and native.get("h") else None)
    evidence = {k: ev[k] for k in ("receipt_dir", "preparation", "job", "native", "acceptance", "video_state") if ev.get(k) is not None}
    # ``refs`` do anchor_pack_ui quyết (chỉ pack đã kiểm); ảnh graph pilot + ảnh stage h3-<sha> của script chỉ là legacy, bị chặn
    legacy = [{"name": r["name"], "url": r["url"], "blocked": LEGACY_BLOCK}
              for r in (ev.get("refs") or []) + [r for r in row["refs"] if r.get("url")]]
    wardrobe = None
    if anchors is not None:  # neo trang phục theo context của shot / nhân vật; context không rõ ⇒ từ chối được ghi, không gắn gì
        bound = ui_wardrobe.attach(row, anchors, settings, ctx.machine)
        problems += bound["problems"] + ([bound["refused"]] if bound["refused"] else [])
        wardrobe = {k: bound[k] for k in ("context", "per_character", "refs", "refused")}
    return {**{k: row[k] for k in ("id", "scene", "size", "angle", "move", "seconds")}, "refs": [], "prompt": prompt,
            "status": status, "native_url": (native or {}).get("url"), "hd_url": (hd or {}).get("url"),
            "thumb_url": (thumb or {}).get("url"), "kind": row["kind"], "speaker": row["speaker"], "camera_id": row["camera_id"],
            "cast": [r["name"] for r in row["refs"]], "legacy_refs": legacy, "context": row["context"],
            ui_wardrobe.PER_CHARACTER_KEY: row[ui_wardrobe.PER_CHARACTER_KEY], "wardrobe": wardrobe, "status_source": source,
            "geometry": geometry, "evidence": evidence or None, "problems": problems}


def build(ctx: Context, *, shotlist: Path, video_out: Path | None = None, h3_dirs: list[Path] | None = None,
          receipts: dict[str, Path] | None = None, shots_doc: Path | None = None, wardrobe: Path | None = None,
          anchor_dir: Path | None = None, pipeline: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings_from_machine(ctx.machine)
    doc, rows = load_shotlist(ctx, Path(shotlist), settings)
    if video_out is not None:
        state_mod.require_plan_of(ctx, state_mod.read_plan(Path(video_out)))
    anchors = ui_wardrobe.load_anchors(Path(wardrobe), ctx.domain_id) if wardrobe else None  # đúng domain, else Refused
    doc_ref, doc_rows, doc_problems = _shots_doc(ctx, shots_doc)
    shots = [_shot(row, ctx, settings, video_out=Path(video_out) if video_out else None, explicit=dict(receipts or {}),
                   doc_row=doc_rows.get(row["id"]), h3_dirs=list(h3_dirs or []), anchors=anchors) for row in rows]
    shots = anchor_pack_ui.attach_ui(shots, Path(anchor_dir) if anchor_dir else None, ctx, settings,  # refs chỉ từ pack đã kiểm
                                     current={"shotlist": sha256_file(Path(shotlist)), "wardrobe_presets": anchors["_sha256"] if anchors else None})
    if pipeline is not None:  # opt-in: chỉ episode có target khai ``pipeline`` mới nhận ``shots[].pipeline`` (10 bước)
        shots = ui_pipeline.with_pipeline(ctx, shots, doc, Path(shotlist), pipeline)
    counts ={**{name: sum(1 for s in shots if s["status"] == name) for name in state_mod.STATES},
              "unknown": sum(1 for s in shots if s["status"] is None)}
    master = (ctx.domain.get("delivery") or {}).get("master") or {}
    native = next((s["geometry"] for s in shots if s.get("geometry")), None)
    planned_native, planned_export = ui_pipeline.planned_sizes(ctx) if pipeline is not None else (None, None)  # opt-in cùng pipeline
    native = planned_native or native
    return {"schema": SCHEMA, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "episode": ctx.episode_id,
            "domain": ctx.domain_id, "fps": (ctx.domain.get("frame_rates") or {}).get("native_fps"), "native": native,
            "export": planned_export or ({"w": master["width"], "h": master["height"]} if master.get("width") and master.get("height") else None),
            "counts": counts, "shots": shots,
            "sources": {"shotlist": {"path": str(shotlist), "sha256": sha256_file(Path(shotlist)), "schema": doc.get("schema")},
                        "shots_doc": doc_ref, "video_out": str(video_out) if video_out else None, "anchor_dir": str(anchor_dir) if anchor_dir else None,
                        "wardrobe": {"path": anchors["_path"], "sha256": anchors["_sha256"], "schema": anchors["schema"]} if anchors else None,
                        "h3_dirs": [str(d) for d in h3_dirs or []], "receipts": {k: str(v) for k, v in (receipts or {}).items()},
                        "comfy_output_dir": str(settings.output_dir)},
            "problems": doc_problems}


def write(document: dict[str, Any], out: Path) -> str:
    """Ghi atomic (temp + ``os.replace``); trả sha256 của byte đã ghi."""
    return write_json_atomic(Path(out), document, mode="utf8")


def upsert_index(index_path: Path, *, episode: str, domain: str, file: str, label: str | None = None) -> dict[str, Any]:
    """``index.json`` cạnh các file tập: thêm/thay đúng MỘT entry của ``episode``; các tập khác giữ nguyên."""
    existing = _read(Path(index_path)) or {}
    rows = [r for r in existing.get("episodes") or [] if isinstance(r, dict) and r.get("episode") != episode] \
        if existing.get("schema") == INDEX_SCHEMA else []
    entry = {"episode": episode, "domain": domain, "file": file, **({"label": label} if label else {})}
    document = {"schema": INDEX_SCHEMA, "episodes": sorted([*rows, entry], key=lambda r: str(r.get("episode")))}
    write_json_atomic(Path(index_path), document, mode="utf8")
    return document


def main(argv: list[str] | None = None) -> int:
    """``python -m engine.video.ui_state ...``: cờ + mã thoát ở ``ui_state_cli`` (nhập tại chỗ: module đó nhập ``build`` từ đây)."""
    from .ui_state_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
