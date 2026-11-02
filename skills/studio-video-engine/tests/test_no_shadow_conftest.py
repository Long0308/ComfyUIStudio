"""Guard: only ONE conftest.py may exist under tests/, and none under engine/.

Why: pytest imports every conftest.py under the name ``conftest``.  A second ``tests/<sub>/conftest.py`` shadows the
top ``tests/conftest.py``: tests that ``import conftest`` read the wrong module, and options/fixtures registered only
in the sub-conftest are invisible to the rest of the suite.  Incident and fix: see
error-db/second-conftest-shadows-top-conftest.json (in the production-local error DB).  Shared options/fixtures go
in tests/conftest.py; helpers go in a uniquely named module (e.g. tests/script/_m6_helpers.py).
"""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
TOP_CONFTEST = "tests/conftest.py"
ERROR_DB = "error-db/second-conftest-shadows-top-conftest.json"


def find_conftests(root: Path) -> list[str]:
    """Relative POSIX paths of every conftest.py under ``root/tests`` and ``root/engine``, sorted."""
    found: list[str] = []
    for sub in ("tests", "engine"):
        base = Path(root) / sub
        if base.is_dir():
            found.extend(p.relative_to(root).as_posix() for p in base.rglob("conftest.py") if p.is_file())
    return sorted(found)


def shadow_problems(root: Path) -> list[str]:
    """Every conftest.py that is not the single allowed ``tests/conftest.py``; also flags a missing top conftest."""
    found = find_conftests(root)
    problems = [path for path in found if path != TOP_CONFTEST]
    if TOP_CONFTEST not in found:
        problems.append(f"{TOP_CONFTEST} (missing)")
    return problems


def _message(problems: list[str]) -> str:
    return (f"second conftest.py would shadow tests/conftest.py: {problems}. "
            f"Move helpers to a uniquely named module and shared options/fixtures into tests/conftest.py. "
            f"See {ERROR_DB}")


def test_the_real_tree_has_only_the_top_conftest() -> None:
    problems = shadow_problems(SKILL_ROOT)
    assert problems == [], _message(problems)


def test_the_real_tree_lists_exactly_the_top_conftest_under_tests() -> None:
    under_tests = [p for p in find_conftests(SKILL_ROOT) if p.startswith("tests/")]
    assert under_tests == [TOP_CONFTEST], _message(under_tests)


def test_helper_catches_a_sub_conftest_in_a_synthetic_tree(tmp_path) -> None:
    # A synthetic listing in tmp_path: the real tree is never written to.
    (tmp_path / "tests" / "h3").mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text("# top\n", encoding="utf-8")
    (tmp_path / "tests" / "h3" / "conftest.py").write_text("# the incident shape\n", encoding="utf-8")
    problems = shadow_problems(tmp_path)
    assert problems == ["tests/h3/conftest.py"], _message(problems)
    assert ERROR_DB in _message(problems)


def test_helper_catches_a_conftest_under_engine_and_a_missing_top(tmp_path) -> None:
    (tmp_path / "engine" / "core").mkdir(parents=True)
    (tmp_path / "engine" / "core" / "conftest.py").write_text("# stray\n", encoding="utf-8")
    problems = shadow_problems(tmp_path)
    assert problems == ["engine/core/conftest.py", f"{TOP_CONFTEST} (missing)"], _message(problems)


def test_helper_passes_on_a_clean_synthetic_tree(tmp_path) -> None:
    (tmp_path / "tests" / "script").mkdir(parents=True)
    (tmp_path / "tests" / "conftest.py").write_text("# top\n", encoding="utf-8")
    (tmp_path / "tests" / "script" / "_m6_helpers.py").write_text("# helpers\n", encoding="utf-8")
    assert shadow_problems(tmp_path) == []
