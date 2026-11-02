"""api_to_gui: a link's target slot is the index of its entry in ``node.inputs`` (widget entries count)."""
from engine.audio.gui import api_to_gui

INFOS = {
    "CLIPLoader": {"input": {"required": {"clip_name": [["a.safetensors"]], "type": [["stable_diffusion"]]}},
                   "input_order": {"required": ["clip_name", "type"]},
                   "output": ["CLIP"], "output_name": ["CLIP"]},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}},
                       "input_order": {"required": ["text", "clip"]},
                       "output": ["CONDITIONING"], "output_name": ["CONDITIONING"]},
}


def test_linked_clip_targets_its_entry_index_not_a_socket_counter():
    api = {"1": {"class_type": "CLIPLoader", "inputs": {"clip_name": "a.safetensors", "type": "stable_diffusion"}},
           "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "hello", "clip": ["1", 0]}}}
    gui = api_to_gui(api, lambda name: INFOS[name], title="t")
    node = next(n for n in gui["nodes"] if n["id"] == 2)
    link = gui["links"][0]
    assert [e["name"] for e in node["inputs"]] == ["text", "clip"]
    assert link[4] == 1 and node["inputs"][link[4]]["name"] == "clip"
    assert node["inputs"][1]["link"] == link[0]
