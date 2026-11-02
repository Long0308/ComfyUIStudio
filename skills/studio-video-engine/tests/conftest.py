"""Test harness: puts the skill root on sys.path and installs the real-lock tripwire.

The real machine-wide lock path appears ONLY in this file.  Every attempt to
open/stat/remove/rename it, through the common os/pathlib/builtin routes, raises
``RealLockTouched`` BEFORE the OS is asked, and is recorded; the session fails
if any attempt other than the deliberate tripwire self-test was recorded.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

# Derived from the repo root (like engine/config/loader.py) so the tripwire follows the tree when it moves drives.
REAL_LOCK = str(
    SKILL_ROOT.parents[2] / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom" / "technical"
    / ".comfyui-image-submit.lock"
)
ATTEMPTS: list[str] = []


class RealLockTouched(AssertionError):
    """Raised instead of touching the real GPU lock path."""


def _normalise(value: object) -> str | None:
    if isinstance(value, int) or isinstance(value, bool):
        return None
    try:
        text = os.fsdecode(os.fspath(value))  # type: ignore[arg-type]
    except TypeError:
        return None
    return os.path.normcase(os.path.abspath(text))


_REAL = os.path.normcase(os.path.abspath(REAL_LOCK))


def _check(value: object) -> None:
    if _normalise(value) == _REAL:
        ATTEMPTS.append(str(value))
        raise RealLockTouched(f"test touched the real lock path: {value}")


def _audit(event: str, args: tuple) -> None:
    if event == "open" or event.startswith(("os.", "shutil.")):
        for item in args[:2]:
            _check(item)


def _wrap(owner: object, name: str) -> None:
    original = getattr(owner, name)

    def guarded(path, *rest, **kwargs):  # type: ignore[no-untyped-def]
        _check(path)
        return original(path, *rest, **kwargs)

    guarded.__name__ = name
    setattr(owner, name, guarded)


def _install() -> None:
    sys.addaudithook(_audit)
    for name in ("stat", "lstat"):
        _wrap(os, name)
    for name in ("exists", "isfile", "isdir", "islink", "lexists", "getsize"):
        if hasattr(os.path, name):
            _wrap(os.path, name)


_install()


@contextlib.contextmanager
def deliberate_trips():
    """Used only by the tripwire self-test: forgives the attempts made inside."""
    before = len(ATTEMPTS)
    try:
        yield
    finally:
        del ATTEMPTS[before:]


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    if ATTEMPTS:
        print(f"\nSENTINEL VIOLATION: real lock path touched {len(ATTEMPTS)} time(s)")
        session.exitstatus = 1


@pytest.fixture(autouse=True)
def _tests_never_run_the_real_docker_cli(monkeypatch):  # type: ignore[no-untyped-def]
    """``DockerProbe()`` built without a runner (the Executor default) must not reach the real docker CLI."""
    from engine.comfy import docker_probe

    def refuse(command):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("the real docker CLI is never run by tests; inject a FakeDocker")

    monkeypatch.setattr(docker_probe, "default_runner", refuse)
    monkeypatch.setattr(docker_probe.DockerProbe.__init__, "__defaults__", (refuse,))


@pytest.fixture(autouse=True)
def _health_preflight_sees_a_healthy_fake_container(monkeypatch):  # type: ignore[no-untyped-def]
    """T-E39: ``engine.health`` probes docker through its own default runner (which delegates to the refused one
    above).  Under tests it answers from a healthy fixture for whatever container name is asked, so the submit
    paths that now call the preflight stay testable; a runner a test injects or monkeypatches wins.  Never the real CLI."""
    from engine.health import docker_facts, fixture

    monkeypatch.setattr(docker_facts, "default_runner",
                        lambda command: fixture.fixture_runner(fixture.healthy_fixture(command[-1]))(command))



@pytest.fixture
def legacy_ep04_cli(monkeypatch):  # type: ignore[no-untyped-def]
    """The editorial CLIs resolve the live ep04 (now its 3444 f contract); these tests pin the v008-era
    2520 f cut (boundaries.json is still v008-era), so they see the frozen snapshot's episode block."""
    import dataclasses
    import json

    from engine.editorial import cli, presets_cli

    legacy = json.loads((SKILL_ROOT / "tests" / "fixtures" / "ep04-engine" / "episode.json").read_text("utf-8"))
    for module in (cli, presets_cli):
        real = module.resolve_episode_or_uncertain
        monkeypatch.setattr(module, "resolve_episode_or_uncertain",
                            lambda ref, real=real: dataclasses.replace(real(ref), episode=legacy))


@pytest.fixture
def parity_mix_allowed(monkeypatch):  # type: ignore[no-untyped-def]
    """The domain lists no legacy parity mix on purpose (CONFIG-PATCH: production never uses it); the parity
    tests name it with --recipe, so for them the config ``jjv audio mix`` resolves gets it on its allow-list."""
    import copy
    import dataclasses

    from engine.audio import mixcli

    real = mixcli.resolve_episode

    def patched(ref, **kwargs):  # type: ignore[no-untyped-def]
        config = real(ref, **kwargs)
        domain = copy.deepcopy(config.domain)
        domain["audio"]["allowed_recipes"].append("audio/mix-legacy-v004-parity")
        return dataclasses.replace(config, domain=domain)

    monkeypatch.setattr(mixcli, "resolve_episode", patched)


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    """M6 script tests: optional explicit work root; default is pytest's tmp_path."""
    parser.addoption("--script-work-root", type=Path, default=None,
                     help="explicit filesystem-test work root for tests/script; default tmp_path")
    parser.addoption("--brand-kit", default=None,
                     help="M5 brand intro kit for real wrapper tests; default: ep04 kit folder, else skipped")


@pytest.fixture
def script_work(request):  # type: ignore[no-untyped-def]
    from uuid import uuid4

    root = request.config.getoption("--script-work-root")
    if root is None:
        return request.getfixturevalue("tmp_path")
    path = root / uuid4().hex
    path.mkdir(parents=True)
    return path
