"""SaveVideo dynamic widgets use the selected live object_info branch."""
import copy
import json
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.gui_export.convert import convert_gui


def world():
    info = json.loads((Path(__file__).parent / "fixtures/gui-export-savevideo-object-info.json").read_text(encoding="utf8"))
    info["VideoSource"] = {"input": {"required": {}}, "output": ["VIDEO"], "output_name": ["VIDEO"]}
    api = {"1": {"class_type": "VideoSource", "inputs": {}},
           "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0], "filename_prefix": "shot/S02_A", "format": "mp4", "format.codec": "h264"}}}
    return api, info


def test_savevideo_dynamic_codec_widget_order():
    api, info = world()
    before = copy.deepcopy(api)
    gui = convert_gui(api, info.__getitem__, title="S02_A", extra={})
    node = next(n for n in gui["nodes"] if n["id"] == 2)
    assert node["widgets_values"] == ["shot/S02_A", "mp4", "h264", "auto"]
    assert node["widgets_values_named"]["format.codec"] == "h264"
    assert node["widgets_values_named"]["format.codec.encoding"] == "auto"
    assert api == before
    assert gui["links"][0][3:] == [2, 0, "VIDEO"]


def test_savevideo_refuses_unknown_input():
    api, info = world()
    api["2"]["inputs"]["format.bogus"] = "x"
    with pytest.raises(Refused, match="undeclared API inputs"):
        convert_gui(api, info.__getitem__, title="S02_A", extra={})


def test_savevideo_refuses_child_not_in_selected_branch():
    api, info = world()
    api["2"]["inputs"].update({"format": "webm", "format.codec": "h264"})
    with pytest.raises(Refused, match="invalid selection"):
        convert_gui(api, info.__getitem__, title="S02_A", extra={})


def test_savevideo_deep_branch_and_per_instance_order():
    api, info = world()
    api["3"] = copy.deepcopy(api["2"])
    api["3"]["inputs"].update({"format.codec.encoding": "re-encode", "format.codec.encoding.crf": 20.0})
    gui = convert_gui(api, info.__getitem__, title="S02_A", extra={})
    nodes = {n["id"]: n for n in gui["nodes"]}
    assert nodes[2]["widgets_values"] == ["shot/S02_A", "mp4", "h264", "auto"]
    assert nodes[3]["widgets_values"] == ["shot/S02_A", "mp4", "h264", "re-encode", 20.0]
