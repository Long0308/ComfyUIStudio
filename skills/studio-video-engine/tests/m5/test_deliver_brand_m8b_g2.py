"""M8b-g2: brand/publish blocks of the delivery sidecar, and clear refusals for brand/publish verbs.

Synthetic machine, kit and episode only. Nothing here renders, posts or writes to production.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.deliver.common import load_context
from engine.deliver.init import init_delivery

MISSING_KIT = "MISSING_MACHINE_KEY:brand.kit"
MISSING_BROWSER = "MISSING_MACHINE_KEY:remotion.browser"
MISSING_LIBRARY = "MISSING_MACHINE_KEY:publish.film_library"
MISSING_FILM = "MISSING_EPISODE_KEY:brand.film"
MISSING_ARTIFACTS = "MISSING_EPISODE_KEY:publish.artifacts"
TITLE_PROPS = {"titleEn": "Fixture", "titleVi": "Thu", "subtitle": "Sub", "brandLine": "BRAND",
               "background": "bg.png", "logo": "logo.png"}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _jjv_main():
    """The real bin/jjv.py entry point (exit-code contract), loaded without touching sys.path."""
    spec = importlib.util.spec_from_file_location("jjv_entry", SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


@pytest.fixture
def world(tmp_path):
    """Repo root with a machine.json, a brand kit beside the series, and one episode."""
    repo = tmp_path / "repo"
    series = repo / "production-local" / "JennieJoyKids-Story"
    episode = series / "fixture-ep" / "engine" / "episode.json"
    _write(episode, {"schema": "jjv/episode/v1", "episode_id": "fixture-ep", "film_id": "fixture-ep",
                     "title": "Fixture", "domain": "jenniejoy_cartoon_3d",
                     "contract": {"revision": "rev-1", "fps": 30, "main_frames": 3384,
                                  "end_card_frames": 60, "total_frames": 3444}})
    kit = series / "_brand" / "intro-v001"
    _write(kit / "episodes" / "fixture-ep" / "title-props.json", TITLE_PROPS)
    (kit / "episodes" / "fixture-ep" / "brand-intro-4K-2160p30-v001.mp4").write_bytes(b"x")
    (kit / "episodes" / "fixture-ep" / "title-fixture-ep-4K-2160p30-v001.mp4").write_bytes(b"x")
    packages = repo / "jenniejoy-zoo-film" / "node_modules"
    packages.mkdir(parents=True)
    browser = repo / "chrome-headless-shell.exe"
    browser.write_bytes(b"x")
    library = series / "film-library.json"
    _write(library, {"films": []})
    return {"repo": repo, "episode": episode, "kit": kit, "packages": packages, "browser": browser,
            "library": library}


def _machine(world, *, with_kit=True, with_browser=True, with_library=True):
    machine = {"schema": "jjv/machine/v1", "node_modules": str(world["packages"]),
               "studio": {"url": "http://127.0.0.1:5050"}}
    if with_kit:
        machine["brand"] = {"kit": str(world["kit"])}
    if with_browser:
        machine["remotion"] = {"browser": str(world["browser"])}
    if with_library:
        machine["publish"] = {"film_library": str(world["library"])}
    _write(world["repo"] / "production-local" / "engine" / "machine.json", machine)


def _doc(world, name="delivery.json"):
    return world["episode"].parent / name


def test_init_resolves_brand_and_publish_from_machine_kit_and_episode(world):
    _machine(world)
    target = world["repo"] / "staging" / "delivery.json"
    init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    doc = _read(target)
    brand, publish = doc["brand"], doc["publish"]
    assert brand["kit"] == str(world["kit"])
    assert brand["packages"] == str(world["packages"])
    assert brand["browser"] == str(world["browser"])
    assert brand["workspace"] == str(world["repo"].resolve())
    assert brand["props"] == TITLE_PROPS
    assert brand["intro"] == str(world["kit"] / "episodes" / "fixture-ep" / "brand-intro-4K-2160p30-v001.mp4")
    assert brand["title"] == str(world["kit"] / "episodes" / "fixture-ep" / "title-fixture-ep-4K-2160p30-v001.mp4")
    assert (target.parent / brand["title_out"]).resolve() == (
        world["episode"].parent.parent / "delivery" / "v001" / "brand-title").resolve()
    assert (target.parent / brand["join_out"]).resolve() == (
        world["episode"].parent.parent / "delivery" / "v001" / "brand-join").resolve()
    assert publish["library"] == str(world["library"])
    assert publish["studio_url"] == "http://127.0.0.1:5050"
    assert (target.parent / publish["out"]).resolve() == (
        world["episode"].parent.parent / "delivery" / "v001" / "publish").resolve()


def test_unresolved_values_are_named_markers_never_paths(world):
    _machine(world, with_kit=False, with_browser=False, with_library=False)
    target = world["repo"] / "staging" / "delivery.json"
    result = init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    doc = _read(target)
    assert doc["brand"]["kit"] == {"missing": MISSING_KIT}
    assert doc["brand"]["props"] == {"missing": MISSING_KIT}
    assert doc["brand"]["intro"] == {"missing": MISSING_KIT}
    assert doc["brand"]["title"] == {"missing": MISSING_KIT}
    assert doc["brand"]["browser"] == {"missing": MISSING_BROWSER}
    assert doc["brand"]["film"] == {"missing": MISSING_FILM}
    assert doc["publish"]["library"] == {"missing": MISSING_LIBRARY}
    assert doc["publish"]["artifacts"] == {"missing": MISSING_ARTIFACTS}
    assert doc["publish"]["studio_url"] == "http://127.0.0.1:5050"  # machine key present
    assert doc["brand"]["packages"] == str(world["packages"])  # machine key present
    assert set(result["unresolved"]) == {MISSING_KIT, MISSING_BROWSER, MISSING_FILM, MISSING_LIBRARY,
                                         MISSING_ARTIFACTS}
    assert str(world["kit"]) not in target.read_text(encoding="utf-8")


def test_missing_machine_file_marks_every_machine_value(world):
    target = world["repo"] / "staging" / "delivery.json"
    result = init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    assert {MISSING_KIT, MISSING_BROWSER, MISSING_LIBRARY} <= set(result["unresolved"])
    assert _read(target)["publish"]["studio_url"] == {"missing": "MISSING_MACHINE_KEY:studio.url"}


def test_brand_title_refuses_marker_before_creating_output(world, capsys):
    _machine(world, with_kit=False)
    target = world["repo"] / "staging" / "delivery.json"
    init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    out = (target.parent / _read(target)["brand"]["title_out"]).resolve()
    code = _jjv_main()(["brand", "title", "--episode", str(world["episode"]), "--delivery-config", str(target),
                        "--repo-root", str(world["repo"])])
    assert code == 1
    assert MISSING_KIT in capsys.readouterr().out
    assert not out.exists()


def test_brand_verbs_without_a_block_refuse_with_exit_one_not_keyerror(world, capsys):
    target = world["repo"] / "staging" / "bare.json"
    _write(target, {"schema": "jjv/delivery-config/v1", "episode_id": "fixture-ep",
                    "domain": "jenniejoy_cartoon_3d", "film_2k": {"out": "x"}})
    main = _jjv_main()
    for argv, word in ((["brand", "title", "--out", str(world["repo"] / "o1")], "brand"),
                       (["brand", "join", "--out", str(world["repo"] / "o2")], "brand"),
                       (["publish", "studio", "--dry-run"], "publish")):
        code = main(argv + ["--episode", str(world["episode"]), "--delivery-config", str(target),
                            "--repo-root", str(world["repo"])])
        printed = capsys.readouterr().out
        assert code == 1, argv
        assert f"no {word} block" in printed, printed
        assert "KeyError" not in printed and "Traceback" not in printed
    assert not (world["repo"] / "o1").exists() and not (world["repo"] / "o2").exists()


def test_brand_join_refuses_marker_for_an_unset_input(world, capsys):
    _machine(world, with_kit=False)
    target = world["repo"] / "staging" / "delivery.json"
    init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    code = _jjv_main()(["brand", "join", "--episode", str(world["episode"]), "--delivery-config", str(target),
                        "--repo-root", str(world["repo"]), "--out", str(world["repo"] / "joined")])
    assert code == 1
    assert MISSING_KIT in capsys.readouterr().out
    assert not (world["repo"] / "joined").exists()


def test_publish_dry_run_refuses_missing_library_marker(world, capsys):
    _machine(world, with_library=False)
    target = world["repo"] / "staging" / "delivery.json"
    init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    code = _jjv_main()(["publish", "studio", "--dry-run", "--episode", str(world["episode"]),
                        "--delivery-config", str(target), "--repo-root", str(world["repo"])])
    assert code == 1
    assert MISSING_LIBRARY in capsys.readouterr().out


def test_publish_refuses_missing_artifacts_marker_even_when_library_resolved(world, capsys):
    _machine(world)
    target = world["repo"] / "staging" / "delivery.json"
    init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    code = _jjv_main()(["publish", "studio", "--dry-run", "--episode", str(world["episode"]),
                        "--delivery-config", str(target), "--repo-root", str(world["repo"])])
    assert code == 1
    assert MISSING_ARTIFACTS in capsys.readouterr().out


def test_brand_help_exits_zero(world):
    with pytest.raises(SystemExit) as exc:
        _jjv_main()(["brand", "title", "--episode", "04-milk-and-mom", "--help"])
    assert exc.value.code == 0


def test_loader_accepts_marker_document(world):
    _machine(world, with_kit=False)
    target = world["repo"] / "staging" / "delivery.json"
    init_delivery(world["episode"], delivery_config=target, repo_root=world["repo"])
    ctx = load_context(world["episode"], delivery_config=target, repo_root=world["repo"])
    assert ctx["config"]["brand"]["kit"] == {"missing": MISSING_KIT}


def test_refusal_type_is_refused(world):
    from engine.deliver.common import need
    with pytest.raises(Refused, match="MISSING_MACHINE_KEY:brand.kit"):
        need({"kit": {"missing": MISSING_KIT}}, "kit", "brand")
