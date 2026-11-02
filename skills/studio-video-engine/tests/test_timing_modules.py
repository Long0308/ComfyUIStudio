"""Static rules for ``engine/timing``: size, neutrality, CPU-only, no HTTP, one subprocess site, recipe-only numbers."""

from __future__ import annotations

import ast
import json

from engine.config.loader import SKILL_ROOT
from engine.timing import firstword, onset, q1, recipe
from test_timing_support import RECIPE

TIMING = SKILL_ROOT / "engine" / "timing"
SOURCES = sorted(TIMING.glob("*.py"))


def test_modules_stay_small_and_neutral() -> None:
    assert len(SOURCES) >= 12
    for source in SOURCES:
        text = source.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 400, source
        for token in ("jenniejoy", "newtecons", "04-milk-and-mom", "ep04", "milk", "d:\\"):
            assert token not in text.lower(), (source, token)
    for test in sorted((SKILL_ROOT / "tests").glob("test_timing_*.py")):
        assert len(test.read_text(encoding="utf-8").splitlines()) <= 400, test


def test_no_gpu_no_network_and_one_subprocess_site() -> None:
    callers = []
    for source in SOURCES:
        text = source.read_text(encoding="utf-8")
        assert not any(word in text for word in ("urllib", "requests", "socket", "http.client", "comfy", "torch.cuda"))
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"run", "Popen", "check_output"} \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                callers.append(source.name)
    assert callers == ["recognise.py"]
    worker = (TIMING / "whisper_worker.py").read_text(encoding="utf-8")
    assert 'CUDA_VISIBLE_DEVICES"] = ""' in worker and "engine" not in {  # the worker imports nothing from the engine
        n.module.split(".")[0] for n in ast.walk(ast.parse(worker)) if isinstance(n, ast.ImportFrom) and n.module}


def test_rule_modules_hold_no_threshold_constants() -> None:
    """Every threshold comes from the recipe: no module-level numeric constant in the rule code."""
    for module in (onset, firstword, q1):
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        numeric = [t.id for node in tree.body if isinstance(node, ast.Assign) for t in node.targets
                   if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float))]
        assert numeric == [], (module.__name__, numeric)


def test_recipe_is_schema_valid_domain_bound_and_matches_the_hand_run_tools() -> None:
    data = json.loads((SKILL_ROOT / "recipes" / "timing" / "words-onset-v001.json").read_text(encoding="utf-8"))
    assert recipe.load_timing_recipe(data["recipe_id"]).sha256 == RECIPE.sha256
    allw, first, q = data["all_words"], data["first_word"], data["q1"]
    assert (allw["floor_dbfs"], allw["voiced_dbfs"], allw["edge_dbfs"], allw["sustain_s"], allw["end_margin_frames"]) == (-50.0, -35.0, -45.0, 0.06, 2)
    assert (allw["pause"]["near_min_s"], allw["pause"]["far_min_s"], allw["pause"]["max_shift_s"]) == (0.05, 0.10, 0.60)
    assert (first["threshold_dbfs"], first["merge_gap_s"], first["sustained_run_s"], first["isolated_gap_s"], first["move_min_s"]) == (-40.0, 0.03, 0.15, 0.5, 0.05)
    assert (q["silence_dbfs"], q["edge_dbfs"], q["max_early_frames"], q["max_late_frames"], q["control_shift_frames"]) == (-55.0, -45.0, 0, 2, 5)
