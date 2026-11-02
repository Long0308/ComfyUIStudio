"""Isolated pytest harness; fresh run directory avoids deleting previous evidence."""
import contextlib
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent


def run(label, candidate=False, regression_only=False):
    work = BASE / label
    work.mkdir(exist_ok=False)
    (work / ".pytest_work_tmp").mkdir()
    os.chdir(work)
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    # Python 3.14 Windows mode=0700 gives this sandbox an unreadable directory.
    # Ordinary inherited directory ACLs are sufficient for synthetic test data.
    mkdir = os.mkdir
    def inherited_mkdir(path, mode=0o777, *, dir_fd=None):
        return mkdir(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)
    os.mkdir = inherited_mkdir
    if candidate:
        import engine.images
        for name in ("codex_queue", "codex", "local", "prompt_route"):
            spec = importlib.util.spec_from_file_location("engine.images." + name, BASE / "candidate" / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            setattr(engine.images, name, module)
            spec.loader.exec_module(module)
            module.__file__ = str(ROOT / "engine" / "images" / (name + ".py"))
    import pytest
    tests = [ROOT / "tests" / "test_images_codex_imgrt.py"] if regression_only else [
        ROOT / "tests" / "test_images_prompt_route.py", *sorted((ROOT / "tests").glob("test_images_codex*.py"))]
    args = [*[str(p) for p in tests], "-q", "--tb=short", "-p", "no:cacheprovider",
            "--basetemp", ".pytest_work_tmp/IMGRT-FIX"]
    with (BASE / (label + ".txt")).open("w", encoding="utf-8") as output:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            print("python -I -B -c pytest.main", args, "candidate=", candidate)
            code = pytest.main(args)
            print("EXIT_CODE", int(code))
    print((BASE / (label + ".txt")).read_text("utf-8"))
    return int(code)
