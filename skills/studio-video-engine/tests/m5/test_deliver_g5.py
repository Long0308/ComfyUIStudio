"""M8b-g5: canonical sidecar placement, write-target containment, optional-value refusal, kit file names.

Synthetic repo, episode, kit and library only. Nothing here renders, posts or writes to production.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.deliver.brand import title
from engine.deliver.common import load_context
from engine.deliver.init import init_delivery
from engine.publish.studio import publish_studio

CONTRACT = {"revision": "rev-g5", "fps": 30, "main_frames": 3384,
            "end_card_frames": 60, "total_frames": 3444}
TITLE_PROPS = {"titleEn": "Fixture", "titleVi": "Thu", "subtitle": "Sub", "brandLine": "BRAND",
               "background": "bg.png", "logo": "logo.png"}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture
def repo(tmp_path):
    """Repo root whose production-local holds one series with one episode (an episode tree)."""
    root = tmp_path / "repo"
    episode = root / "production-local" / "Series" / "fixture-ep" / "engine" / "episode.json"
    _write(episode, {"schema": "jjv/episode/v1", "episode_id": "fixture-ep", "film_id": "fixture-ep",
                     "title": "Fixture", "domain": "jenniejoy_cartoon_3d", "contract": CONTRACT})
    return root


@pytest.fixture
def episode(repo):
    return repo / "production-local" / "Series" / "fixture-ep" / "engine" / "episode.json"


def _episode_root(episode):
    return episode.parent.parent


def _canonical(episode):
    return episode.parent / "delivery.json"


# ---- 1. canonical default, explicit placement, and the bypass ------------------------------------

def test_default_target_is_canonical_and_marked(episode, repo):
    result = init_delivery(episode, repo_root=repo)
    doc = _read(_canonical(episode))
    assert doc["canonical"] is True
    assert result["canonical"] is True


def test_explicit_path_outside_episode_trees_is_noncanonical(episode, repo):
    target = repo / "staging" / "delivery.json"
    result = init_delivery(episode, delivery_config=target, repo_root=repo)
    assert _read(target)["canonical"] is False
    assert result["canonical"] is False
    assert not _canonical(episode).exists()


def test_canonical_looking_sidecar_inside_an_episode_tree_is_refused(episode, repo):
    target = _episode_root(episode) / "delivery" / "v001" / "other" / "delivery.json"
    with pytest.raises(Refused, match="episode tree"):
        init_delivery(episode, delivery_config=target, repo_root=repo)
    assert not target.exists()


def test_alternate_path_cannot_bypass_existing_canonical_sidecar(episode, repo):
    init_delivery(episode, repo_root=repo)
    before = _canonical(episode).read_bytes()
    # The bypass from the critic report: an alternate sidecar inside the episode tree.
    alt = _episode_root(episode) / "engine" / "alt" / "delivery.json"
    with pytest.raises(Refused, match="episode tree"):
        init_delivery(episode, delivery_config=alt, repo_root=repo)
    assert _canonical(episode).read_bytes() == before
    assert not alt.exists()


def test_write_once_still_refuses_existing_canonical(episode, repo):
    init_delivery(episode, repo_root=repo)
    with pytest.raises(Refused, match="already exists"):
        init_delivery(episode, repo_root=repo)


def test_explicit_noncanonical_sidecar_is_refused_by_default_consumers(episode, repo):
    staging = repo / "staging" / "delivery.json"
    init_delivery(episode, delivery_config=staging, repo_root=repo)
    # A copy of the staging document placed at the canonical name must still be refused by default.
    _canonical(episode).write_bytes(staging.read_bytes())
    with pytest.raises(Refused, match="not canonical"):
        load_context(episode, repo_root=repo)
    ctx = load_context(episode, delivery_config=_canonical(episode), repo_root=repo)
    assert ctx["config"]["canonical"] is False


def test_loader_default_accepts_canonical_document(episode, repo):
    init_delivery(episode, repo_root=repo)
    assert load_context(episode, repo_root=repo)["config"]["canonical"] is True


# ---- 2. write targets are contained and never reached through reparse points ----------------

def _sidecar(path, publish_library, *, extra=None):
    doc = {"schema": "jjv/delivery-config/v1", "episode_id": "fixture-ep", "domain": "jenniejoy_cartoon_3d",
           "canonical": False, "film_2k": {"out": "x"},
           "publish": {"library": publish_library, "studio_url": "http://127.0.0.1:5050",
                       "artifacts": {"missing": "MISSING_EPISODE_KEY:publish.artifacts"},
                       "out": "publish"}}
    doc.update(extra or {})
    _write(path, doc)


def test_publish_library_outside_production_local_is_refused(episode, repo):
    target = repo / "staging" / "delivery.json"
    outside = repo / "elsewhere" / "film-library.json"
    _sidecar(target, str(outside))
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    with pytest.raises(Refused, match="publish.film_library"):
        publish_studio(ctx, publish=False)


def test_publish_library_absolute_path_outside_repo_is_refused(episode, repo, tmp_path):
    target = repo / "staging" / "delivery.json"
    _sidecar(target, str(tmp_path / "anywhere" / "film-library.json"))
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    with pytest.raises(Refused, match="publish.film_library"):
        publish_studio(ctx, publish=False)


def test_publish_library_dotdot_traversal_out_of_production_local_is_refused(episode, repo):
    target = repo / "staging" / "delivery.json"
    traversal = str(repo / "production-local" / "Series" / ".." / ".." / "film-library.json")
    _sidecar(target, traversal)
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    with pytest.raises(Refused, match="publish.film_library"):
        publish_studio(ctx, publish=False)


def test_publish_library_through_a_junction_is_refused(episode, repo, tmp_path):
    link = repo / "production-local" / "Linked"
    real = tmp_path / "real-library-dir"
    real.mkdir()
    (real / "film-library.json").write_text('{"films": []}', encoding="utf-8")
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)],
                          capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(f"cannot create a junction here: {made.stderr or made.stdout}")
    target = repo / "staging" / "delivery.json"
    _sidecar(target, str(link / "film-library.json"))
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    try:
        with pytest.raises(Refused, match="symlink or junction"):
            publish_studio(ctx, publish=False)
    finally:
        os.rmdir(link)  # removes the junction only, never the target directory


def test_publish_library_inside_production_local_is_accepted(episode, repo):
    target = repo / "staging" / "delivery.json"
    library = repo / "production-local" / "Series" / "film-library.json"
    _write(library, {"films": []})
    _sidecar(target, str(library))
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    # The sidecar's artifacts are still a marker, so the dry run stops AFTER the library passed containment.
    with pytest.raises(Refused, match="MISSING_EPISODE_KEY:publish.artifacts"):
        publish_studio(ctx, publish=False)


# ---- 3. resolve every value (optional ones too) before the output directory exists ----------

def _brand_sidecar(target, repo, chime):
    brand = {"kit": str(repo / "kit"), "workspace": str(repo), "packages": str(repo / "nm"),
             "browser": str(repo / "chrome.exe"), "props": TITLE_PROPS,
             "intro": str(repo / "intro.mp4"), "title": str(repo / "title.mp4"),
             "film": {"missing": "MISSING_EPISODE_KEY:brand.film"},
             "title_out": "brand-title", "join_out": "brand-join"}
    if chime is not None:
        brand["chime"] = chime
    _write(target, {"schema": "jjv/delivery-config/v1", "episode_id": "fixture-ep",
                    "domain": "jenniejoy_cartoon_3d", "canonical": False, "film_2k": {"out": "x"},
                    "brand": brand})


def test_brand_title_marker_in_optional_chime_is_named_refusal_before_output(episode, repo):
    target = repo / "staging" / "delivery.json"
    _brand_sidecar(target, repo, {"missing": "MISSING_MACHINE_KEY:brand.chime"})
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    out = repo / "out-title"
    with pytest.raises(Refused, match="MISSING_MACHINE_KEY:brand.chime"):
        title(ctx, out)
    assert not out.exists()


def test_brand_title_absent_chime_is_not_a_refusal(episode, repo):
    target = repo / "staging" / "delivery.json"
    _brand_sidecar(target, repo, None)
    ctx = load_context(episode, delivery_config=target, repo_root=repo)
    out = repo / "out-title"
    # An absent optional value resolves to its default: no chime refusal. The run then stops later, on the
    # synthetic kit having no render tools, which is not a delivery-value refusal.
    with pytest.raises(Exception) as exc:
        title(ctx, out)
    assert "MISSING_" not in str(exc.value) and "brand.chime" not in str(exc.value)


# ---- 4. brand-kit file names are data, not engine literals ---------------------------------------

RECIPE = SKILL_ROOT / "recipes" / "deliver" / "brand-kit.json"


def test_brand_kit_names_live_in_a_recipe_not_in_engine_code():
    assert RECIPE.is_file()
    recipe = _read(RECIPE)
    assert recipe["schema"] == "jjv/deliver-brand-kit/v1"
    source = (SKILL_ROOT / "engine" / "deliver" / "init.py").read_text(encoding="utf-8")
    assert "brand-intro-4K" not in source and "title-props.json" not in source
    assert "2160p30" not in source


def test_init_resolves_kit_files_named_by_the_recipe(episode, repo):
    recipe = _read(RECIPE)
    kit = repo / "production-local" / "Series" / "_brand" / "intro-v001"
    folder = kit / "episodes" / "fixture-ep"
    _write(folder / recipe["props"], TITLE_PROPS)
    (folder / recipe["intro"]).parent.mkdir(parents=True, exist_ok=True)
    (folder / recipe["intro"]).write_bytes(b"x")
    (folder / recipe["title"].format(slug="fixture-ep")).write_bytes(b"x")
    _write(repo / "production-local" / "engine" / "machine.json",
           {"schema": "jjv/machine/v1", "brand": {"kit": str(kit)}})
    target = repo / "staging" / "delivery.json"
    init_delivery(episode, delivery_config=target, repo_root=repo)
    brand = _read(target)["brand"]
    assert brand["props"] == TITLE_PROPS
    assert brand["intro"] == str(folder / recipe["intro"])
    assert brand["title"] == str(folder / recipe["title"].format(slug="fixture-ep"))
