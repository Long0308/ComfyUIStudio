"""Group ``02 VIẾT PROMPT``: prompt revision đóng băng + prompt receipt (CPU, chạy được theo lane, không GPU).

Prompt được ghép tất định từ phần mở đầu của template (node prompt của graph) và ``prompt_as_code`` của shot;
cùng input ⇒ cùng byte ⇒ cùng sha256 (A3: idempotent).  Cùng revision mà khác nội dung ⇒ Refused: sửa prompt
là một revision MỚI, không ghi đè.

Luật trang phục theo context (plan receipt ``wardrobe``, chữ luật từ hàng routes ``wardrobe_prompts`` của domain — user
31/10: văn phòng/container office không mũ không gile, ngoài công trường full PPE mũ đội): câu luật của context được ghép
vào prompt, và khi cả shot chỉ có MỘT context thì mọi cụm của ``prompt_as_code`` chứa từ trong ``forbid`` của context đó bị
bỏ khỏi prompt (kịch bản vẫn nguyên văn trong plan receipt).  Shot không có ``wardrobe`` ⇒ prompt y như trước.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_bytes, sha256_file, write_json_once, write_once
from . import state as state_mod

PROMPT_FILE = "prompt.txt"
RECEIPT_FILE = "prompt-receipt.json"
GENERATOR = "jjv video prompt / compose v1"
CODE_FIELDS = ("subject", "style", "composition", "lighting", "material", "negative")
_SEGMENT = re.compile(r"\s*[,;]\s*")


def _mentions(segment: str, forbid: list[str]) -> bool:
    return any(re.search(rf"(?<![\w-]){re.escape(term)}s?(?![\w-])", segment, re.IGNORECASE) for term in forbid)


_NEGATED_WORN = re.compile(r"\b(?:not|never)\s+(?:worn|wear\w*)\b", re.IGNORECASE)


def _prop_core(prop: str) -> str:
    """Tên đạo cụ không có phần chú thích trong ngoặc: ``white logo helmet (prop, not worn)`` -> ``white logo helmet``."""
    return re.sub(r"\s*\([^)]*\)", "", prop).strip()


def _prop_terms(props: list[str], forbid: list[str]) -> list[str]:
    """Các từ cấm mà CHÍNH đạo cụ đã khai mang theo (vd ``helmet``): cụm nhắc tới chúng là mô tả đạo cụ, không phải trang phục."""
    cores = [_prop_core(p).casefold() for p in props]
    return [term for term in forbid if any(_mentions(core, [term]) for core in cores)]


def _filter(text: str, forbid: list[str], props: list[str] | None = None,
            worn_markers: list[str] | None = None) -> tuple[str, list[str]]:
    """Bỏ các cụm (tách bằng dấu phẩy / chấm phẩy) có chứa một từ trong ``forbid``; trả ``(phần giữ, [cụm đã bỏ])``.

    Cụm nhắc tới từ cấm MÀ ĐẠO CỤ đã khai (``props``) được giữ, trừ khi cụm có dấu hiệu MẶC (``worn_markers`` sau khi bỏ phủ
    định ``not worn``): đạo cụ không bị lọc, còn câu mặc mũ/gile vẫn bị bỏ.  Không có ``props`` ⇒ hành vi cũ nguyên văn."""
    if not forbid:
        return text, []
    carried = _prop_terms(props or [], forbid)
    kept, removed = [], []
    for segment in _SEGMENT.split(text.strip()):
        if not segment:
            continue
        drop = _mentions(segment, forbid)
        if drop and carried and _mentions(segment, carried):
            worn = _mentions(_NEGATED_WORN.sub("", segment), worn_markers or [])
            drop = worn
        (removed if drop else kept).append(segment)
    return ", ".join(kept), removed


def apply_wardrobe(receipt: dict[str, Any]) -> dict[str, Any]:
    """``{"lines": [câu luật ghép vào prompt], "code": prompt_as_code đã lọc, "removed": {trường: [cụm đã bỏ]}}``.

    Một context cho cả shot ⇒ một dòng luật + lọc; ``context_per_character`` ⇒ một dòng luật mỗi nhân vật, và chỉ lọc khi mọi
    context trùng nhau (hai context khác nhau thì từ cấm của người này là trang phục hợp lệ của người kia).  ``props`` của shot
    không bao giờ bị lọc (xem :func:`_filter`); mệnh đề đạo cụ được ghép riêng trong :func:`compose`."""
    code = dict(receipt["prompt_as_code"])
    wardrobe = receipt.get("wardrobe") or {}
    rules = wardrobe.get("rules") or {}
    context, per = wardrobe.get("context"), wardrobe.get("per_character") or {}
    lines: list[str] = []
    if context and not per:
        lines.append(f"Wardrobe rule: {rules[context]['rule']}")
    elif per:
        if context:
            lines.append(f"Wardrobe rule (everyone else in frame): {rules[context]['rule']}")
        lines += [f"Wardrobe rule ({character}): {rules[key]['rule']}" for character, key in per.items()]
    contexts = {c for c in (context, *per.values()) if c}
    removed: dict[str, list[str]] = {}
    if len(contexts) == 1:
        rule = rules[next(iter(contexts))]
        forbid = list(rule.get("forbid") or [])
        props = [str(p) for p in receipt.get("props") or []]
        worn = list(rule.get("worn_markers") or [])
        for field in CODE_FIELDS:
            code[field], gone = _filter(str(code[field]), forbid, props, worn)
            if gone:
                removed[field] = gone
    return {"lines": lines, "code": code, "removed": removed}


def compose(template_prompt: str, receipt: dict[str, Any]) -> str:
    """Prompt live-action của shot: mở đầu template + luật trang phục theo context + hành động/camera/thoại của shot đó."""
    wardrobe = apply_wardrobe(receipt)
    code = wardrobe["code"]
    continuity = receipt.get("continuity") or {}
    pictures = [f"<Picture {r['picture']}> = {r.get('bible_name') or r['role']} ({r['role']}, {r.get('character_id')})."
                for r in receipt["refs"] if r.get("bound")]
    unbound = [r["role"] for r in receipt["refs"] if not r.get("bound")]
    lines = [str(template_prompt).strip(), "",
             f"SHOT {receipt['shot']} ({receipt.get('scene_id')}, {float(receipt['duration_s']):g} s, "
             f"camera {continuity.get('camera_id')}, setting {continuity.get('setting_id')}).",
             *pictures]
    if unbound:
        lines.append(f"Also in frame (no reference picture bound): {', '.join(unbound)}.")
    lines += wardrobe["lines"]
    props = [_prop_core(str(p)) for p in receipt.get("props") or []]
    if props:  # đạo cụ cầm/đập trong cảnh: mệnh đề riêng, không bị bộ lọc trang phục
        lines.append(f"Props: {', '.join(props)} (held/handled, not worn).")
    fields = (("Subject", code["subject"]), ("Style", code["style"]), ("Composition", code["composition"]),
              ("Lighting", code["lighting"]), ("Material", code["material"]))
    lines += [f"{label}: {value}." for label, value in fields if value]  # trống chỉ khi bộ lọc bỏ hết cụm của trường đó
    if receipt.get("speech", "dialogue") == "none":
        lines.append("No dialogue in this shot: no spoken words, no lip-sync; the shot is silent apart from the scene's own "
                     "sound.")
    else:
        lines.append(f"Dialogue (vi, spoken by {receipt['speaker']}): \"{receipt['speech_text']}\" - performance timed to "
                     "the supplied dialogue audio.")
    if code["negative"]:
        lines.append(f"Negative: {code['negative']}.")
    return "\n".join(lines) + "\n"


def prompt_dir(out: Path, shot: str, revision: int) -> Path:
    return state_mod.shot_dir(out, shot) / "prompt" / state_mod.rev(revision)


def write_prompt(out: Path, shot: str, revision: int, text: str, *, body: dict[str, Any]) -> dict[str, Any]:
    """``prompt.txt`` + ``prompt-receipt.json`` write-once; byte khác ở cùng revision ⇒ Refused (không ghi đè)."""
    folder = prompt_dir(out, shot, revision)
    payload = text.encode("utf-8")
    existing = folder / PROMPT_FILE
    reused = existing.is_file()
    if reused and existing.read_bytes() != payload:
        raise Refused(f"{shot}: prompt revision {state_mod.rev(revision)} already holds a different prompt "
                      f"({sha256_file(existing)[:12]} vs {sha256_bytes(payload)[:12]}); a changed prompt is a NEW "
                      "revision, never an overwrite")
    prompt_sha = write_once(existing, payload)
    receipt = {"schema": state_mod.PROMPT_RECEIPT_SCHEMA, **body, "shot": shot, "revision": revision,
               "prompt": {"path": PROMPT_FILE, "sha256": prompt_sha, "chars": len(text)}, "generator": GENERATOR}
    receipt_path = folder / RECEIPT_FILE
    receipt_sha = write_json_once(receipt_path, receipt, mode="utf8")
    return {"shot": shot, "revision": revision, "path": receipt_path, "receipt_sha256": receipt_sha,
            "prompt_sha256": prompt_sha, "reused": reused}


def read_prompt(out: Path, shot: str, revision: int) -> tuple[str, dict[str, Any]]:
    folder = prompt_dir(out, shot, revision)
    receipt = read_json(folder / RECEIPT_FILE)
    text_path = folder / PROMPT_FILE
    if not text_path.is_file() or sha256_file(text_path) != receipt["prompt"]["sha256"]:
        raise Refused(f"{shot}: {PROMPT_FILE} does not match its receipt; reconcile before any render")
    return text_path.read_text(encoding="utf-8"), receipt


__all__ = ["compose", "apply_wardrobe", "write_prompt", "read_prompt", "prompt_dir", "PROMPT_FILE", "RECEIPT_FILE"]
