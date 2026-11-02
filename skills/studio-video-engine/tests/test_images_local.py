"""``jjv images submit --provider comfyui-local``: Krea2 edit graph, LoRA gate, guarded dispatch against a FAKE ComfyUI."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from engine.comfy.client import ComfyClient
from engine.comfy.settings import settings_from_machine
from engine.core.errors import Refused
from engine.images import krea2, local
from engine.layout.context import load_recipe
from fake_comfy import FakeComfy
from images_fixtures import LIVE, World, make_png, sha

LORA_INFO = {"python_module": "nodes", "category": "loaders",
             "input": {"required": {"lora_name": [["krea2_general_edit_v2.safetensors", "krea2_identity_edit_v2.safetensors"]]}}}


def recipe(**changes):
    row = copy.deepcopy(load_recipe("krea2-edit-local-v001", "jjv/images-local-recipe/v1")[0])
    row["min_free_vram_mib"] = 1024
    row["poll_seconds"] = 0.05
    row.update(changes)
    return row


class Setup:
    def __init__(self, tmp: Path, fake: FakeComfy, domain: str = "jenniejoy_cartoon_3d") -> None:
        self.world = World(tmp, domain=domain, comfy_url=fake.url)
        self.fake = fake
        self.layout, self.out = tmp / "layout", tmp / "images"
        self.world.plan_layout(self.layout)
        self.world.images_plan(self.out, self.layout)
        self.prompt = tmp / "brief.txt"
        self.prompt.write_text("Warm sunny garden, mother seated, child kneeling.", encoding="utf-8")
        self.settings = settings_from_machine(self.world.machine)
        self.client = ComfyClient(self.settings.base_url, timeout_seconds=5)
        fake.object_info["LoraLoaderModelOnly"] = LORA_INFO
        fake.auto_complete = True
        fake.on_post = self._make_output

    def _make_output(self, payload, prompt_id):
        prefix = payload["prompt"]["15"]["inputs"]["filename_prefix"]
        folder = self.settings.output_dir / prefix
        folder.mkdir(parents=True, exist_ok=True)
        make_png(folder / "image_00001_.png", (30, 90, 60), (320, 180))
        return {"15": {"images": [{"filename": "image_00001_.png", "subfolder": prefix, "type": "output"}]}}

    def submit(self, **kw):
        kw.setdefault("recipe", recipe())
        return local.submit(self.world.ctx(), self.out, "S01_A", self.prompt, self.settings, self.client, **kw)


@pytest.fixture
def fake():
    with FakeComfy() as server:
        yield server


def test_dry_run_saves_graph_prompt_cast_sheet_and_seed_and_sends_nothing(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    result = setup.submit(dry_run=True)
    folder = setup.out / "S01_A" / "local" / "t001"
    assert result["dry_run"] and not result["submitted"] and fake.posts == []
    graph = json.loads((folder / "graph.api.json").read_text("utf-8"))
    assert graph["13"]["inputs"]["seed"] == result["seed"] and 0 <= result["seed"] < 2 ** 32
    assert graph["4"]["inputs"]["lora_name"] == "krea2_general_edit_v2.safetensors" and graph["4"]["inputs"]["model"] == ["1", 0]
    assert graph["12"]["inputs"]["model"] == ["4", 0]                     # edit LoRA right after UNETLoader
    assert (folder / "cast-sheet.png").is_file() and (folder / "prompt.txt").is_file()
    assert "PLACEMENT" in (folder / "prompt.txt").read_text("utf-8") and "Mother seated" in graph["10"]["inputs"]["prompt"]
    assert result["size"][0] * result["size"][1] <= 2_000_000 and result["size"][0] % 16 == 0
    assert not (folder / "graph.gui.json").exists()  # dry run cannot publish missing inputs
    assert "GUI_INPUT" in result["gui"]["error"]
    assert not list(setup.settings.input_dir.iterdir())                    # a dry run stages nothing


def test_seed_is_deterministic_per_take_and_an_explicit_seed_wins(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    first = setup.submit(dry_run=True)["seed"]
    second = setup.submit(dry_run=True)["seed"]                            # take t002
    assert first != second and setup.submit(dry_run=True, seed=1234, take="t010")["seed"] == 1234


def test_identity_task_picks_the_identity_lora(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    result = setup.submit(dry_run=True, task="identity")
    assert result["lora"] == "krea2_identity_edit_v2.safetensors"
    with pytest.raises(Refused, match="--task"):
        setup.submit(dry_run=True, task="swap")


def test_a_real_submit_needs_the_pilot_flag_while_the_recipe_is_unqualified(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    with pytest.raises(Refused, match="--pilot"):
        setup.submit()
    assert fake.posts == [] and not (setup.out / "S01_A" / "local").exists()


def test_pilot_submit_posts_once_and_receipts_everything_with_the_graph_and_both_guis(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    result = setup.submit(pilot=True, seed=777)
    assert result["submitted"] and len(fake.posts) == 1 and result["prompt_id"] == "pid-0001"
    posted = fake.posts[0]["prompt"]
    assert {n["class_type"] for n in posted.values()} <= {"UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly",
        "LoadImage", "VAEEncode", "EmptySD3LatentImage", "Krea2EditGroundedEncode", "ConditioningZeroOut",
        "Krea2EditModelPatch", "KSampler", "VAEDecode", "SaveImage"}          # no partner/chat node can appear
    receipt = json.loads(Path(result["receipt"]).read_text("utf-8"))
    assert receipt["route"] == "comfyui-local" and receipt["seed"] == 777 and receipt["runtime_id"] == "pid-0001"
    assert receipt["models"]["unet"] == "krea2_turbo_int8_convrot.safetensors" and receipt["models"]["lora"].startswith("krea2_general")
    assert receipt["recipe_qualification"] == "unqualified" and receipt["comfy_output"]["sha256"] == receipt["output"]["sha256"]
    assert [r["role"] for r in receipt["ref_hashes"]] == ["mother", "alice"] and receipt["cast_sheet"]["sha256"]
    folder = Path(receipt["graph"]["dir"])
    for name in ("graph.api.json", "graph.gui.json", "graph.review.gui.json"):
        assert (folder / name).is_file(), name
    review = json.loads((folder / "graph.review.gui.json").read_text("utf-8"))
    assert review["extra"]["result_sha256"] == receipt["output"]["sha256"] and review["nodes"][-1]["type"] == "LoadImage"
    staged = sorted(p.name for p in setup.settings.input_dir.iterdir())
    assert any(n.endswith("guide.png") for n in staged) and any(n.endswith("refs.png") for n in staged)
    guide = next(p for p in setup.settings.input_dir.iterdir() if p.name.endswith("guide.png"))
    assert sha(guide) == receipt["guide"]["sha256"]                         # staged bytes are the planned bytes
    assert not setup.settings.lock_path.exists()


def test_missing_edit_lora_in_comfyui_refuses_before_any_post(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    fake.object_info["LoraLoaderModelOnly"] = {**LORA_INFO, "input": {"required": {"lora_name": [["something_else.safetensors"]]}}}
    with pytest.raises(Refused, match="E_LORA_GATE"):
        setup.submit(pilot=True)
    assert fake.posts == []


def test_a_partner_node_in_comfyui_object_info_refuses(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    fake.object_info["KSampler"] = {"python_module": "comfy_api_nodes.nodes_x", "category": "api node/image"}
    with pytest.raises(Refused, match="partner/API node"):
        setup.submit(pilot=True)
    assert fake.posts == []


def test_not_enough_free_vram_refuses_and_a_busy_queue_refuses(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    with pytest.raises(Refused, match="free VRAM"):
        setup.submit(pilot=True, recipe=recipe(min_free_vram_mib=20000))     # the fake card reports 8 GiB free
    fake.queue["queue_pending"] = [[1, "other", {}, {"client_id": "x"}, []]]
    with pytest.raises(Refused, match="queue is busy"):
        setup.submit(pilot=True, take="t900")
    assert fake.posts == []


def test_the_lora_gate_catches_a_graph_where_the_patch_bypasses_the_lora():
    r = recipe()
    graph = krea2.build_graph(r, task="general", guide_name="g.png", sheet_name="s.png", prompt="p", seed=1, width=64,
                              height=64, prefix="x")
    assert krea2.lora_gate(graph, r, "general")["lora_name"] == "krea2_general_edit_v2.safetensors"
    broken = copy.deepcopy(graph)
    broken["12"]["inputs"]["model"] = ["1", 0]                               # the bare UNET: the v014-v016 failure
    with pytest.raises(Refused, match="does not take its model from the edit LoRA"):
        krea2.lora_gate(broken, r, "general")
    wrong = copy.deepcopy(graph)
    wrong["4"]["inputs"]["lora_name"] = "krea2_identity_edit_v2.safetensors"
    with pytest.raises(Refused, match="needs LoRA krea2_general_edit_v2"):
        krea2.lora_gate(wrong, r, "general")
    detached = copy.deepcopy(graph)
    detached["4"]["inputs"]["model"] = ["2", 0]
    with pytest.raises(Refused, match="not wired to the UNETLoader"):
        krea2.lora_gate(detached, r, "general")


def test_fit_size_keeps_aspect_stays_under_the_pixel_cap_and_on_the_grid():
    for w, h in ((1672, 941), (1536, 864), (4000, 3000), (320, 180)):
        fw, fh = krea2.fit_size(w, h, 2_000_000, 16)
        assert fw * fh <= 2_000_000 and fw % 16 == 0 and fh % 16 == 0
        assert abs(fw / fh - w / h) / (w / h) < 0.03     # the grid floors a side by < 16 px


def test_live_action_domain_may_use_the_local_route(tmp_path, fake):
    setup = Setup(tmp_path, fake, domain=LIVE)
    assert setup.submit(dry_run=True)["dry_run"] is True
