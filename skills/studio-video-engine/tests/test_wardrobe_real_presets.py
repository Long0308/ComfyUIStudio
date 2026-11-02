"""Guard on the REAL wardrobe presets: no helmet and no reflective vest in context ``van_phong``.

User rule (31/10): offices and site-container offices never show a helmet or a reflective vest.
The other tests use synthetic configs, so a regression in the real presets would pass them.

Reads two real files READ-ONLY, skipping when a file is absent (CI on another machine):
  * ComfyUI UI preset registry  -> ``contexts.van_phong[*]`` fields ``name`` / ``file`` / ``role``
  * engine bridge config         -> ``wardrobe.<domain>.contexts.van_phong[*]`` item ids

The ``secret`` file next to the bridge config is never opened.
Engine code stays domain-neutral: the real paths and the domain name live only in this test file.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]  # tests -> studio-video-engine -> skills -> .agents -> 03 Voice
UI_PRESETS = (REPO_ROOT / "production-local" / "ComfyUI" / "custom_nodes" / "newtecons_step_ui"
              / "web" / "data" / "wardrobe" / "newtecons_live_action.json")
BRIDGE_CONFIG = REPO_ROOT / "production-local" / "engine" / "bridge" / "config.json"
DOMAIN = "newtecons_live_action"
CONTEXT = "van_phong"

# Vietnamese keywords, diacritic-insensitive: HELMET; MU = mũ; NON = nón; VEST; PHAN QUANG = phản quang.
FORBIDDEN_KEYWORDS = ("HELMET", "MU", "NON", "VEST", "PHAN QUANG")
FORBIDDEN_ID_PREFIXES = ("NT_HELMET_", "NT_VEST_")

# "ÁO PHẢN TRONG.png" contains none of the keywords above; it is a SHIRT (user: wardrobe_shirt_fine_microgrid...).
# Whitelisted by full sha256 so the exemption is bound to this exact file, not to its name.
WHITELIST_SHA256 = {
    "59aba9523b6177e3702c831e4abe44f3b7cca03477f1c85c274565cec086c57e",  # ÁO PHẢN TRONG.png (shirt)
}


def _norm(text: object) -> str:
    """Upper-case, strip diacritics, turn separators (_ - / . space) into single spaces."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("Đ", "D").replace("đ", "d")
    return re.sub(r"[\W_]+", " ", stripped.upper()).strip()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registry_violations(path: Path) -> list[str]:
    """Return one message per forbidden keyword found in a van_phong item (whitelisted sha skipped)."""
    doc = _load(path)
    items = doc["contexts"].get(CONTEXT)
    assert isinstance(items, list), f"context {CONTEXT!r} missing or not a list in {path.name}"
    out: list[str] = []
    for index, item in enumerate(items):
        if str(item.get("sha256", "")).lower() in WHITELIST_SHA256:
            continue
        for field in ("name", "file", "role"):
            text = _norm(item.get(field, ""))
            for keyword in FORBIDDEN_KEYWORDS:
                if keyword in text:
                    out.append(f"{CONTEXT}[{index}].{field}={item.get(field)!r} contains {keyword!r}")
    return out


def bridge_violations(path: Path) -> list[str]:
    """Return one message per van_phong item id that starts with a forbidden prefix."""
    doc = _load(path)
    items = doc["wardrobe"][DOMAIN]["contexts"].get(CONTEXT)
    assert isinstance(items, list), f"wardrobe.{DOMAIN}.contexts.{CONTEXT} missing or not a list"
    out: list[str] = []
    for index, entry in enumerate(items):
        item_id = str(entry.get("item", "")) if isinstance(entry, dict) else str(entry)
        if item_id.startswith(FORBIDDEN_ID_PREFIXES):
            out.append(f"wardrobe.{DOMAIN}.contexts.{CONTEXT}[{index}]={item_id!r}")
    return out


def _need(path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"real preset absent, skipped: {path}")


def test_real_ui_registry_van_phong_has_no_helmet_or_vest() -> None:
    _need(UI_PRESETS)
    assert registry_violations(UI_PRESETS) == []


def test_real_bridge_config_van_phong_has_no_helmet_or_vest() -> None:
    _need(BRIDGE_CONFIG)
    assert bridge_violations(BRIDGE_CONFIG) == []


_MINIMAL_UI = {"contexts": {CONTEXT: [{"name": "ÁO PHẢN TRONG.png", "file": "w/59aba9523b61_AO_PHAN_TRONG.png",
                                       "sha256": next(iter(WHITELIST_SHA256)), "role": "shirt"}]}}
_MINIMAL_BRIDGE = {"wardrobe": {DOMAIN: {"contexts": {CONTEXT: ["NT_SHIRT_FINE_GRID_V001"]}}}}


@pytest.mark.parametrize("injected", [
    {"name": "UNIFORM_HELMET_INJECTED.png", "file": "w/deadbeef0000_HELMET.png", "sha256": "0" * 64, "role": "x"},
    {"name": "MŨ BẢO HIỂM.png", "file": "w/deadbeef0001_mu.png", "sha256": "1" * 64, "role": "x"},
    {"name": "x.png", "file": "w/deadbeef0002_NON.png", "sha256": "2" * 64, "role": "x"},
    {"name": "AO_PHAN_QUANG_9.png", "file": "w/deadbeef0003_vest.png", "sha256": "3" * 64, "role": "x"},
    {"name": "x.png", "file": "w/deadbeef0004_x.png", "sha256": "4" * 64, "role": "wardrobe_vest_front_geometry"},
])
def test_guard_bites_on_injected_ui_helmet_or_vest(tmp_path, monkeypatch, injected) -> None:
    # Temp copy of the real file (stand-in when absent); the real file is never written.
    target = tmp_path / "newtecons_live_action.json"
    data = copy.deepcopy(_load(UI_PRESETS) if UI_PRESETS.is_file() else _MINIMAL_UI)
    data["contexts"][CONTEXT].append(injected)
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(globals(), "UI_PRESETS", target)
    with pytest.raises(AssertionError):
        test_real_ui_registry_van_phong_has_no_helmet_or_vest()


@pytest.mark.parametrize("injected_id", ["NT_HELMET_WHITE_V001", "NT_VEST_KKT_V001"])
def test_guard_bites_on_injected_bridge_helmet_or_vest(tmp_path, monkeypatch, injected_id) -> None:
    target, data = tmp_path / "config.json", copy.deepcopy(_load(BRIDGE_CONFIG) if BRIDGE_CONFIG.is_file()
                                                           else _MINIMAL_BRIDGE)
    data["wardrobe"][DOMAIN]["contexts"][CONTEXT].append(injected_id)
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(globals(), "BRIDGE_CONFIG", target)
    with pytest.raises(AssertionError):
        test_real_bridge_config_van_phong_has_no_helmet_or_vest()


def test_whitelisted_shirt_is_not_flagged_negative_control(tmp_path) -> None:
    """Negative control: the whitelisted shirt, with a name that would otherwise match, must pass."""
    entry = {"name": "ÁO PHẢN TRONG HELMET-LIKE.png", "file": "w/59aba9523b61_AO_PHAN_TRONG.png",
             "sha256": next(iter(WHITELIST_SHA256)), "role": "shirt"}
    target = tmp_path / "newtecons_live_action.json"
    target.write_text(json.dumps({"contexts": {CONTEXT: [entry]}}, ensure_ascii=False), encoding="utf-8")
    assert registry_violations(target) == []
