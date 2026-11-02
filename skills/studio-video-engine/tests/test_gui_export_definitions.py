"""Concrete H3 autogrow sockets survive GUI conversion (no filesystem fixtures)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_PROPOSED = Path(__file__).resolve().parents[1]
_REPO = next(parent for parent in _PROPOSED.parents if (parent / ".agents/skills/studio-video-engine").is_dir())
sys.path.insert(0, str(_REPO / ".agents/skills/studio-video-engine"))

import engine  # noqa: E402

if str(_PROPOSED / "engine") not in engine.__path__:
    engine.__path__.insert(0, str(_PROPOSED / "engine"))

from engine.audio.gui import api_to_gui  # noqa: E402
from engine.core.errors import Refused  # noqa: E402
from engine.gui_export.convert import convert_gui  # noqa: E402
from engine.gui_export.definitions import normalize_definitions  # noqa: E402


def _world():
    measured = json.loads((Path(__file__).resolve().parent / "fixtures/gui-export-h3-object-info.json").read_text("utf-8"))
    infos = {"LoadImage": {"input": {"required": {"image": [["reference.png"]]}},
                           "output": ["IMAGE"], "output_name": ["IMAGE"]},
             "LoadAudio": {"input": {"required": {"audio": [["line.wav"]]}},
                           "output": ["AUDIO"], "output_name": ["AUDIO"]}, **measured}
    api = {"1": {"class_type": "LoadImage", "inputs": {"image": "reference.png"}},
           "2": {"class_type": "LoadAudio", "inputs": {"audio": "line.wav"}},
           "3": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
               "prompt": "Approved prompt", "width": 864, "height": 480, "length": 124,
               "ref_image_size": "match", "ref_images.ref_image_0": ["1", 0], "ref_audios.ref_audio_0": ["2", 0]}}}
    return api, infos


def test_measured_h3_autogrow_sockets_are_visible_and_linked():
    api, infos = _world()
    normalized = normalize_definitions(api, infos.__getitem__)
    optional = normalized["MiniMaxH3ReferenceToVideo"]["input"]["optional"]
    assert optional["ref_images.ref_image_0"][0] == "IMAGE"
    assert optional["ref_audios.ref_audio_0"][0] == "AUDIO"
    assert "ref_images" not in optional and "ref_audios" not in optional
    gui = api_to_gui(api, normalized.__getitem__, title="measured H3 conversion")
    h3 = next(node for node in gui["nodes"] if node["id"] == 3)
    sockets = {item["name"]: item for item in h3["inputs"]}
    assert sockets["ref_images.ref_image_0"]["link"] is not None
    assert sockets["ref_audios.ref_audio_0"]["link"] is not None
    assert h3["widgets_values_named"]["prompt"] == "Approved prompt"
    assert infos["MiniMaxH3ReferenceToVideo"]["input"]["optional"]["ref_images"][0] == "COMFY_AUTOGROW_V3"


@pytest.mark.parametrize("field,value", [("ref_images.ref_image_9", ["1", 0]),
                                        ("ref_images.ref_image_bad", ["1", 0]),
                                        ("ref_images.ref_image_0", ["2", 0]),
                                        ("ref_audios.ref_audio_0", "line.wav")])
def test_autogrow_refuses_unknown_out_of_range_or_wrongly_typed_bindings(field, value):
    api, infos = _world()
    api["3"]["inputs"][field] = value
    with pytest.raises(Refused, match="GUI_AUTOGROW|GUI_OBJECT_INFO"):
        normalize_definitions(api, infos.__getitem__)


def test_autogrow_refuses_unmeasured_schema_version():
    api, infos = _world()
    infos["MiniMaxH3ReferenceToVideo"]["input"]["optional"]["ref_images"][0] = "COMFY_AUTOGROW_FUTURE"
    with pytest.raises(Refused, match="unsupported definition"):
        normalize_definitions(api, infos.__getitem__)


def test_repeated_class_instances_preserve_union_of_concrete_optional_sockets():
    api, infos = _world()
    api["4"] = copy.deepcopy(api["3"])
    del api["4"]["inputs"]["ref_images.ref_image_0"]
    api["4"]["inputs"]["ref_images.ref_image_2"] = ["1", 0]
    normalized = normalize_definitions(api, infos.__getitem__)
    optional = normalized["MiniMaxH3ReferenceToVideo"]["input"]["optional"]
    assert "ref_images.ref_image_0" in optional and "ref_images.ref_image_2" in optional


def test_converter_preserves_dynamic_links_at_actual_socket_indexes():
    api, infos = _world()
    gui = convert_gui(api, infos.__getitem__, title="measured H3 conversion", extra={})
    nodes = {node["id"]: node for node in gui["nodes"]}
    links = {link[0]: link for link in gui["links"]}
    h3 = nodes[3]
    for index, entry in enumerate(h3["inputs"]):
        if entry.get("link") is None:
            continue
        link = links[entry["link"]]
        assert link[3] == 3 and link[4] == index
        assert [str(link[1]), link[2]] == api["3"]["inputs"][entry["name"]]
    assert {entry["name"] for entry in h3["inputs"] if entry.get("link")} == {
        "ref_images.ref_image_0", "ref_audios.ref_audio_0"}
