"""M8b-g: ``jjv deliver init`` writes the delivery sidecar from domain policy + locked episode contract.

Synthetic episode only (no production paths). Real domain files are read from the skill root.
"""
import json
from pathlib import Path

import pytest

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.deliver.cli import main as deliver_main
from engine.deliver.common import load_context
from engine.deliver.init import init_delivery

CONTRACT = {"revision": "fixture-rev-1", "fps": 30, "main_frames": 3384,
            "end_card_frames": 60, "total_frames": 3444}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture
def episode(tmp_path):
    ep = {"schema": "jjv/episode/v1", "episode_id": "fixture-ep", "film_id": "fixture-ep",
          "title": "Fixture", "domain": "jenniejoy_cartoon_3d", "contract": CONTRACT}
    file = tmp_path / "fixture-ep" / "engine" / "episode.json"
    _write(file, ep)
    return file


def test_init_writes_document_from_domain_and_contract(episode, tmp_path):
    result = init_delivery(episode, repo_root=tmp_path)
    target = episode.parent / "delivery.json"
    doc = _read(target)
    assert doc["schema"] == "jjv/delivery-config/v1"
    assert (doc["episode_id"], doc["domain"]) == ("fixture-ep", "jenniejoy_cartoon_3d")
    assert doc["film_2k"] == {"out": "../delivery/v001/2k"}
    assert doc["master"] == {"width": 3840, "height": 2160, "fps": 30, "total_frames": 3444}
    assert doc["contract"] == {"revision": "fixture-rev-1", "main_frames": 3384, "end_card_frames": 60}
    assert doc["engine_tree_sha256"] and doc["engine_tree_files"] > 0
    assert result["sha256"] == sha256_file(target)
    assert "MISSING_MACHINE_KEY:brand.kit" in result["unresolved"]


def test_generated_document_is_accepted_by_the_loader(episode, tmp_path):
    init_delivery(episode, repo_root=tmp_path)
    ctx = load_context(episode, repo_root=tmp_path)
    out = (ctx["base"] / ctx["config"]["film_2k"]["out"]).resolve()
    assert out == (episode.parent.parent / "delivery" / "v001" / "2k").resolve()


def test_refuses_domain_without_film_2k(episode, tmp_path):
    ep = _read(episode)
    ep["domain"] = "newtecons_live_action"
    _write(episode, ep)
    with pytest.raises(Refused, match="film_2k"):
        init_delivery(episode, repo_root=tmp_path)
    assert not (episode.parent / "delivery.json").exists()


def test_refuses_film_2k_not_2560_lanczos(episode, tmp_path):
    domain = _read(SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json")
    domain["delivery"]["film_2k"]["width"] = 1920
    _write(tmp_path / "skill" / "domains" / "jenniejoy_cartoon_3d.json", domain)
    with pytest.raises(Refused, match="lanczos"):
        init_delivery(episode, repo_root=tmp_path, skill_root=tmp_path / "skill")
    assert not (episode.parent / "delivery.json").exists()


def test_refuses_episode_without_contract(episode, tmp_path):
    ep = _read(episode)
    del ep["contract"]
    _write(episode, ep)
    with pytest.raises(Refused, match="contract"):
        init_delivery(episode, repo_root=tmp_path)


def test_write_once_refuses_existing_and_keeps_bytes(episode, tmp_path):
    init_delivery(episode, repo_root=tmp_path)
    target = episode.parent / "delivery.json"
    before = target.read_bytes()
    with pytest.raises(Refused, match="already exists"):
        init_delivery(episode, repo_root=tmp_path)
    assert target.read_bytes() == before


def test_explicit_target_gets_paths_relative_to_its_own_directory(episode, tmp_path):
    target = tmp_path / "staging" / "delivery.json"
    init_delivery(episode, delivery_config=target, repo_root=tmp_path)
    doc = _read(target)
    resolved = (target.parent / doc["film_2k"]["out"]).resolve()
    assert resolved == (episode.parent.parent / "delivery" / "v001" / "2k").resolve()


def test_cli_dispatch_writes_and_film_2k_still_requires_master(episode, tmp_path, capsys):
    target = tmp_path / "cli" / "delivery.json"
    code = deliver_main(["deliver", "init", "--episode", str(episode),
                         "--delivery-config", str(target), "--repo-root", str(tmp_path)])
    assert code == 0 and target.is_file()
    with pytest.raises(SystemExit):
        deliver_main(["deliver", "film-2k", "--episode", str(episode)])


def test_cli_refusal_exits_1_and_writes_nothing(episode, tmp_path, capsys):
    ep = _read(episode)
    ep["domain"] = "newtecons_live_action"
    _write(episode, ep)
    target = tmp_path / "cli" / "delivery.json"
    code = deliver_main(["deliver", "init", "--episode", str(episode),
                         "--delivery-config", str(target), "--repo-root", str(tmp_path)])
    assert code == 1
    assert "film_2k" in capsys.readouterr().out
    assert not target.exists()
