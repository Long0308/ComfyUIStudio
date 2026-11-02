"""T-E21: the authoring-only JJClaudeBridge node must never reach a render graph."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config_fixtures import make_world
from engine.comfy import guards
from engine.comfy.client import ComfyClient
from engine.config import loader, rules
from engine.core.errors import Refused
from fake_comfy import FakeComfy

CARTOON = "jenniejoy_cartoon_3d"
LIVE = "newtecons_live_action"
BRIDGE = "JJClaudeBridge"


def _domain(name: str) -> dict:
    return json.loads((loader.SKILL_ROOT / "domains" / f"{name}.json").read_text("utf-8"))


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


@pytest.mark.parametrize("name", [CARTOON, LIVE])
def test_both_domains_forbid_the_bridge_and_never_allowlist_its_pack(name: str) -> None:
    domain = _domain(name)
    assert BRIDGE in domain["forbidden_node_classes"] and "ClaudeNode" in domain["forbidden_node_classes"]
    assert not any("claude_bridge" in pack.lower() for pack in domain["allowed_custom_nodes"])
    assert rules.check_domain(domain, name) == []


@pytest.mark.parametrize("name", [CARTOON, LIVE])
@pytest.mark.parametrize("replacement", [["ClaudeNode"], ["ClaudeNode", "jjclaudebridge"]])
def test_a_domain_that_lost_the_exact_bridge_name_is_refused(name: str, replacement: list[str]) -> None:
    domain = _domain(name)
    domain["forbidden_node_classes"] = replacement
    assert any(f"must contain {BRIDGE}" in problem for problem in rules.check_domain(domain, name))


def test_an_episode_cannot_drop_the_bridge_from_the_forbidden_list() -> None:
    base = {"domain": {"forbidden_node_classes": _domain(CARTOON)["forbidden_node_classes"]}}
    assert rules.check_overrides({"domain.forbidden_node_classes": ["ClaudeNode", "bfs_body_swap", "bfs_head_swap"]}, base)
    assert rules.check_overrides({"domain.forbidden_node_classes": ["ClaudeNode", "jjclaudebridge"]}, base)


def test_episode_override_dropping_the_bridge_is_refused_end_to_end(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["overrides"].update(
        {"domain.forbidden_node_classes": ["ClaudeNode", "bfs_body_swap", "bfs_head_swap"]}))
    report = loader.build_config(world.episode_file, skill_root=world.skill_root,
                                 machine_path=world.machine_path)
    assert any("override 'domain.forbidden_node_classes'" in p for p in report.violations)
    assert report.config is None


@pytest.mark.parametrize("policy", [guards.ClassPolicy(frozenset(), False),
                                    guards.ClassPolicy(frozenset({"other"}), True)])
@pytest.mark.parametrize("spelling", [BRIDGE, "jjclaudebridge", "JJCLAUDEBRIDGE"])
def test_bridge_is_refused_under_any_policy(policy, spelling: str) -> None:
    with pytest.raises(Refused, match="forbidden by policy"):
        guards.check_graph(None, {"1": {"class_type": spelling, "inputs": {}}}, policy)
    assert guards.static_refusals([spelling.lower()], policy)


@pytest.mark.parametrize("name", [CARTOON, LIVE])
def test_domain_policy_refuses_the_bridge(name: str) -> None:
    policy = guards.ClassPolicy.from_domain(_domain(name))
    assert guards.static_refusals([BRIDGE], policy)
    assert guards.static_refusals(["LocalNode"], policy) == []


def test_bridge_is_refused_before_any_network_even_with_a_client(fake) -> None:
    with pytest.raises(Refused):
        guards.check_graph(ComfyClient(fake.url, timeout_seconds=5),
                           {"1": {"class_type": BRIDGE, "inputs": {}}},
                           guards.ClassPolicy(frozenset(), False))
    assert fake.requests == []


def test_bridge_pack_is_also_blocked_by_the_custom_node_allowlist(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    fake.object_info["Bridgey"] = {"python_module": "custom_nodes.jenniejoy_claude_bridge.node",
                                   "category": "JennieJoy/Authoring"}
    policy = guards.ClassPolicy.from_domain(_domain(CARTOON))
    with pytest.raises(Refused, match="jenniejoy_claude_bridge"):
        guards.check_graph(client, {"1": {"class_type": "Bridgey", "inputs": {}}}, policy)
