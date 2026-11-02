"""H3-PACK-BIND (user 31/10): H3 preparation binds EVERY reference image of a shot from its anchor pack — face/body from the
library, wardrobe from presets, the first frame (AddGuide) from the pack storyboard — never from a casting file or an old
storyboard.  A pack that exists but is stale / sha-drifted / unstaged is refused, not replaced.  No pack ⇒ the cast path as
before, with a warning.  The dialogue WAV stays the one named in ``preparation.json -> wav.sha256`` (AGENTS.md rule 3).
No GPU; the only ComfyUI is the in-process fake on 127.0.0.1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
for _folder in (_TESTS / "video", _TESTS / "h3", _TESTS):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from fake_comfy import FakeComfy  # noqa: E402
from h3_fixtures import EP, SHOT, FakeProbe, fake_with_video, ok_ps, run_h3, sha_file  # noqa: E402
from pack_fixtures import ROWS, dump, presets, saved_pack, staged_name  # noqa: E402
from test_h3_inputs_m8b import InputsWorld, library_stub  # noqa: E402

from engine.comfy.client import ComfyClient  # noqa: E402
from engine.core.errors import Refused  # noqa: E402
from engine.core.io import read_json  # noqa: E402
from engine.h3 import inputs as inputs_mod  # noqa: E402
from engine.h3 import pack_refs  # noqa: E402
from engine.h3 import prepare as prepare_mod  # noqa: E402
from engine.h3 import submit  # noqa: E402
from engine.video import anchor_pack_ui, anchor_stage, anchor_verify  # noqa: E402

PREFIX = "demo_anc"
REF_LOADERS = ("5", "39", "32", "41")  # ref_image_0..3 as in the grouped H3 template; "8" is the AddGuide LoadImage


def name_of(ref: dict) -> str:
    return staged_name(PREFIX, ref["slot"], ref["sha256"])


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def pack_template(extra_loader: bool = False) -> dict:
    graph = {
        "7": {"class_type": "LoadAudio", "inputs": {"audio": "STALE.wav"}},
        "8": {"class_type": "LoadImage", "inputs": {"image": "STALE-storyboard.png"}},
        "9": {"class_type": "MiniMaxH3AddGuide", "inputs": {"image": ["8", 0], "audio": ["7", 0], "frame": 0}},
        "19": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "template prompt"}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
        "6": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["19", 0], "length": 141, "guide": ["9", 0],
                                                                    "ref_audios.ref_audio_0": ["7", 0]}},
        "17": {"class_type": "CreateVideo", "inputs": {"images": ["6", 0], "fps": 24, "audio": ["7", 0]}},
        "18": {"class_type": "SaveVideo", "inputs": {"video": ["17", 0], "filename_prefix": "x"}},
        "63": {"class_type": "SaveVideo", "inputs": {"video": ["17", 0], "filename_prefix": "y"}},
    }
    for index, node in enumerate(REF_LOADERS + (("40",) if extra_loader else ())):
        graph[node] = {"class_type": "LoadImage", "inputs": {"image": f"STALE-{index}.png"}}
        graph["6"]["inputs"][f"ref_images.ref_image_{index}"] = [node, 0]
    return graph


class PackWorld(InputsWorld):
    """InputsWorld (voice + image receipts + cast) + a pack built by ``anchor_pack`` under ``tmp/pack`` + a 4-ref template."""

    def __init__(self, tmp: Path, *, storyboard: bool = True, extra_loader: bool = False, rows: list[dict] | None = None,
                 approved: bool = True) -> None:
        super().__init__(tmp)
        self.template.write_text(json.dumps(pack_template(extra_loader)), encoding="utf-8")
        self.pack_world, self.lib, self.pack_path = saved_pack(tmp / "pack", storyboard=storyboard, rows=rows, approved=approved)
        self.anchor_dir = self.pack_path.parent.parent
        self.shotlist = self.pack_world.tmp / "shotlist-draft.json"
        self.write_spec()

    def spec_doc(self, **shot) -> dict:
        doc = super().spec_doc(**shot)
        doc["defaults"] = {k: v for k, v in doc["defaults"].items() if k != "faces"}
        doc["defaults"]["anchor_ports"] = [["8", "image"]]
        return doc

    def stage(self, **kw) -> dict:
        return anchor_stage.stage(self.ctx(), self.pack_path, self.settings(), input_prefix=PREFIX, shotlist=self.shotlist, **kw)

    def build(self, out: Path | None = None, **kw) -> dict:
        return inputs_mod.write_inputs(self.ctx(), self.spec, out or self.tmp / "built-inputs.json", images=self.images,
                                       voice=self.voice, cast_file=self.world.cast, mapping={"mother": "mom-alice"},
                                       anchor_dir=self.anchor_dir, shotlist=self.shotlist, **kw)

    def cast_tokens(self) -> list[str]:
        return [str(self.world.cast_dir), sha_file(self.world.alice), sha_file(self.world.mom), sha_file(self.native), "casting"]


def test_pack_present_binds_every_pack_ref_and_never_the_cast_file(tmp_path) -> None:
    world = PackWorld(tmp_path)
    world.stage()
    summary = world.build()
    manifest = read_json(world.tmp / "built-inputs.json")
    row = manifest["shots"][0]
    assert row["faces"] == [] and [r["slot"] for r in row["refs"]] == [f"ref_images.ref_image_{i}" for i in range(4)]
    assert [r["role"] for r in row["refs"]] == ["face", "body", "wardrobe", "wardrobe"]
    assert [r["ports"] for r in row["refs"]] == [[[n, "image"]] for n in REF_LOADERS]
    assert all(r["input_name"] == name_of(r) for r in row["refs"])
    board = read_json(world.pack_path)["storyboard_anchor"]
    assert row["anchor"]["ports"] == [["8", "image"]] and row["anchor"]["slot"] == "guide.image" and row["anchor"]["role"] == "storyboard"
    assert row["anchor"]["sha256"] == board["sha256"] and row["storyboard"] == {"status": "approved", "pilot": False}
    assert row["anchor_pack"]["sha256"] == sha_file(world.pack_path) and row["anchor_pack"]["context"] == "cong_truong"
    text = json.dumps(manifest).lower()
    assert not [t for t in world.cast_tokens() if t.lower() in text]
    assert summary["warnings"] == [] and summary["shots"][0]["source"] == "anchor-pack"
    result = prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    receipt = read_json(world.out / SHOT / "preparation.json")
    assert receipt["faces"] == [] and [(r["slot"], r["role"]) for r in receipt["refs"]] == [(r["slot"], r["role"]) for r in row["refs"]]
    assert all({"path", "sha256", "slot", "role", "input_name", "name"} <= set(r) for r in receipt["refs"])
    assert receipt["anchor_pack"]["sha256"] == sha_file(world.pack_path) and receipt["storyboard"] == {"status": "approved", "pilot": False}
    assert receipt["wav"]["sha256"] == sha_file(world.wav)  # AGENTS.md (3): the dialogue WAV is the one named here
    graph = read_json(world.out / SHOT / "graph.api.json")
    assert [graph[n]["inputs"]["image"] for n in REF_LOADERS] == [r["input_name"] for r in receipt["refs"]]
    assert graph["8"]["inputs"]["image"] == receipt["anchor"]["input_name"] == staged_name(PREFIX, "guide.image", board["sha256"])
    text = json.dumps(receipt).lower()
    assert not [t for t in world.cast_tokens() if t.lower() in text]
    assert result["warnings"] == [] and result["shots"][0]["graph_sha256"] == receipt["graph_sha256"]
    assert prepare_mod.load_prepared(world.ctx(), world.out)[0][1]["graph_sha256"] == receipt["graph_sha256"]


def test_pack_ref_approval_sha_mismatch_is_refused_before_inputs_write(tmp_path, monkeypatch) -> None:
    world = PackWorld(tmp_path, approved=False)
    world.stage()
    ref = read_json(world.pack_path)["face_refs"][0]

    def wrong_current_approval(out: Path, prompt_id: str) -> dict:
        return {"schema": "jjv/library-image-approval/v1", "status": "accepted_library_image",
                "candidate_sha256": "f" * 64,
                "path": str(Path(out) / "_review" / prompt_id / "approvals" / "approval-v001.json")}

    monkeypatch.setattr(pack_refs.image_library, "current_approval", wrong_current_approval)
    output = world.tmp / "mismatch-inputs.json"
    with pytest.raises(Refused, match=pack_refs.APPROVAL_SHA_MISMATCH):
        world.build(out=output)
    assert not output.exists() and ref["sha256"] != "f" * 64


def test_submit_stages_the_pack_refs_under_their_subfolder_and_posts_once(tmp_path, fake) -> None:
    world = PackWorld(tmp_path)
    world.world.machine["comfy"]["url"] = fake.url
    world.world.write_machine()
    world.stage()
    world.build()
    prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    fake_with_video(world, fake)
    result = submit.submit(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5), probe=FakeProbe(),
                           ps=ok_ps, wait_timeout=5, approve_gpu=True)
    assert len(fake.posts) == 1 and result["submitted"][0]["status"] == "COMPLETED"
    receipt = read_json(world.out / SHOT / "preparation.json")
    posted = fake.posts[0]["prompt"]
    assert [posted[n]["inputs"]["image"] for n in REF_LOADERS] == [r["input_name"] for r in receipt["refs"]]
    top = sorted(p.name for p in (world.world.comfy_root / "input").iterdir() if p.is_file())
    expected = [*(r["input_name"] for r in receipt["refs"]), receipt["anchor"]["input_name"], f"h3-{sha_file(world.wav)}.wav"]
    assert top == sorted(expected)  # flat at the input root; no second image copy under a content-hash name
    again = submit.submit(world.ctx(), world.out, None, world.settings(), ComfyClient(fake.url, timeout_seconds=5), probe=FakeProbe(),
                          ps=ok_ps, wait_timeout=5, approve_gpu=True)
    assert len(fake.posts) == 1 and again["already_submitted"][0]["status"] == "ALREADY_SUBMITTED"


def test_stale_pack_is_refused_never_replaced_by_the_cast_file(tmp_path) -> None:
    site = [{**r, "context": "cong_truong"} if r["id"] == SHOT else r for r in ROWS]
    world = PackWorld(tmp_path, rows=site)
    world.stage()
    world.build(out=world.tmp / "ok-inputs.json")
    office = [{**r, "context": "van_phong"} if r["id"] == SHOT else r for r in ROWS]
    world.shotlist = dump(world.pack_world.tmp / "shotlist-v2.json", {"schema": "jjv/shotlist-draft/v1", "episode": EP, "fps": 24, "rows": office})
    with pytest.raises(Refused, match="ANCHOR_PACK_STALE") as error:  # shotlist moved the shot to an office: the site pack is stale
        world.build(out=world.tmp / "stale-inputs.json")
    assert "van_phong" in str(error.value) and not (world.tmp / "stale-inputs.json").exists()
    presets(world.pack_world, approved=True)  # a pack source rewritten after the pack ⇒ prepare of the earlier manifest refuses too
    with pytest.raises(Refused, match="ANCHOR_PACK_STALE"):
        prepare_mod.prepare(world.ctx(), world.tmp / "ok-inputs.json", world.out)
    assert not world.out.exists()
    world.shotlist = world.pack_world.tmp / "shotlist-draft.json"
    with pytest.raises(Refused, match="ANCHOR_PACK_STALE"):
        world.build(out=world.tmp / "stale2-inputs.json")
    assert not (world.tmp / "stale2-inputs.json").exists()


def test_ref_sha_drift_is_refused_at_inputs_and_at_prepare(tmp_path) -> None:
    world = PackWorld(tmp_path)
    world.stage()
    world.build()
    (world.lib.dir / world.lib.entry("alice", "FACE", 1)["file"]).write_bytes(b"tampered")
    with pytest.raises(Refused, match="hash mismatch|SHA_MISMATCH|ANCHOR_PACK_INVALID"):
        prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    assert not world.out.exists()
    with pytest.raises(Refused, match="hash mismatch|SHA_MISMATCH|ANCHOR_PACK_INVALID"):
        world.build(out=world.tmp / "again.json")
    assert not (world.tmp / "again.json").exists()


@pytest.mark.usefixtures("library_stub")
def test_without_a_pack_the_cast_path_is_unchanged_but_warned(tmp_path) -> None:
    """LEGACY (--legacy-cast-faces): faces from the cast file, each with an approved library record; warned, and recorded."""
    world = InputsWorld(tmp_path)
    summary = world.build()
    manifest = read_json(world.tmp / "built-inputs.json")
    assert [f["sha256"] for f in manifest["shots"][0]["faces"]] == [sha_file(world.world.mom), sha_file(world.world.alice)]
    assert "refs" not in manifest["shots"][0] and "anchor_pack" not in manifest["shots"][0]
    assert summary["warnings"] and summary["warnings"][0].startswith("ANCHOR_PACK_MISSING") and summary["shots"][0]["source"] == "cast"
    result = prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    assert result["warnings"] and result["warnings"][0].startswith("ANCHOR_PACK_MISSING")
    receipt = read_json(world.out / SHOT / "preparation.json")
    assert receipt["refs"] == [] and receipt["anchor_pack"] is None
    empty = tmp_path / "no-packs"
    empty.mkdir()
    summary = inputs_mod.write_inputs(world.ctx(), world.spec, world.tmp / "b.json", images=world.images, voice=world.voice,
                                      cast_file=world.world.cast, mapping={"mother": "mom-alice"}, anchor_dir=empty,
                                      legacy_cast_faces=True)
    assert summary["warnings"][0].startswith("ANCHOR_PACK_MISSING") and str(empty) in summary["warnings"][0]


@pytest.mark.usefixtures("library_stub")
def test_without_a_pack_and_without_the_legacy_flag_nothing_is_written(tmp_path) -> None:
    """CRFIX #01: a shot with no anchor pack is REFUSED by default; the cast file is never the silent fallback."""
    world = InputsWorld(tmp_path)
    out = world.tmp / "refused.json"
    with pytest.raises(Refused, match="ANCHOR_PACK_MISSING"):
        world.build(out, legacy=False)
    assert not out.exists()


def test_pending_storyboard_is_refused_unless_the_explicit_pilot_flag(tmp_path) -> None:
    world = PackWorld(tmp_path, storyboard=False)
    world.stage()
    with pytest.raises(Refused, match="STORYBOARD_PENDING"):
        world.build()
    assert not (world.tmp / "built-inputs.json").exists()
    world.build(allow_pending_storyboard=True)
    row = read_json(world.tmp / "built-inputs.json")["shots"][0]
    body = read_json(world.pack_path)["body_refs"][0]
    assert row["anchor"]["role"] == "pilot-guide:body" and row["anchor"]["sha256"] == body["sha256"]
    assert row["storyboard"] == {"status": "pending", "pilot": True}
    prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    receipt = read_json(world.out / SHOT / "preparation.json")
    assert receipt["storyboard"] == {"status": "pending", "pilot": True} and receipt["review_status"] == "pending"
    graph = read_json(world.out / SHOT / "graph.api.json")
    assert graph["8"]["inputs"]["image"] == staged_name(PREFIX, "ref_images.ref_image_1", body["sha256"])


def test_unstaged_pack_and_unfilled_loader_are_refused(tmp_path) -> None:
    world = PackWorld(tmp_path)
    with pytest.raises(Refused, match="ANCHOR_PACK_NOT_STAGED"):
        world.build()
    world = PackWorld(tmp_path / "b", extra_loader=True)
    world.stage()
    with pytest.raises(Refused, match="REF_SLOTS_UNFILLED"):
        world.build()


def test_cli_inputs_accepts_anchor_dir_and_shotlist(tmp_path) -> None:
    world = PackWorld(tmp_path)
    world.stage()
    out = world.tmp / "cli-inputs.json"
    code, summary = run_h3(["inputs", "--episode", str(world.root), "--machine", str(world.world.machine_path), "--out", str(out),
                            "--spec", str(world.spec), "--images", str(world.images), "--voice", str(world.voice), "--cast",
                            str(world.world.cast), "--map", "mother=mom-alice", "--anchor-dir", str(world.anchor_dir),
                            "--shotlist", str(world.shotlist)])
    assert code == 0 and summary["shots"][0]["source"] == "anchor-pack" and out.is_file()


def test_modules_stay_small_and_neutral() -> None:
    for module in (pack_refs, anchor_stage, anchor_verify, anchor_pack_ui, prepare_mod, inputs_mod, submit):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert len(text.splitlines()) < 400, module.__name__
        for token in ("jenniejoy", "newtecons", "ep04", "04-milk", "s02_a", "char_02"):
            assert token not in text.lower(), (module.__name__, token)


def _spec_with_drop(world: PackWorld, value) -> None:
    doc = world.spec_doc()
    doc["defaults"]["drop_unfilled_refs"] = value
    world.write_spec(doc)


def test_drop_unfilled_refs_removes_the_loader_the_pack_has_no_image_for(tmp_path) -> None:
    world = PackWorld(tmp_path, extra_loader=True)  # template has 5 ref loaders, the pack binds 4
    world.stage()
    _spec_with_drop(world, True)
    world.build()
    row = read_json(world.tmp / "built-inputs.json")["shots"][0]
    assert row["dropped_refs"] == ["ref_images.ref_image_4"]
    prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    graph = read_json(world.out / SHOT / "graph.api.json")
    assert "40" not in graph and "ref_images.ref_image_4" not in graph["6"]["inputs"]
    assert [graph[n]["inputs"]["image"] for n in REF_LOADERS] == [r["input_name"] for r in row["refs"]]
    receipt = read_json(world.out / SHOT / "preparation.json")
    assert receipt["dropped_refs"] == {"slots": ["ref_images.ref_image_4"], "nodes": ["40"]}
    assert prepare_mod.load_prepared(world.ctx(), world.out)[0][1]["graph_sha256"] == receipt["graph_sha256"]


def test_drop_unfilled_refs_is_off_by_default_and_must_be_boolean(tmp_path) -> None:
    world = PackWorld(tmp_path, extra_loader=True)
    world.stage()
    _spec_with_drop(world, False)
    with pytest.raises(Refused, match="REF_SLOTS_UNFILLED"):
        world.build()
    _spec_with_drop(world, "yes")
    with pytest.raises(Refused, match="drop_unfilled_refs must be true or false"):
        world.build()


def test_a_full_pack_with_the_flag_on_changes_nothing(tmp_path) -> None:
    world = PackWorld(tmp_path)
    world.stage()
    _spec_with_drop(world, True)
    world.build()
    row = read_json(world.tmp / "built-inputs.json")["shots"][0]
    assert "dropped_refs" not in row
    prepare_mod.prepare(world.ctx(), world.tmp / "built-inputs.json", world.out)
    assert "dropped_refs" not in read_json(world.out / SHOT / "preparation.json")


def test_prepare_never_drops_a_bound_or_foreign_slot(tmp_path) -> None:
    world = PackWorld(tmp_path)
    world.stage()
    world.build()
    manifest = read_json(world.tmp / "built-inputs.json")
    for slot, match in (("ref_images.ref_image_0", "bound to an image"), ("ref_images.ref_image_9", "not a ref loader")):
        bad = json.loads(json.dumps(manifest))
        bad["shots"][0]["dropped_refs"] = [slot]
        path = world.tmp / f"bad-{slot[-1]}.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(Refused, match=match):
            prepare_mod.prepare(world.ctx(), path, world.tmp / f"out-{slot[-1]}")
