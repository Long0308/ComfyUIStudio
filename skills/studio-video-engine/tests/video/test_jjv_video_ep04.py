"""JennieJoy ep04 video route: real-shot planning, exact NTC block preservation and domain isolation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from video_fixtures import CARTOON, LIVE, run_video

from engine.layout.context import REPO_ROOT
from engine.video import routes as routes_mod

ROOT = REPO_ROOT
REAL_ROUTES = routes_mod.ROUTES
EPISODE = ROOT / "production-local/JennieJoyKids-Story/04-milk-and-mom/engine/episode.json"
SCRIPT = ROOT / "production-local/JennieJoyKids-Story/04-milk-and-mom/script/script-astra-candidate-v003.json"
SHOTS = ROOT / "production-local/JennieJoyKids-Story/04-milk-and-mom/engine/shots.json"
PROMPT_PACK = ROOT / "production-local/JennieJoyKids-Story/04-milk-and-mom/script/shot-prompt-pack-v004.json"
NTC_BLOCK_SHA256 = "365b1c07a1d194c8a9d28fb4643303af965dc8b3f717e05cb91022451afc67a7"


def _machine(tmp_path: Path) -> Path:
    comfy = tmp_path / "comfy"
    (comfy / "input").mkdir(parents=True)
    path = tmp_path / "machine.json"
    path.write_text(
        json.dumps(
            {
                "comfy": {"url": "http://127.0.0.1:1", "root": str(comfy), "container": "none"},
                "gpu_lock_path": str(tmp_path / "gpu.lock"),
            }
        ),
        encoding="utf-8",
    )
    return path


def _ep04_shotlist(tmp_path: Path) -> Path:
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    shots = json.loads(SHOTS.read_text(encoding="utf-8"))
    pack = json.loads(PROMPT_PACK.read_text(encoding="utf-8"))
    shot = next(row for row in script["shots"] if row["id"] == "S01_A")
    listed = next(row for row in shots["shots"] if row["shot"] == "S01_A")
    packed = next(row for row in pack["shots"] if row["shot_id"] == "S01_A")
    alice = next(row for row in packed["visible_cast"] if row["character_id"] == "alice")
    mother = next(row for row in packed["visible_cast"] if row["character_id"] == "mom-alice")
    prompt_parts = shot["video_prompt_en"].splitlines()
    document = {
        "schema": "jjv/script/v1",
        "film_id": "04-milk-and-mom",
        "domain": CARTOON,
        "fps": 24,
        "character_references": {
            "mother": {
                "character_id": "mom-alice",
                "bible_name": "Mother",
                "canonical_path": mother["canonical_path"],
                "canonical_sha256": mother["canonical_sha256"],
            },
            "alice": {
                "character_id": "alice",
                "bible_name": "Alice",
                "canonical_path": alice["canonical_path"],
                "canonical_sha256": alice["canonical_sha256"],
            },
        },
        "shots": [
            {
                "id": "S01_A",
                "speaker": "mother",
                "listener": "alice",
                "speech_text": shot["speech_text"],
                "duration_s": listed["clip"]["frames"] / 24,
                "visual": shot["visual"],
                "continuity": {
                    "setting_id": shot["continuity"]["setting_id"],
                    "camera_id": "S01_A_HYBRID_A",
                },
                "source": {
                    "scene_id": packed["scene_id"],
                    "prompt_as_code": {
                        "subject": shot["visual"],
                        "style": prompt_parts[0],
                        "composition": "Outdoor medium-wide establishing two-shot at the picnic table.",
                        "lighting": "Soft warm morning daylight with stable exposure and restrained pastel colors.",
                        "material": "Detailed soft hair and fabric, wooden picnic table, sealed lesson milk bottle, continuous wooden fence, metal milking pail.",
                        "negative": "No photographic humans, anime, flat vector restyling, native captions, letters, labels, logos, extra people, kitchen, bedroom, or enclosed room.",
                    },
                },
            }
        ],
    }
    path = tmp_path / "ep04-S01_A-jjv-script-v1.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _object_after(text: str, key: str) -> str:
    marker = f'"{key}":'
    key_at = text.index(marker)
    start = text.index("{", key_at)
    depth = 0
    in_string = escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
    raise AssertionError(f"unterminated object after {key}")


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _foreign_refs(domain: str, block: dict[str, Any]) -> list[str]:
    markers = {
        LIVE: (
            "jenniejoy_cartoon_3d",
            "JennieJoyKids",
            "04-milk-and-mom",
            "S01_A_HYBRID_A.api.json",
            "JennieJoyKids-H3-Video-Ready.json",
            "v003-7b-int8-tile768-int17-raw21",
            "jenniejoy_soft_v001",
        ),
        CARTOON: (
            "newtecons_live_action",
            "NEWTECONS",
            "NEWTECONS_H3",
            "v008-c2turbo.api.json",
            "newtecons_film_v001",
        ),
    }[domain]
    bad = []
    for text in _strings(block):
        for marker in markers:
            if marker.casefold() in text.casefold():
                bad.append(marker)
    return sorted(set(bad))


def test_real_ep04_s01a_plans_and_dry_runs_on_the_cartoon_route(tmp_path) -> None:
    for path in (EPISODE, SCRIPT, SHOTS, PROMPT_PACK):
        if not path.is_file():
            pytest.skip(f"real ep04 input missing: {path}")
    shotlist = _ep04_shotlist(tmp_path)
    out = tmp_path / "video-v001"
    base = [
        "--episode",
        str(EPISODE),
        "--out",
        str(out),
        "--machine",
        str(_machine(tmp_path)),
        "--routes",
        str(REAL_ROUTES),
    ]
    code, planned = run_video(["plan", *base, "--shotlist", str(shotlist)])
    assert code == 0, planned
    assert planned["template_sha256"] == "9d23360765c9891866570d6cb4d574e9f8e3d2ec8855adb5b04209a2b6de8036"
    receipt = json.loads((out / "S01_A" / "plan-receipt.json").read_text(encoding="utf-8"))
    assert receipt["domain"] == CARTOON
    assert receipt["shot"] == "S01_A" and receipt["duration_s"] == 5
    assert receipt["length"]["frames"] == 124 and receipt["length"]["grid"] == "17k+5"
    assert (receipt["geometry"]["width"], receipt["geometry"]["height"]) == (864, 480)
    assert receipt["seed"] == 20261027 and receipt["speech_text"] == "Alice, look! What does milk look like?"
    before = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
    code, dry = run_video(["run", *base, "--completion", "--lanes", "1", "--dry-run"])
    assert code == 0 and dry["dry_run"] is True and dry["domain"] == CARTOON
    assert dry["gates_preview"]["would_stop_at"] == "gpu-approval"
    assert dry["wrote"] == [] and [row["shot"] for row in dry["payloads"]] == ["S01_A"]
    assert "Alice, look! What does milk look like?" in dry["payloads"][0]["prompt"]["text"]
    after = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
    assert after == before


def test_newtecons_block_is_byte_for_byte_unchanged() -> None:
    block = _object_after(REAL_ROUTES.read_bytes().decode("utf-8"), LIVE).encode("utf-8")
    assert hashlib.sha256(block).hexdigest() == NTC_BLOCK_SHA256


def test_cross_domain_template_recipe_or_lut_reference_is_rejected() -> None:
    raw = json.loads(REAL_ROUTES.read_text(encoding="utf-8"))
    assert _foreign_refs(LIVE, raw["domains"][LIVE]) == []
    assert _foreign_refs(CARTOON, raw["domains"][CARTOON]) == []

    live_bad = copy.deepcopy(raw["domains"][LIVE])
    live_bad["template"] = copy.deepcopy(raw["domains"][CARTOON]["template"])
    assert "S01_A_HYBRID_A.api.json" in _foreign_refs(LIVE, live_bad)

    cartoon_bad = copy.deepcopy(raw["domains"][CARTOON])
    cartoon_bad["template"] = copy.deepcopy(raw["domains"][LIVE]["template"])
    assert "NEWTECONS_H3" in _foreign_refs(CARTOON, cartoon_bad)

    live_recipe_bad = copy.deepcopy(raw["domains"][LIVE])
    live_recipe_bad["upscale"]["crop_mode"] = "jenniejoy_soft_v001"
    assert "jenniejoy_soft_v001" in _foreign_refs(LIVE, live_recipe_bad)

    cartoon_lut_bad = copy.deepcopy(raw["domains"][CARTOON])
    cartoon_lut_bad["upscale"]["comment"] += " newtecons_film_v001"
    assert "newtecons_film_v001" in _foreign_refs(CARTOON, cartoon_lut_bad)
