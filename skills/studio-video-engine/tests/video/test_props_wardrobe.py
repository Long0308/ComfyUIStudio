"""Đạo cụ (``props``) và shot không lời trong prompt video (user 01/11, SCENE_01_HELMET_PROP).

Trong container văn phòng (van_phong) không ai ĐỘI mũ hay mặc gile; GDDA CẦM và đập một mũ trắng logo NEWTECONS xuống bàn — đó là
ĐẠO CỤ.  Luật: (1) ``props[]`` của shot đi từ shotlist vào plan receipt rồi vào prompt thành mệnh đề riêng ``Props: ... (held/handled,
not worn)``; (2) bộ lọc ``forbid`` của trang phục chỉ bỏ cụm MẶC/ĐỘI, không bao giờ bỏ cụm mô tả đạo cụ đã khai; (3) rule
``cong_truong`` không ghi "never carried" khi shot khai đạo cụ mũ; (4) shot không lời (không thoại) được lập plan, không WAV, không
lip-sync, ``speech: none``.  Không GPU, không mạng, không ghi production.
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

PROP = "white NEWTECONS logo helmet (prop, not worn)"
SLAM = "GDDA slams a white NEWTECONS logo helmet down on the table"
RULES = {
    "van_phong": {
        "rule": "Wardrobe (van_phong, office or site container office): the company fine blue-white grid shirt with the small "
                "collar logo only; no helmet, no safety vest, nothing reflective.",
        "forbid": ["helmet", "hard hat", "hardhat", "vest", "reflective", "hi-vis", "high-visibility", "PPE"],
        "worn_markers": ["worn", "wears", "wearing", "on the head", "on his head", "on her head"]},
    "cong_truong": {
        "rule": "Wardrobe (cong_truong, outdoors on site): full PPE over the company shirt; the white safety helmet with the "
                "company logo is worn on the head, chin strap fastened, never carried; reflective safety vest on.",
        "rule_with_props": "Wardrobe (cong_truong, outdoors on site): full PPE over the company shirt; the white safety helmet "
                           "with the company logo is worn on the head, chin strap fastened; reflective safety vest on. A helmet "
                           "the shot declares as a prop is held in hand, not worn.",
        "forbid": []},
}
# bản tuyên bố MẶC mũ — cụm mà prompt không được chứa (trừ khi là phủ định)
WORN_HELMET = re.compile(r"(?<!not )(?<!never )\bworn\b[^.\n]*helmet|\bwear(s|ing)?\b[^.\n]*helmet|helmet[^.\n]*\bworn on the head",
                         re.IGNORECASE)


def _row(shot: str, subject: str, material: str = "crisp paper blueprints, steel thermos cups", **extra) -> dict:
    row = shot_row(shot)
    return {**row, "source": {**row["source"], "prompt_as_code": {**CODE, "subject": subject, "material": material}}, **extra}


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


def test_scene01_like_shot_keeps_the_helmet_as_a_prop_and_states_no_worn_helmet(tmp_path) -> None:
    row = _row("SCENE_01", SLAM, context="van_phong", props=[PROP], speaker=None, speech_text=None)
    world = _world(tmp_path, [row])
    text, receipt = _compose(world, "SCENE_01")
    assert receipt["props"] == [PROP]
    assert "Subject: GDDA slams a white NEWTECONS logo helmet down on the table." in text  # cụm đạo cụ KHÔNG bị lọc
    assert "Props: white NEWTECONS logo helmet (held/handled, not worn)." in text
    assert WORN_HELMET.search(text) is None, text
    assert prompt_mod.apply_wardrobe(receipt)["removed"] == {}
    assert receipt["prompt_as_code"]["subject"] == SLAM  # receipt giữ nguyên văn kịch bản


def test_van_phong_shot_without_props_still_strips_the_helmet_phrase(tmp_path) -> None:
    world = _world(tmp_path, [_row(SHOT, SLAM, context="van_phong")])
    text, receipt = _compose(world)
    assert "Props:" not in text
    assert "helmet" not in text.replace("no helmet, no safety vest", "")
    assert prompt_mod.apply_wardrobe(receipt)["removed"] == {"subject": [SLAM]}


def test_worn_helmet_phrase_in_a_van_phong_shot_with_a_prop_is_still_stripped(tmp_path) -> None:
    """Có đạo cụ mũ không có nghĩa mọi câu nhắc mũ đều hợp lệ: câu MẶC mũ (có dấu hiệu worn) vẫn bị bỏ."""
    row = _row("SCENE_01", f"{SLAM}; GDDA wears a helmet on his head", context="van_phong", props=[PROP])
    world = _world(tmp_path, [row])
    text, receipt = _compose(world, "SCENE_01")
    assert "wears a helmet" not in text and WORN_HELMET.search(text) is None, text
    assert prompt_mod.apply_wardrobe(receipt)["removed"] == {"subject": ["GDDA wears a helmet on his head"]}


def test_props_clause_is_not_filtered_and_props_are_strings_only(tmp_path) -> None:
    row = _row("SCENE_01", SLAM, context="van_phong", props=[PROP, "steel thermos cup"], speaker=None, speech_text=None)
    text, receipt = _compose(_world(tmp_path, [row]), "SCENE_01")
    assert "Props: white NEWTECONS logo helmet, steel thermos cup (held/handled, not worn)." in text
    bad = _row("SCENE_01", SLAM, context="van_phong", props=[PROP, 7], speaker=None, speech_text=None)
    with pytest.raises(Refused, match="PROPS_INVALID"):
        _compose(_world(tmp_path / "bad", [bad]), "SCENE_01")


def test_cong_truong_shot_with_a_helmet_prop_does_not_inject_never_carried(tmp_path) -> None:
    row = _row("S06_A", "a white helmet on the table", context="cong_truong", props=[PROP])
    text, receipt = _compose(_world(tmp_path, [row]), "S06_A")
    assert "never carried" not in text
    assert "A helmet the shot declares as a prop is held in hand, not worn." in text
    assert receipt["wardrobe"]["rules"]["cong_truong"]["rule"] == RULES["cong_truong"]["rule_with_props"]


def test_cong_truong_shot_without_props_keeps_the_old_rule(tmp_path) -> None:
    text, receipt = _compose(_world(tmp_path, [_row("S06_A", "a clean site", context="cong_truong")]), "S06_A")
    assert "never carried" in text and receipt["wardrobe"]["rules"]["cong_truong"]["rule"] == RULES["cong_truong"]["rule"]


def test_non_dialogue_shot_plans_without_speaker_or_wav(tmp_path) -> None:
    row = _row("SCENE_01", "an empty field-office table", context="van_phong", speaker=None, speech_text=None)
    row.pop("listener", None)
    world = _world(tmp_path, [row])
    code, _ = world.plan()
    assert code == 0
    receipt = json.loads((world.out / "SCENE_01" / "plan-receipt.json").read_text("utf-8"))
    assert receipt["speech"] == "none" and receipt["speaker"] is None and receipt["speech_text"] is None
    assert receipt["wav"]["status"] == "not-applicable" and receipt["refs"] == []
    text, _ = _compose(world, "SCENE_01")
    assert "Dialogue" not in text and "No dialogue" in text and "lip-sync" not in text.replace("no lip-sync", "")


def test_dialogue_shot_still_carries_speech_and_pending_wav(tmp_path) -> None:
    world = _world(tmp_path, [_row(SHOT, "alice at the table", context="van_phong")])
    text, receipt = _compose(world)
    assert receipt["speech"] == "dialogue" and receipt["wav"]["status"] == "pending"
    assert 'Dialogue (vi, spoken by alice)' in text


def test_speech_without_speaker_is_still_refused(tmp_path) -> None:
    row = _row(SHOT, "alice at the table", context="van_phong")
    row.pop("speaker")
    with pytest.raises(Refused, match="speaker"):
        _compose(_world(tmp_path, [row]))
