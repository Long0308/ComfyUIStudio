"""Luật trang phục theo context trong prompt video (user 31/10): ``van_phong`` (văn phòng + container office công trường) =
áo sơ mi công ty, KHÔNG mũ, KHÔNG gile; ``cong_truong`` (ngoài trời trên công trường) = full PPE, mũ ĐỘI trên đầu.

Gap đo được (DRYRUN-WARDROBE-PROMPTS): script-v003 S02_A (van_phong) ghi ``material: "reflective polyester safety vests, ..."``
và ``prompt.compose`` ghép nguyên chuỗi vào prompt H3.  Chữ luật là DỮ LIỆU theo domain (hàng routes video ``wardrobe_prompts``),
code engine không chứa từ nào về PPE; shot không có khoá context ⇒ prompt y như cũ.  Không GPU, không ghi production.
"""

from __future__ import annotations

import json
import re

import pytest
from video_fixtures import CODE, LIVE, SHOT, VideoWorld, shot_row

from engine.core.errors import Refused
from engine.video import plan as plan_mod
from engine.video import prompt as prompt_mod
from engine.video import routes as routes_mod

# nguyên văn script-v003.json S02_A (:218) và S06_A (:340)
S02_MATERIAL = "reflective polyester safety vests, crisp paper blueprints, steel thermos cups, rugged concrete background"
S06_MATERIAL = "polished architectural glass curtain wall, clean white helmet with NEWTECONS logo, high-visibility orange vest"
ALLOWED = "no helmet, no safety vest"
FORBIDDEN = ("vest", "helmet", "hard hat", "ppe")
RULES = {
    "van_phong": {
        "rule": "Wardrobe (van_phong, office or site container office): the company fine blue-white grid shirt with the small "
                "collar logo only; no helmet, no safety vest, nothing reflective.",
        "forbid": ["helmet", "hard hat", "hardhat", "vest", "reflective", "hi-vis", "high-visibility", "PPE"]},
    "cong_truong": {
        "rule": "Wardrobe (cong_truong, outdoors on site): full PPE over the company shirt; the white safety helmet with the "
                "company logo is worn on the head, chin strap fastened, never carried; reflective safety vest on.",
        "forbid": []},
}


def _row(shot: str, material: str, **extra) -> dict:
    row = shot_row(shot)
    return {**row, "source": {**row["source"], "prompt_as_code": {**CODE, "material": material}}, **extra}


def _world(tmp_path, shots: list[dict], *, rules: dict | None = RULES) -> VideoWorld:
    world = VideoWorld(tmp_path, domain=LIVE, shots=shots)
    if rules is not None:
        routes = json.loads(world.routes.read_text("utf-8"))
        routes["domains"][LIVE]["wardrobe_prompts"] = rules
        world.routes.write_text(json.dumps(routes), encoding="utf-8")
    return world


def _compose(world: VideoWorld, shot: str = SHOT) -> tuple[str, dict]:
    routes = routes_mod.load_routes(world.routes)
    _, receipts = plan_mod.build(world.ctx(), world.shotlist, world.out, routes=routes)
    receipt = next(r for r in receipts if r["shot"] == shot)
    return prompt_mod.compose("template prompt", receipt), receipt


def _hits(text: str) -> list[str]:
    """Từ PPE còn sót sau khi bỏ đúng cụm cho phép ``no helmet, no safety vest``."""
    rest = text.replace(ALLOWED, "")
    return [word for word in FORBIDDEN if re.search(rf"\b{re.escape(word)}s?\b", rest, re.IGNORECASE)]


def test_van_phong_prompt_states_no_helmet_no_vest_and_drops_the_script_vest_phrase(tmp_path) -> None:
    world = _world(tmp_path, [_row(SHOT, S02_MATERIAL, context="van_phong")])
    text, receipt = _compose(world)
    assert ALLOWED in text
    assert _hits(text) == [], text
    assert "Material: crisp paper blueprints, steel thermos cups, rugged concrete background." in text
    assert receipt["wardrobe"]["context"] == "van_phong" and receipt["wardrobe"]["per_character"] == {}
    assert prompt_mod.apply_wardrobe(receipt)["removed"] == {"material": ["reflective polyester safety vests"]}
    assert receipt["prompt_as_code"]["material"] == S02_MATERIAL  # receipt giữ nguyên văn kịch bản (provenance)


def test_cong_truong_prompt_says_the_helmet_is_worn_and_keeps_the_site_material(tmp_path) -> None:
    world = _world(tmp_path, [_row("S06_A", S06_MATERIAL, context="cong_truong")])
    text, receipt = _compose(world, "S06_A")
    assert re.search(r"helmet[^.\n]*worn on the head", text), text
    assert f"Material: {S06_MATERIAL}." in text
    assert prompt_mod.apply_wardrobe(receipt)["removed"] == {}


def test_shot_without_a_context_key_keeps_the_old_prompt(tmp_path) -> None:
    world = _world(tmp_path, [shot_row()])
    text, receipt = _compose(world)
    assert receipt["wardrobe"] is None and "Wardrobe" not in text
    assert text.startswith("template prompt") and f"Material: {CODE['material']}." in text


def test_split_shot_gets_one_rule_per_character_and_no_filtering(tmp_path) -> None:
    row = _row("S03_A", "crisp collared fabric, a spare vest on the chair", listener="mother",
               context_per_character={"alice": "cong_truong", "mother": "van_phong"})
    row = {**row, "listener": "mother"}
    world = _world(tmp_path, [row])
    text, receipt = _compose(world, "S03_A")
    assert receipt["wardrobe"] == {"context": None, "per_character": {"alice": "cong_truong", "mother": "van_phong"},
                                   "rules": {k: RULES[k] for k in ("cong_truong", "van_phong")}}
    assert "Wardrobe rule (alice): " + RULES["cong_truong"]["rule"] in text
    assert "Wardrobe rule (mother): " + RULES["van_phong"]["rule"] in text
    assert "a spare vest on the chair" in text  # hai context ⇒ không lọc (gile của alice là hợp lệ)


def test_context_without_rule_text_in_routes_is_refused_never_guessed(tmp_path) -> None:
    world = _world(tmp_path, [_row(SHOT, S02_MATERIAL, context="van_phong")], rules=None)
    with pytest.raises(Refused, match="WARDROBE_PROMPT_RULE_MISSING"):
        _compose(world)


def test_unknown_context_value_is_refused(tmp_path) -> None:
    world = _world(tmp_path, [_row(SHOT, S02_MATERIAL, context="van_phong_suit")])
    with pytest.raises(Refused, match="WARDROBE_CONTEXT_UNKNOWN"):
        _compose(world)


def test_dry_run_payload_carries_the_filtered_prompt(tmp_path) -> None:
    """Đường thật: ``jjv video plan`` -> ``run --dry-run``: text vào cổng prompt của graph là prompt đã lọc."""
    world = _world(tmp_path, [_row(SHOT, S02_MATERIAL, context="van_phong")])
    code, _ = world.plan()
    assert code == 0
    result = world.run_direct(dry_run=True)
    text = result["payloads"][0]["prompt"]["text"]
    assert ALLOWED in text and _hits(text) == [], text
