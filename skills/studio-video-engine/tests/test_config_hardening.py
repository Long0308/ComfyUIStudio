"""Critic T-E15d fix round: no-loosening hardening, pins verified at load, CLI never tracebacks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from config_fixtures import make_world
from engine.config import loader, rules
from engine.core.errors import Refused, Uncertain
from engine.core.io import canonical_sha256, sha256_file

CARTOON = "jenniejoy_cartoon_3d"
V003 = "seedvr2/v003-7b-int8-tile768-int17-raw21"


def _build(world, **extra):
    return loader.build_config(world.episode_file, skill_root=world.skill_root,
                               machine_path=world.machine_path, **extra)


def _resolve(world):
    return loader.resolve_episode(str(world.episode_file), skill_root=world.skill_root,
                                  machine_path=world.machine_path)


def _overrides(world, **pairs):
    world.edit_episode(lambda d: d["overrides"].update(pairs))


def _expect(world, text: str, **extra) -> None:
    report = _build(world, **extra)
    assert any(text in problem for problem in report.violations), report.violations
    assert report.config is None


def _recipe_path(world) -> Path:
    return world.data(f"recipes/{V003}.json")


# ---- F1: forbidden_node_classes is only ever added to, exact spelling -------------------
def test_tightening_unions_with_the_domain_list_and_keeps_exact_claudenode(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    base = json.loads(world.data(f"domains/{CARTOON}.json").read_text("utf-8"))
    _overrides(world, **{
        "domain.forbidden_node_classes": ["ExtraNode", *base["forbidden_node_classes"]],
        "domain.allowed_custom_nodes": [],
    })
    config = _resolve(world)
    forbidden = config.domain["forbidden_node_classes"]
    assert "ClaudeNode" in forbidden
    assert all(name in forbidden for name in base["forbidden_node_classes"])
    assert forbidden == [*base["forbidden_node_classes"], "ExtraNode"]  # union, domain order first
    assert config.domain["allowed_custom_nodes"] == []
    assert base["allowed_custom_nodes"] == ["comfyui-krea2edit"]  # on-disk domain untouched


def test_forbidden_class_comparison_is_case_sensitive_and_never_replaces() -> None:
    base = {"domain": {"forbidden_node_classes": ["ClaudeNode"]}}
    assert rules.check_overrides({"domain.forbidden_node_classes": ["ClaudeNode", "X"]}, base) == []
    assert rules.check_overrides({"domain.forbidden_node_classes": ["claudenode", "X"]}, base)
    domain = {"forbidden_node_classes": ["ClaudeNode", "A"], "allowed_custom_nodes": ["k"],
              "allowed_recipes": ["f/x", "f/y"]}
    resolved = rules.apply_tightening(domain, {"domain.forbidden_node_classes": ["B", "A"],
                                               "domain.allowed_recipes": ["f/y"]})
    assert resolved["forbidden_node_classes"] == ["ClaudeNode", "A", "B"]  # union, never replace
    assert resolved["allowed_recipes"] == ["f/y"]


def test_probe_10_lowercase_replacement_is_refused_end_to_end(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _overrides(world, **{"domain.forbidden_node_classes": ["claudenode", "bfs_body_swap", "bfs_head_swap"]})
    _expect(world, "override 'domain.forbidden_node_classes'")
    with pytest.raises(loader.ConfigViolation):
        _resolve(world)


def test_a_domain_that_lost_exact_claudenode_is_refused() -> None:
    domain = json.loads((loader.SKILL_ROOT / "domains" / f"{CARTOON}.json").read_text("utf-8"))
    domain["forbidden_node_classes"] = ["claudenode", "bfs_body_swap"]
    assert any("must contain ClaudeNode" in p for p in rules.check_domain(domain, CARTOON))


# ---- F2: ill-typed overrides are violations, never exceptions ---------------------------
@pytest.mark.parametrize("key,value", [
    ("domain.forbidden_node_classes", [1, "ClaudeNode"]),
    ("domain.forbidden_node_classes", "ClaudeNode"),
    ("domain.forbidden_node_classes", None),
    ("domain.forbidden_node_classes", [["ClaudeNode"]]),
    ("domain.allowed_recipes", [["x"]]),
    ("domain.allowed_recipes", [{"a": 1}]),
    ("domain.allowed_recipes", "seedvr2/v003"),
    ("domain.allowed_custom_nodes", [1]),
    ("domain.allowed_custom_nodes", {"comfyui-krea2edit": True}),
])
def test_ill_typed_list_overrides_are_violations_not_crashes(tmp_path: Path, key: str, value) -> None:
    world = make_world(tmp_path)
    _overrides(world, **{key: value})
    report = _build(world)  # must not raise
    assert any(f"override {key!r}" in problem for problem in report.violations), report.violations
    assert report.config is None


def _jjv():
    spec = importlib.util.spec_from_file_location("jjv_cli_hardening", loader.SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [[1, "ClaudeNode"], [["x"]], "ClaudeNode", None])
def test_cli_never_tracebacks_on_ill_typed_overrides(tmp_path: Path, capsys, value) -> None:
    world = make_world(tmp_path)
    _overrides(world, **{"domain.forbidden_node_classes": value})
    code = _jjv().main(["config", "validate", "--episode", str(world.episode_file)])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["ok"] is False and out["violations"]


def test_main_maps_engine_errors_and_unexpected_exceptions(monkeypatch, capsys) -> None:
    cli = _jjv()
    for error, expected in ((Refused("nope"), 1), (Uncertain("unsure"), 2),
                            (RuntimeError("boom"), 2), (AttributeError("x"), 2)):
        def explode(_ref, error=error):
            raise error
        monkeypatch.setattr(cli, "find_episode_file", explode)
        assert cli.main(["config", "validate", "--episode", "x"]) == expected
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False and out["error"]


def test_main_wraps_frozen_verify_and_keeps_its_normal_behaviour(monkeypatch, capsys) -> None:
    cli = _jjv()
    monkeypatch.setattr(cli, "run_verify", lambda **_kw: 0)
    assert cli.main(["frozen", "verify"]) == 0 and capsys.readouterr().out == ""
    monkeypatch.setattr(cli, "run_verify", lambda **_kw: 1)
    assert cli.main(["frozen", "verify"]) == 1

    def explode(**_kw):
        raise KeyError("manifest")
    monkeypatch.setattr(cli, "run_verify", explode)
    assert cli.main(["frozen", "verify"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


# ---- F3: allow-list is re-checked after tightening --------------------------------------
def test_narrowing_allowed_recipes_below_the_selected_recipe_is_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    _overrides(world, **{"domain.allowed_recipes": []})
    _expect(world, f"recipe {V003} is not in domain '{CARTOON}' allowed_recipes []")


def test_untightened_allow_list_failure_is_reported_once(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit(world.data(f"domains/{CARTOON}.json"), lambda d: d.update(allowed_recipes=[]))
    report = _build(world)
    assert sum("allowed_recipes []" in p for p in report.violations) == 1, report.violations


# ---- F4: recipe values are pinned; receipt and pilot graph are verified on disk ---------
@pytest.mark.parametrize("field,value", [("denoise", 0.5), ("sampler_steps", 4), ("sampler_seed", 7)])
def test_recipe_value_edits_are_caught_by_the_canonical_pin(tmp_path: Path, field: str, value) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["graph_recipe"].update({field: value}))
    _expect(world, "graph_recipe canonical sha256")


def test_graph_recipe_is_closed_to_known_keys(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["graph_recipe"].update(extra_knob=1))
    _expect(world, "unexpected property 'extra_knob'")
    world = make_world(tmp_path / "again")
    world.edit(_recipe_path(world), lambda d: d["graph_recipe"].pop("denoise"))
    _expect(world, "missing required property 'denoise'")


def test_qualification_receipt_is_verified_on_disk_at_load(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["pilot"].update(qualification_receipt_sha256="0" * 64))
    _expect(world, "qualification receipt sha256")
    other = make_world(tmp_path / "other")
    _expect(other, "qualification receipt not found", repo_root=tmp_path / "nowhere")


@pytest.mark.parametrize("field,text", [
    ("graph_file_sha256", "pilot graph file sha256"),
    ("graph_recipe_sha256", "pilot graph recipe sha256"),
    ("graph_canonical_sha256", "pilot graph canonical sha256"),
])
def test_pilot_graph_pins_are_verified_on_disk_at_load(tmp_path: Path, field: str, text: str) -> None:
    world = make_world(tmp_path)
    world.edit(_recipe_path(world), lambda d: d["pilot"].update({field: "1" * 64}))
    _expect(world, text)


def test_receipt_that_disagrees_with_the_recipe_is_refused(tmp_path: Path) -> None:
    """A receipt copy whose own sha is pinned but whose content differs (model sha) is caught."""
    world = make_world(tmp_path)
    real = json.loads((loader.REPO_ROOT / json.loads(_recipe_path(world).read_text("utf-8"))["pilot"]
                       ["qualification_receipt"]).read_text("utf-8"))
    real["model"]["sha256"] = "2" * 64
    fake_root = tmp_path / "repo"
    recipe = json.loads(_recipe_path(world).read_text("utf-8"))
    receipt_path = fake_root / recipe["pilot"]["qualification_receipt"]
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(real), encoding="utf-8")
    graph_path = fake_root / recipe["pilot"]["graph_file"]
    graph_path.parent.mkdir(parents=True)
    graph_path.write_bytes((loader.REPO_ROOT / recipe["pilot"]["graph_file"]).read_bytes())
    world.edit(_recipe_path(world), lambda d: d["pilot"].update(
        qualification_receipt_sha256=sha256_file(receipt_path)))
    _expect(world, "qualification receipt model.sha256", repo_root=fake_root)


def test_real_recipe_pins_are_self_consistent() -> None:
    recipe = json.loads((loader.SKILL_ROOT / "recipes" / f"{V003}.json").read_text("utf-8"))
    assert canonical_sha256(recipe["graph_recipe"], mode="ascii") == recipe["pilot"]["graph_recipe_block_sha256"]


# ---- F6: top-level config_sha256 in the CLI output --------------------------------------
def test_cli_output_carries_config_sha256(capsys) -> None:
    code = _jjv().main(["config", "validate", "--episode", "04-milk-and-mom"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and len(out["config_sha256"]) == 64
    assert out["config_sha256"] == out["resolved"]["config_sha256"]


def test_cli_config_sha256_is_null_on_refusal(tmp_path: Path, capsys) -> None:
    world = make_world(tmp_path)
    _overrides(world, **{"domain.forbid_partner_nodes": False})
    code = _jjv().main(["config", "validate", "--episode", str(world.episode_file)])
    assert code == 1 and json.loads(capsys.readouterr().out)["config_sha256"] is None


# ---- F7: neutrality over all of engine/, one named allowlist entry ----------------------
def test_engine_source_is_neutral_except_the_named_frozen_guard() -> None:
    engine = loader.SKILL_ROOT / "engine"
    allow_ep04_word = {"frozen.py"}  # temporary ep04 resume guard; its paths live in FROZEN-EP04.json
    sources = sorted(engine.rglob("*.py"))
    assert len(sources) > 10
    for source in sources:
        text = source.read_text(encoding="utf-8").lower()
        for token in ("jenniejoy", "newtecons", "04-milk-and-mom", ".comfyui-image-submit"):
            assert token not in text, (source, token)
        if source.name not in allow_ep04_word:
            assert "ep04" not in text, source
    assert "ep04" in (engine / "frozen.py").read_text(encoding="utf-8").lower()  # allowlist not stale


# ---- critic round 2: graph_recipe is bound to the pinned pilot graph, not only to its own pin
def test_block_edit_with_rewritten_block_pin_is_still_refused(tmp_path: Path) -> None:
    world = make_world(tmp_path)

    def tamper(data: dict) -> None:
        data["graph_recipe"]["denoise"] = 0.5
        data["pilot"]["graph_recipe_block_sha256"] = canonical_sha256(data["graph_recipe"], mode="ascii")

    world.edit(_recipe_path(world), tamper)
    report = _build(world)
    assert not any("graph_recipe canonical sha256" in v for v in report.violations)  # its own pin now agrees
    assert any("graph_recipe.denoise 0.5 != pilot graph value 1.0" in v for v in report.violations), report.violations
    assert report.config is None


def test_every_block_value_is_bound_to_the_pilot_graph(tmp_path: Path) -> None:
    from engine.seedvr2.recipe import EXTRACT_TABLE
    for index, key in enumerate(sorted(EXTRACT_TABLE)):
        world = make_world(tmp_path / f"k{index}")

        def tamper(data: dict, key=key) -> None:
            current = data["graph_recipe"][key]
            data["graph_recipe"][key] = (current + 1) if isinstance(current, (int, float)) else current + "x"
            data["pilot"]["graph_recipe_block_sha256"] = canonical_sha256(data["graph_recipe"], mode="ascii")

        world.edit(_recipe_path(world), tamper)
        assert any(f"graph_recipe.{key} " in v and "!= pilot graph value" in v
                   for v in _build(world).violations), key


def test_graph_recipe_canonical_mode_is_recorded_and_both_modes_agree_for_this_ascii_graph() -> None:
    from engine.seedvr2.recipe import graph_recipe_sha256
    recipe = json.loads(_recipe_path_real().read_text("utf-8"))
    pilot = recipe["pilot"]
    assert pilot["graph_recipe_sha256_canonical_mode"] == "ascii"
    graph = json.loads((loader.REPO_ROOT / pilot["graph_file"]).read_text("utf-8"))
    ascii_sha = graph_recipe_sha256(graph, mode="ascii")
    assert ascii_sha == graph_recipe_sha256(graph, mode="utf8") == pilot["graph_recipe_sha256"]
    assert json.dumps(graph, ensure_ascii=True) == json.dumps(graph, ensure_ascii=False)  # pure ASCII


def _recipe_path_real() -> Path:
    return loader.SKILL_ROOT / "recipes" / f"{V003}.json"
