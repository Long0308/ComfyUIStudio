"""Cổng domain/sha của bước logo: không bật = từ chối; sha sai = từ chối; schema; trung lập domain trong engine/post."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from engine.config.loader import REPO_ROOT, SKILL_ROOT
from engine.config.schema import validate
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.post.logo import policy as policy_mod

SCHEMA = read_json(SKILL_ROOT / "schemas" / "domain.schema.json")
CARTOON = read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json")
LIVE = read_json(SKILL_ROOT / "domains" / "newtecons_live_action.json")
GOOD_SHA = "a" * 64


def synthetic_domain(sha: str = GOOD_SHA, *, enabled: bool = True, detect: dict | None = None) -> dict:
    block = {"enabled": enabled, "asset": {"path": "assets/logo.png", "sha256": sha}}
    if detect is not None:
        block["detect"] = detect
    return {"domain_id": "test_domain", "post": {"logo_composite": block}}


def good_detect() -> dict:
    return {"search_region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "mark_height_frac": {"min": 0.05, "max": 0.2},
            "aspect_tolerance": 0.4, "mark_rgb": [50, 55, 103], "dark_threshold": 50, "fill_range": [0.2, 0.95],
            "color_min_similarity": 0.5, "box_pad_frac": 0.2, "search_frames": 6, "min_score": 0.15,
            "min_margin": 0.05, "min_agreement": 0.5}


def test_cartoon_domain_is_refused_and_live_domain_is_enabled() -> None:
    with pytest.raises(Refused, match=policy_mod.NOT_ENABLED):
        policy_mod.logo_policy(CARTOON)
    live = policy_mod.logo_policy(LIVE)
    assert live.asset_sha256 == LIVE["post"]["logo_composite"]["asset"]["sha256"]
    assert live.detect is not None and live.detect.search_frames == 12
    assert "logo_composite" not in CARTOON.get("post", {})  # the cartoon domain never carries the logo flag (grade may)


def test_live_domain_asset_exists_and_hashes_to_the_declared_sha() -> None:
    live = policy_mod.logo_policy(LIVE)
    asset = REPO_ROOT / live.asset_path
    if not asset.is_file():
        pytest.skip(f"logo asset not on this machine: {asset}")
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == live.asset_sha256


@pytest.mark.parametrize("domain", [{}, {"domain_id": "x"}, {"domain_id": "x", "post": {}},
                                    {"domain_id": "x", "post": {"logo_composite": {}}},
                                    synthetic_domain(enabled=False)])
def test_missing_or_disabled_flag_refuses(domain: dict) -> None:
    with pytest.raises(Refused, match=policy_mod.NOT_ENABLED):
        policy_mod.logo_policy(domain)


@pytest.mark.parametrize("sha", ["", "abc", "A" * 64, "g" * 64])
def test_malformed_declared_sha_refuses(sha: str) -> None:
    with pytest.raises(Refused, match=policy_mod.ASSET_INVALID):
        policy_mod.logo_policy(synthetic_domain(sha))


def test_require_asset_refuses_wrong_file_and_wrong_declared_sha(tmp_path: Path) -> None:
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"logo-bytes")
    actual = hashlib.sha256(b"logo-bytes").hexdigest()
    policy = policy_mod.logo_policy(synthetic_domain(actual))
    bound = policy_mod.require_asset(policy, logo, None)
    assert bound["sha256"] == actual and bound["domain_declared_sha256"] == actual
    assert policy_mod.require_asset(policy, logo, actual)["sha256"] == actual
    with pytest.raises(Refused, match=policy_mod.SHA_MISMATCH):
        policy_mod.require_asset(policy, logo, "b" * 64)  # caller's sha disagrees with the domain
    logo.write_bytes(b"other-bytes")
    with pytest.raises(Refused, match=policy_mod.SHA_MISMATCH):
        policy_mod.require_asset(policy, logo, None)  # file bytes disagree with the domain
    with pytest.raises(Refused, match=policy_mod.ASSET_INVALID):
        policy_mod.require_asset(policy, tmp_path / "missing.png", None)


@pytest.mark.parametrize("change", [
    lambda d: d.pop("search_region"), lambda d: d["search_region"].update(x=0.8, w=0.5),
    lambda d: d.update(mark_height_frac={"min": 0.3, "max": 0.1}), lambda d: d.update(mark_rgb=[1, 2]),
    lambda d: d.update(mark_rgb=[1, 2, 300]), lambda d: d.update(dark_threshold=0.5),
    lambda d: d.update(fill_range=[0.9, 0.2]), lambda d: d.update(min_score=0), lambda d: d.update(search_frames=0),
    lambda d: d.update(min_agreement=True),
])
def test_invalid_detect_block_refuses(change) -> None:
    detect = good_detect()
    change(detect)
    with pytest.raises(Refused, match=policy_mod.DETECT_INVALID):
        policy_mod.logo_policy(synthetic_domain(detect=detect))


def test_schema_accepts_both_real_domains_and_rejects_malformed_post_blocks() -> None:
    assert validate(CARTOON, SCHEMA, label="domain") == []
    assert validate(LIVE, SCHEMA, label="domain") == []
    bad = [{"post": {"logo_composite": {"enabled": True}}},                                   # asset missing
           {"post": {"logo_composite": {"enabled": "yes", "asset": {"path": "p", "sha256": GOOD_SHA}}}},
           {"post": {"logo_composite": {"enabled": True, "asset": {"path": "p", "sha256": "xyz"}}}},
           {"post": {"other_step": {}}},
           {"post": {"logo_composite": {"enabled": True, "asset": {"path": "p", "sha256": GOOD_SHA},
                                        "detect": {"search_frames": 12}}}}]                   # detect incomplete
    for change in bad:
        assert validate({**copy.deepcopy(LIVE), **change}, SCHEMA, label="domain") != [], change


def test_engine_post_modules_stay_neutral_and_small() -> None:
    sources = sorted((SKILL_ROOT / "engine" / "post").rglob("*.py"))
    assert len(sources) >= 10
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 400, source
        for token in ("jenniejoy", "newtecons", "04-milk-and-mom", "ep04"):
            assert token not in text.lower(), (source, token)
