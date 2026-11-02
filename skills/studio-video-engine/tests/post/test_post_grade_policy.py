"""Domain gate of the grade step: refuses unless the domain declares post.grade AND the LUT sha is declared."""
from __future__ import annotations

import copy

import pytest

from engine.config.loader import SKILL_ROOT
from engine.config.schema import validate
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.post.grade import policy as policy_mod

SCHEMA = read_json(SKILL_ROOT / "schemas" / "domain.schema.json")
LUT = SKILL_ROOT / "recipes" / "grade" / "jenniejoy_soft_v001.cube"
GOOD = sha256_file(LUT)


def domain(*, enabled: bool = True, sha: str = GOOD, luts: dict | None = None) -> dict:
    block = {"enabled": enabled, "luts": luts if luts is not None else {
        "jenniejoy_soft_v001": {"path": "recipes/grade/jenniejoy_soft_v001.cube", "sha256": sha}}}
    return {"domain_id": "test_domain", "post": {"grade": block}}


def test_no_grade_block_refuses():
    with pytest.raises(Refused, match="GRADE_NOT_ENABLED"):
        policy_mod.grade_policy({"domain_id": "test_domain", "post": {}})


def test_disabled_refuses():
    with pytest.raises(Refused, match="GRADE_NOT_ENABLED"):
        policy_mod.grade_policy(domain(enabled=False))


def test_bad_sha_declaration_refuses():
    with pytest.raises(Refused, match="GRADE_ASSET_INVALID"):
        policy_mod.grade_policy(domain(sha="xyz"))


def test_lut_not_declared_refuses():
    policy = policy_mod.grade_policy(domain())
    other = SKILL_ROOT / "recipes" / "grade" / "newtecons_film_v001.cube"
    with pytest.raises(Refused, match="LUT_NOT_DECLARED"):
        policy_mod.require_lut(policy, other)


def test_lut_sha_mismatch_refuses(tmp_path):
    # A LUT is identified by its declared file name; a tampered file keeps that name.
    bad_lut = tmp_path / "jenniejoy_soft_v001.cube"
    bad_lut.write_bytes(LUT.read_bytes() + b"\n# tampered\n")
    policy = policy_mod.grade_policy(domain(luts={"jenniejoy_soft_v001": {
        "path": "recipes/grade/jenniejoy_soft_v001.cube", "sha256": GOOD}}))
    with pytest.raises(Refused, match="LUT_SHA_MISMATCH"):
        policy_mod.require_lut(policy, bad_lut)


def test_declared_lut_passes_and_returns_name():
    policy = policy_mod.grade_policy(domain())
    info = policy_mod.require_lut(policy, LUT)
    assert info["name"] == "jenniejoy_soft_v001"
    assert info["sha256"] == GOOD


def test_declared_sha_argument_must_agree():
    policy = policy_mod.grade_policy(domain())
    with pytest.raises(Refused, match="LUT_SHA_MISMATCH"):
        policy_mod.require_lut(policy, LUT, declared_sha256="0" * 64)


def test_schema_accepts_real_grade_blocks_and_rejects_bad_sha():
    # post.grade is a schema key now (root added it). Real shipped domains must validate; a malformed sha must not.
    for stem in ("newtecons_live_action", "jenniejoy_cartoon_3d"):
        real = read_json(SKILL_ROOT / "domains" / f"{stem}.json")
        assert validate(real, SCHEMA, label="domain") == [], stem
    bad = copy.deepcopy(read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json"))
    bad["post"]["grade"]["luts"]["jenniejoy_soft_v001"]["sha256"] = "XYZ"
    assert validate(bad, SCHEMA, label="domain"), "malformed LUT sha accepted by the schema"
    extra = copy.deepcopy(read_json(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json"))
    extra["post"]["grade"]["unknown_key"] = True
    assert validate(extra, SCHEMA, label="domain"), "unknown key under post.grade accepted"


def test_engine_names_no_domain():
    source = (SKILL_ROOT / "engine" / "post" / "grade" / "policy.py").read_text(encoding="utf-8")
    for name in ("jenniejoy", "newtecons", "milk", "ep04"):
        assert name not in source.lower()
