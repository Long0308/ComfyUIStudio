"""Build staged examples from the historical S02_A GUI graph, without touching production."""
import csv
import hashlib
import json
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[5]
SOURCE = WORKSPACE / "production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/workflows/H3_MOTION/S02_A-h3-f52be0d7015d-v001.workflow.json"
source = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
old = {str(node["id"]): node for node in source["nodes"]}
examples = PACK / "examples"
examples.mkdir(exist_ok=True)
(examples / "assets").mkdir(exist_ok=True)

episode = "Newtecons-TienDo-KichTinh-30s"
base = episode + "/panel-example/"
panel = dict(domain="newtecons_live_action", script_path=base + "script.txt",
             shotlist_path=base + "shots.csv", asset_folder=base + "assets",
             run_mode="One shot", scene="SCENE_02", shot="S02_A", aspect="16:9",
             generation_size="704p", output_resolution="1440p", style="Live-action photoreal",
             no_image_mode="I2V", min_duration=4.0)
prompt = old["19"]["widgets_values"][0]
(examples / "script.txt").write_text("S02_A integration example. Replace with the selected screenplay.\n\n" + prompt + "\n", encoding="utf-8")
with (examples / "shots.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["scene", "shot", "duration", "prompt", "refs", "guide"])
    writer.writerow(["SCENE_02", "S02_A", 107 / 24, prompt,
                     json.dumps(["S02_A_ref_0.png", "S02_A_ref_1.png", "S02_A_ref_2.png"]),
                     "S02_A_guide.png"])
(examples / "project-panel.json").write_text(json.dumps({"domain": "newtecons_live_action",
    "shotlists": ["panel-example/shots.csv"]}, indent=2), encoding="utf-8")
(examples / "assets/README.md").write_text(
    "Put approved source images here, or edit refs/guide in shots.csv.\n"
    "Required placeholders: S02_A_ref_0.png, S02_A_ref_1.png, S02_A_ref_2.png, S02_A_guide.png.\n"
    "No media are included, generated, copied or approved by this example.\n", encoding="utf-8")

graph = {}
def node(id, kind, **inputs):
    graph[str(id)] = {"class_type": kind, "inputs": inputs}

def values(id):
    return old[str(id)]["widgets_values"]

node(100, "NewteconsProjectPanel", **panel)
node(1, "UNETLoader", unet_name=values(1)[0], weight_dtype=values(1)[1])
node(2, "CLIPLoader", clip_name=values(2)[0], type=values(2)[1], device=values(2)[2])
node(3, "VAELoader", vae_name=values(3)[0])
node(4, "VAELoader", vae_name=values(4)[0])
node(6, "NewteconsPanelH3", clip=["2", 0], vae=["3", 0], prompt=["100", 0],
     ref_image_paths_json=["100", 1], width=["100", 3], height=["100", 4], length=["100", 6])
node(7, "LoadAudio", audio=values(7)[0])  # Existing fixed S02 WAV, untouched.
node(8, "NewteconsPanelReference", ref_image_paths_json=["100", 10], index=0)
node(9, "MiniMaxH3AddGuide", positive=["6", 0], latent=["6", 1], vae=["3", 0],
     audio_vae=["4", 0], image=["8", 0], audio=["7", 0], frame_idx=0)
node(20, "LoraLoaderModelOnly", model=["1", 0], lora_name=values(20)[0], strength_model=values(20)[1])
node(21, "MiniMaxH3SigmaShift", model=["20", 0], shift_video=values(21)[0], shift_audio=values(21)[1])
node(10, "BasicGuider", model=["21", 0], conditioning=["9", 0])
node(11, "RandomNoise", noise_seed=values(11)[0])
node(12, "KSamplerSelect", sampler_name=values(12)[0])
node(13, "BasicScheduler", model=["21", 0], scheduler=values(13)[0], steps=values(13)[1], denoise=values(13)[2])
node(14, "SamplerCustomAdvanced", noise=["11", 0], guider=["10", 0], sampler=["12", 0],
     sigmas=["13", 0], latent_image=["6", 1])
node(15, "VAEDecode", samples=["14", 0], vae=["3", 0])
node(16, "VAEDecodeAudio", samples=["14", 0], vae=["4", 0])
node(17, "CreateVideo", images=["15", 0], fps=["100", 5], audio=["16", 0])
node(18, "NewteconsPanelSaveVideo", video=["17", 0], receipt_json=["100", 7])

(examples / "S02_A-panel.api.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

panel_outputs = [("prompt", "STRING"), ("ref_image_paths_json", "STRING"), ("duration_s", "FLOAT"),
                 ("width", "INT"), ("height", "INT"), ("fps", "FLOAT"), ("length", "INT"),
                 ("receipt_json", "STRING"), ("output_width", "INT"), ("output_height", "INT"),
                 ("guide_image_paths_json", "STRING")]
new_outputs = {"100": panel_outputs, "6": [("positive", "CONDITIONING"), ("LATENT", "LATENT")],
               "8": [("IMAGE", "IMAGE")], "18": [("render_receipt_json", "STRING")]}
gui_nodes, byid, links = [], {}, []
for order, (id, api_node) in enumerate(graph.items()):
    kind = api_node["class_type"]
    outputs = new_outputs.get(id) or [(x["name"], x["type"]) for x in old[id].get("outputs", [])]
    widgets = [value for value in api_node["inputs"].values() if not isinstance(value, list)]
    if kind == "RandomNoise":
        widgets.append("fixed")
    if kind == "LoadAudio":
        widgets.append("")
    gui = {"id": int(id), "type": kind, "title": "NEWTECONS Project Panel" if id == "100" else kind,
           "pos": [-520, 0] if id == "100" else [int((order - 1) % 3) * 470, int((order - 1) // 3) * 230],
           "size": [460, 990] if id == "100" else [430, 190], "flags": {}, "order": order, "mode": 0,
           "inputs": [], "outputs": [{"name": name, "type": type, "links": []} for name, type in outputs],
           "properties": {"Node name for S&R": kind}, "widgets_values": widgets}
    gui_nodes.append(gui)
    byid[id] = gui
for id, api_node in graph.items():
    for name, value in api_node["inputs"].items():
        if not isinstance(value, list):
            continue
        source_id, slot = value
        type = byid[source_id]["outputs"][slot]["type"]
        link_id = len(links) + 1
        input_slot = len(byid[id]["inputs"])
        byid[id]["inputs"].append({"name": name, "type": type, "link": link_id})
        byid[source_id]["outputs"][slot]["links"].append(link_id)
        links.append([link_id, int(source_id), slot, int(id), input_slot, type])
workflow = {"version": 0.4, "last_node_id": 100, "last_link_id": len(links), "nodes": gui_nodes,
            "links": links, "groups": [], "config": {}, "extra": {
                "title": "NEWTECONS S02_A • Project Panel integration example",
                "domain": "newtecons_live_action", "stage_only": True, "not_rendered": True,
                "source_workflow": str(SOURCE.relative_to(WORKSPACE)).replace("\\", "/"),
                "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "notes": "Replace sample paths/images. Fixed approved S02 WAV retained. One shot only. No approval inferred."}}
(examples / "S02_A-panel.workflow.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {len(gui_nodes)} nodes, {len(links)} checked links. Stage only; no GPU.")
