"""routes-v002 (user 2026-10-30): NEWTECONS images go HYBRID = comfyui-local + codex-exec + codex-adopt, then compare.

OpenRouter stays refused for NEWTECONS. The cartoon domain keeps its v001 table byte for byte. No network, no GPU,
no real ``codex exec`` (FAKE binary / dry-run only).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from engine.core.errors import Refused
from engine.layout import context
from engine.layout.context import domain_policy, require_provider
from images_fixtures import CARTOON, LIVE, World, make_png, run_images
from test_images_codex import Setup as CodexSetup

V001_SHA = "6c32dac8a098bb3dc1805b672dfdf28056c527456e5fc3ea9904807dba185fc4"  # v001 stays byte-identical


def _base(setup: CodexSetup) -> list[str]:
    return ["--episode", str(setup.world.root), "--out", str(setup.out), "--machine", str(setup.world.machine_path),
            "--shot", "S01_A"]


def test_a_newtecons_codex_exec_is_accepted_in_dry_run(tmp_path):
    setup = CodexSetup(tmp_path, domain=LIVE)
    result = setup.run(dry_run=True)
    assert result["dry_run"] is True and result["submitted"] is False
    assert not setup.calls("acct1") and not setup.state.exists()


def test_a2_newtecons_codex_exec_through_the_cli_dry_run(tmp_path):
    setup = CodexSetup(tmp_path, domain=LIVE)
    setup.world.machine["images"] = {"codex_accounts": [
        {"label": a.label, "codex_home": str(a.codex_home)} for a in setup.accounts]}
    setup.world.write_machine()
    code, out = run_images(["submit", *_base(setup), "--provider", "codex-exec", "--prompt-file", str(setup.prompt),
                            "--dry-run"])
    assert code == 0 and out["dry_run"] is True, out


def test_b_newtecons_codex_adopt_is_accepted(tmp_path):
    setup = CodexSetup(tmp_path, domain=LIVE)
    png = make_png(tmp_path / "gpt.png", (10, 90, 40), (1672, 941))
    home = setup.accounts[0].codex_home  # N25: NEWTECONS adopt must prove its source
    setup.world.machine["images"] = {"codex_accounts": [{"label": "acct1", "codex_home": str(home)}]}
    setup.world.write_machine()
    (home / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a").mkdir(parents=True)
    (home / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "exec-1.png").write_bytes(png.read_bytes())  # N25b: the source must exist, same bytes
    from images_fixtures import write_rollout
    write_rollout(home, "019a3c1e-0000-7000-8000-00000000000a", "exec-1.png")  # N25c
    code, out = run_images(["adopt", *_base(setup), "--file", str(png), "--route", "codex-builtin",
                            "--prompt-file", str(setup.prompt), "--refs-from-plan", "--requested-model", "gpt-image-2",
                            "--source-path", str(home / "generated_images" / "019a3c1e-0000-7000-8000-00000000000a" / "exec-1.png")])
    assert code == 0 and out["route"] == "codex-builtin", out


def test_c_newtecons_openrouter_is_still_refused_before_any_send(tmp_path):
    setup = CodexSetup(tmp_path, domain=LIVE)
    with pytest.raises(Refused, match="not allowed for domain 'newtecons_live_action'"):
        require_provider(setup.world.ctx(), "openrouter")
    code, out = run_images(["submit", *_base(setup), "--provider", "openrouter", "--spend-ok",
                            "--prompt-file", str(setup.prompt)])
    assert code == 1 and "not allowed for domain" in out["error"] and "openrouter" in out["error"], out


def test_d_unknown_provider_is_refused_for_every_domain(tmp_path):
    for domain in (LIVE, CARTOON):
        ctx = World(tmp_path / domain, domain=domain).ctx()
        with pytest.raises(Refused, match="not allowed for domain"):
            require_provider(ctx, "midjourney")


def test_e_cartoon_keeps_the_v001_behaviour(tmp_path):
    ctx = World(tmp_path, domain=CARTOON).ctx()
    v001 = json.loads((context.RECIPE_DIR / "routes-v001.json").read_text("utf-8"))["domains"][CARTOON]
    policy = domain_policy(ctx)
    for key in ("allowed_providers", "preferred_order", "brief_status", "cast_ref_in_brief"):
        assert policy[key] == v001[key], key
    assert set(policy["allowed_providers"]) == {"comfyui-local", "openrouter", "codex-adopt", "codex-exec"}


def test_newtecons_policy_row_is_hybrid_and_local_stays_the_default(tmp_path):
    policy = domain_policy(World(tmp_path, domain=LIVE).ctx())
    assert set(policy["allowed_providers"]) == {"comfyui-local", "codex-exec", "codex-adopt"}
    assert "openrouter" not in policy["allowed_providers"]
    assert context.default_provider(World(tmp_path / "x", domain=LIVE).ctx()) == "comfyui-local"


def test_engine_loads_v002_and_v001_is_left_alone():
    recipe, sha = context.load_recipe("routes-v002", "jjv/images-routes/v1")
    assert recipe["id"] == "routes-v002" and sha
    assert context.ROUTES_RECIPE == "routes-v002"
    assert hashlib.sha256((context.RECIPE_DIR / "routes-v001.json").read_bytes()).hexdigest() == V001_SHA
