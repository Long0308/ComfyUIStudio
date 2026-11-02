"""``jjv video plan`` — group ``01 ĐỌC SHOTLIST``: shotlist đã duyệt -> state ``planned`` + plan receipt từng shot.

Shotlist là tài liệu ``jjv/script/v1`` (script đã APPROVED, có ``prompt_as_code`` và ``character_references``
hash-bound).  Mỗi shot nhận: thứ tự, thời lượng, số frame trên lưới H3 của domain, seed, ảnh tham chiếu nhân
vật (sha256 đã kiểm trên đĩa), target 1080p và chính sách upscale.  WAV và anchor ở đây là ``pending``: WAV
thoại của shot là ``preparation.json -> wav.sha256`` do ``jjv h3 prepare`` ghi (AGENTS.md), anchor là ảnh native đã
duyệt do ``jjv h3 inputs`` bind.  Không ghi gì khi có bất kỳ từ chối nào.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..core.paths import resolve_data_path
from ..h3.prepare import safe
from ..layout.context import REPO_ROOT, Context
from . import longtake as longtake_mod
from . import routes as routes_mod
from . import state as state_mod
from . import ui_wardrobe
from . import tiers

SHOT_KEYS = ("id", "duration_s", "source")  # speaker/speech_text chỉ bắt buộc khi shot CÓ THOẠI (shot không lời: speech none)
CODE_KEYS = ("subject", "style", "composition", "lighting", "material", "negative")
WARDROBE_RULES_KEY = "wardrobe_prompts"  # hàng routes của domain: {<context>: {"rule": <câu ghép vào prompt>, "forbid": [từ cấm]}}


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def _speech_of(row: dict[str, Any]) -> str | None:
    """Thoại của shot, hoặc None khi shot không lời (khoá vắng / None / chỉ khoảng trắng)."""
    text = row.get("speech_text")
    if text is None or (isinstance(text, str) and not text.strip()):
        return None
    if not isinstance(text, str):
        raise Refused(f"speech_text must be text, got {text!r}")
    return text


def load_shotlist(ctx: Context, path: Path, routes: dict[str, Any]) -> dict[str, Any]:
    """Shotlist của ĐÚNG episode + domain, schema nằm trong ``routes.shotlist_schemas``; mọi shot đủ trường."""
    document = read_json(path)
    if not isinstance(document, dict) or document.get("schema") not in routes["shotlist_schemas"]:
        raise Refused(f"{path}: shotlist schema must be one of {routes['shotlist_schemas']}")
    if document.get("domain") != ctx.domain_id:
        raise Refused(f"VIDEO_DOMAIN_REFUSED: shotlist domain {document.get('domain')!r} is not the episode domain "
                      f"{ctx.domain_id!r}; domains are never mixed")
    if document.get("film_id") != ctx.episode_id:
        raise Refused(f"shotlist film_id {document.get('film_id')!r} is not episode {ctx.episode_id!r}")
    shots = document.get("shots")
    if not isinstance(shots, list) or not shots:
        raise Refused(f"{path}: shotlist has no shots")
    seen: set[str] = set()
    for row in shots:
        if not isinstance(row, dict) or any(key not in row for key in SHOT_KEYS):
            raise Refused(f"{path}: every shot needs {list(SHOT_KEYS)}")
        shot = safe(row["id"])
        if shot in seen:
            raise Refused(f"{path}: duplicate shot id {shot}")
        seen.add(shot)
        code = (row.get("source") or {}).get("prompt_as_code")
        if not isinstance(code, dict) or any(not isinstance(code.get(k), str) or not code[k] for k in CODE_KEYS):
            raise Refused(f"{shot}: source.prompt_as_code needs text for {list(CODE_KEYS)}")
        duration = row["duration_s"]
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise Refused(f"{shot}: duration_s must be a positive number")
        speech = _speech_of(row)
        if speech is not None and not isinstance(row.get("speaker"), str):
            raise Refused(f"{shot}: a shot with speech_text needs a speaker")
        props = row.get("props", [])
        if not isinstance(props, list) or any(not isinstance(p, str) or not p.strip() for p in props):
            raise Refused(f"PROPS_INVALID: {shot}: props must be a list of non-empty strings, got {props!r}")
    fps = ctx.domain["frame_rates"]["native_fps"]
    if document.get("fps") not in (None, fps):
        raise Refused(f"{path}: shotlist fps {document.get('fps')} differs from the domain native_fps {fps}")
    return document


def _reference(shotlist: dict[str, Any], role: str, repo_root: Path) -> dict[str, Any]:
    entry = (shotlist.get("character_references") or {}).get(role)
    if not isinstance(entry, dict) or not isinstance(entry.get("canonical_path"), str) \
            or not isinstance(entry.get("canonical_sha256"), str):
        raise Refused(f"NO_CHARACTER_REFERENCE: role {role!r} has no hash-bound canonical reference in the shotlist")
    given = Path(entry["canonical_path"])
    path = resolve_data_path(given if given.is_absolute() else repo_root / given)
    require_hash(path, entry["canonical_sha256"], f"character reference {role}")
    return {"role": role, "character_id": entry.get("character_id"), "bible_name": entry.get("bible_name"),
            "path": str(Path(path).resolve()), "sha256": entry["canonical_sha256"]}


def refs_for(shotlist: dict[str, Any], row: dict[str, Any], face_ports: list, repo_root: Path) -> list[dict]:
    """Ảnh tham chiếu theo thứ tự speaker, listener; chỉ ``len(face_ports)`` ảnh đầu được bind vào graph."""
    roles = [r for r in (row.get("speaker"), row.get("listener")) if r]  # shot không lời có thể không có speaker
    refs = []
    for index, role in enumerate(roles):
        item = _reference(shotlist, role, repo_root)
        bound = index < len(face_ports)
        refs.append({**item, "picture": index + 1, "bound": bound,
                     "ports": face_ports[index] if bound else None,
                     **({} if bound else {"note": "the template graph has no free reference port for this role"})})
    return refs


def _context_key(value: Any, shot: str, who: str) -> str:
    key = ui_wardrobe.context_of({"context": value})
    if key is None:
        raise Refused(f"WARDROBE_CONTEXT_UNKNOWN: {shot}: {who} context {value!r} is not in the wardrobe vocabulary "
                      f"{sorted(ui_wardrobe.ALIASES)}; never guessed")
    return key


def wardrobe_for(route: dict[str, Any], row: dict[str, Any], shot: str) -> dict[str, Any] | None:
    """Context trang phục của shot (khoá shotlist ``context``/``setting``/``location`` + ``context_per_character``, cùng từ vựng
    với ``ui_wardrobe``) kèm luật prompt của từng context đọc từ hàng routes ``wardrobe_prompts`` (chữ luật là DỮ LIỆU theo
    domain; code không chứa từ nào).  Không khoá context ⇒ None (prompt như cũ); context lạ hoặc chưa có luật ⇒ Refused."""
    raw = next((row[k] for k in ui_wardrobe.CONTEXT_KEYS if isinstance(row.get(k), str) and row[k].strip()), None)
    per_raw = row.get(ui_wardrobe.PER_CHARACTER_KEY)
    per_raw = per_raw if isinstance(per_raw, dict) else {}
    if raw is None and not per_raw:
        return None
    context = _context_key(raw, shot, "shot") if raw is not None else None
    per = {str(c): _context_key(v, shot, f"character {c!r}") for c, v in per_raw.items()}
    rules = route.get(WARDROBE_RULES_KEY) or {}
    needed = sorted({c for c in (context, *per.values()) if c})
    missing = [c for c in needed if not isinstance(rules.get(c), dict) or not isinstance(rules[c].get("rule"), str)
               or not rules[c]["rule"].strip()]
    if missing:
        raise Refused(f"WARDROBE_PROMPT_RULE_MISSING: {shot}: context {missing} has no `{WARDROBE_RULES_KEY}` rule text in the "
                      "video routes row of this domain; add it there (never guessed)")
    has_props = bool(row.get("props"))
    return {"context": context, "per_character": per,
            "rules": {c: _rule_entry(rules[c], has_props) for c in needed}}


def _rule_entry(source: dict[str, Any], has_props: bool) -> dict[str, Any]:
    """Một luật trang phục của routes -> ``{rule, forbid[, worn_markers]}``.  Shot khai đạo cụ dùng ``rule_with_props`` khi domain
    có (vd bỏ "never carried" khỏi luật công trường); khoá tuỳ chọn chỉ có trong kết quả khi routes có."""
    text = source["rule"]
    if has_props and isinstance(source.get("rule_with_props"), str) and source["rule_with_props"].strip():
        text = source["rule_with_props"]
    entry: dict[str, Any] = {"rule": text.strip(),
                             "forbid": [str(t).strip() for t in (source.get("forbid") or []) if str(t).strip()]}
    worn = [str(t).strip() for t in (source.get("worn_markers") or []) if str(t).strip()]
    if worn:
        entry["worn_markers"] = worn
    return entry


def build(ctx: Context, shotlist_path: Path, out: Path, *, routes: dict[str, Any], upscale_backend: str | None = None,
          repo_root: Path = REPO_ROOT, tier: str = "preview", tier_approval: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(plan, [plan receipt per shot])``; không ghi gì.  Mọi từ chối xảy ra trước mọi ghi."""
    route = routes_mod.domain_route(ctx, routes)
    template = routes_mod.template_for(route, repo_root)
    shotlist = load_shotlist(ctx, shotlist_path, routes)
    policy = route["upscale"]
    backend = upscale_backend or policy["default_backend"]
    if backend not in policy["backends"]:
        raise Refused(f"upscale backend {backend!r} is not one of {policy['backends']}")
    fps = ctx.domain["frame_rates"]["native_fps"]
    ports = route["ports"]
    shotlist_ref = {"path": str(Path(shotlist_path).resolve()), "sha256": sha256_file(shotlist_path)}
    resolution, geometry = tiers.resolve(ctx, route, template, tier, tier_approval, shotlist_ref,
                                         [r["id"] for r in shotlist["shots"]])
    policy = {**policy, "target": resolution["target"]}
    routes_ref = {"path": str(Path(routes["_path"]).resolve()), "sha256": routes["_sha256"]}
    receipts = []
    for order, row in enumerate(shotlist["shots"], 1):
        shot = safe(row["id"])
        source = row.get("source") or {}
        speech = _speech_of(row)
        take = longtake_mod.decide_take_mode(ctx.domain_id, route, row, row.get("take_mode"))  # Refused trước mọi ghi
        take_windows = None
        if take["take_mode"] == "long" and (row.get("beats") or row.get("windows")):
            block = longtake_mod.long_block(ctx.domain_id, route)
            count = longtake_mod.window_count(row["duration_s"], block["max_windows"])
            take_windows = longtake_mod.window_beats(row, count)
        receipts.append({
            "schema": state_mod.PLAN_RECEIPT_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "tier": tier, "resolution": resolution,
            "shot": shot, "order": order, "logical_shot": shot, "scene_id": source.get("scene_id"),
            "stage": routes["stages"][0], "duration_s": row["duration_s"], "fps": fps,
            "length": routes_mod.frame_length(row["duration_s"], fps, route["frame_grid"]),
            "seed": int(route["seed_base"]) + order - 1,
            "seed_source": f"routes seed_base {route['seed_base']} + shot order - 1",
            "speech": "none" if speech is None else "dialogue",
            "speaker": row.get("speaker") if speech is not None else None, "listener": row.get("listener"),
            "speech_text": speech,
            "props": [str(p) for p in row.get("props") or []],
            **({"geometry": geometry} if geometry else {}),
            "refs": refs_for(shotlist, row, ports["face"], repo_root), "ports": ports, "template": template,
            "shotlist": shotlist_ref, "routes": routes_ref,
            "prompt_as_code": source["prompt_as_code"], "visual": row.get("visual"),
            "continuity": row.get("continuity"), "tts_hint": source.get("tts_hint"),
            "wardrobe": wardrobe_for(route, row, shot),
            "wav": ({"status": "pending", "rule": "the conditioning WAV is preparation.json -> wav.sha256 written by "
                                                  "`jjv h3 prepare` from a listen-approved voice WAV; trim once before H3"}
                    if speech is not None else
                    {"status": "not-applicable", "rule": "non-dialogue shot (speech none): no conditioning WAV, no lip-sync"}),
            "anchor": {"status": "pending", "rule": "the scene anchor is the approved `jjv images native` image bound "
                                                    "by `jjv h3 inputs`"},
            "upscale": {"backend": backend, "target": policy["target"],
                        "qualified": backend in (policy.get("qualified") or {})},
            "h3_route": take["route"], "take_mode": take["take_mode"], "take_route": take["route"],
            "take_reason": take["reason"], "take_mode_requested": take["take_mode_requested"],
            "long_take_flag": row.get("long_take") is True, "take_windows": take_windows,
            "delivery": ctx.domain.get("delivery", {}).get("master"),
        })
    plan = {"schema": state_mod.PLAN_SCHEMA, "episode_id": ctx.episode_id, "domain": ctx.domain_id,
            "tier": tier, "resolution": resolution, "geometry": geometry,
            "shotlist": shotlist_ref, "routes": routes_ref, "template": template, "stages": routes["stages"],
            "upscale": {"backend": backend, "target": policy["target"]}, "fps": fps,
            "shots": [{"shot": r["shot"], "order": r["order"], "length_frames": r["length"]["frames"]} for r in receipts]}
    return plan, receipts


def plan(ctx: Context, shotlist_path: Path, out: Path, *, routes_path: Path | None = None,
         upscale_backend: str | None = None, tier: str = "preview", tier_approval: Path | None = None) -> dict[str, Any]:
    """Ghi ``<out>/plan.json`` + ``<out>/<shot>/{plan-receipt.json,state.json}`` (thư mục versioned, write-once)."""
    out = Path(out)
    if (out / state_mod.PLAN_FILE).exists():
        raise Refused(f"{out} already holds {state_mod.PLAN_FILE}: a plan folder is write-once; use a new versioned --out")
    routes = routes_mod.load_routes(routes_path)
    document, receipts = build(ctx, Path(shotlist_path), out, routes=routes, upscale_backend=upscale_backend,
                               tier=tier, tier_approval=tier_approval)
    rows = []
    for receipt in receipts:
        folder = state_mod.shot_dir(out, receipt["shot"])
        receipt_path = folder / state_mod.PLAN_RECEIPT_FILE
        sha = write_json_once(receipt_path, receipt, mode="utf8")
        state = state_mod.new_state(ctx, receipt["shot"], receipt["order"], {"path": f"{receipt['shot']}/{receipt_path.name}",
                                                                           "sha256": sha})
        state_mod.write_state(out, state)
        rows.append({"shot": receipt["shot"], "order": receipt["order"], "state": state["state"],
                     "length_frames": receipt["length"]["frames"], "seed": receipt["seed"],
                     "refs": [r["sha256"][:12] for r in receipt["refs"] if r["bound"]],
                     "plan_receipt_sha256": sha})
    plan_sha = write_json_once(out / state_mod.PLAN_FILE, document, mode="utf8")
    return {"out": str(out), "plan_sha256": plan_sha, "template_sha256": document["template"]["sha256"],
            "shotlist_sha256": document["shotlist"]["sha256"], "upscale": document["upscale"], "shots": rows,
            "tier": tier, "resolution": document["resolution"], "geometry": document["geometry"],
            "next": f"jjv video run --episode {ctx.episode_id} --out {out} --completion --lanes N [--dry-run]"}


__all__ = ["plan", "build", "load_shotlist", "refs_for", "wardrobe_for", "WARDROBE_RULES_KEY"]
