"""M8b (e): ``jjv h3 publish-shots`` writes jjv/shots/v1 from ACCEPTED takes only; carry frames are hash-bound.

Two shots of one logical line (``S02_A1`` cut, ``S02_A2`` carry), each through the real prepare -> submit ->
adopt -> accept path against a FAKE ComfyUI (no GPU, nothing but 127.0.0.1).  Frame counts are injected
(``frames_of``) because the fake outputs are not real video.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_comfy import FakeComfy
from h3_fixtures import EP, FakeProbe, H3World, ok_ps, run_h3, sha_file, template_graph
from test_h3_inputs_m8b import library_stub  # noqa: F401  (library_stub: fixture)
from images_fixtures import make_png

from engine.comfy.client import ComfyClient
from engine.core.errors import Refused
from engine.h3 import accept, adopt, publish, submit
from engine.h3 import inputs as inputs_mod

CUT, CARRY = "S02_A1", "S02_A2"
FRAMES = 120


pytestmark = pytest.mark.usefixtures("library_stub")

@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


class PublishWorld(H3World):
    """H3World whose graph has a carry sink (SaveImage of ImageFromBatch frame 119) and a 2-shot skeleton."""

    def __init__(self, tmp: Path, fake: FakeComfy) -> None:
        super().__init__(tmp, comfy_url=fake.url)
        graph = template_graph()
        graph["50"] = {"class_type": "ImageFromBatch", "inputs": {"image": ["6", 0], "batch_index": FRAMES - 1,
                                                                  "length": 1}}
        graph["55"] = {"class_type": "SaveImage", "inputs": {"images": ["50", 0], "filename_prefix": "z"}}
        self.template.write_text(json.dumps(graph), encoding="utf-8")
        self.fake = fake
        self.skeleton = self.tmp / "skeleton.json"
        self.write_skeleton()
        fake.auto_complete = True
        fake.on_post = self._outputs

    def write_skeleton(self, carry_kind: str = "carry") -> None:
        rows = [{"shot": CUT, "logical_shot": "S02_A", "speaker": "mother", "listener": "alice",
                 "entry": {"kind": "cut", "evidence": "script"}, "clip": None, "wav_binding": None, "receipt_dir": None},
                {"shot": CARRY, "logical_shot": "S02_A", "speaker": "mother", "listener": "alice",
                 "entry": {"kind": carry_kind, "evidence": "script"}, "clip": None, "wav_binding": None,
                 "receipt_dir": None}]
        self.skeleton.write_text(json.dumps({"schema": "jjv/shots-skeleton/v1", "episode_id": EP, "shots": rows}),
                                 encoding="utf-8")

    def _outputs(self, payload: dict, prompt_id: str) -> dict:
        root = self.world.comfy_root / "output"
        outputs = {}
        for node in ("18", "63"):
            (root / f"{prompt_id}-{node}.mp4").write_bytes(f"video-{prompt_id}-{node}".encode())
            outputs[node] = {"videos": [{"filename": f"{prompt_id}-{node}.mp4", "subfolder": "", "type": "output"}]}
        make_png(root / f"{prompt_id}-55.png", (len(prompt_id) * 7 % 255, int(prompt_id[-1]) * 20, 9), (864, 480))
        outputs["55"] = {"images": [{"filename": f"{prompt_id}-55.png", "subfolder": "", "type": "output"}]}
        return outputs

    def shot(self, shot: str, anchor: dict | None = None, pick: bool = True) -> None:
        overrides = {"shot": shot, "logical_shot": "S02_A", "sinks": {"native": "18", "carry": "55"},
                     "output_ports": [["18", "filename_prefix"], ["63", "filename_prefix"], ["55", "filename_prefix"]]}
        if anchor is not None:
            overrides["anchor"] = anchor
        self.write_manifest([self.row(**overrides)])
        self.prepare(shots=[shot])
        client = ComfyClient(self.fake.url, timeout_seconds=5)
        submit.submit(self.ctx(), self.out, [shot], self.settings(), client, probe=FakeProbe(), ps=ok_ps,
                      wait_timeout=5, approve_gpu=True)
        adopt.adopt(self.ctx(), self.out, [shot], self.settings(), client)
        if pick:
            accept.decide(self.out, shot, "pick", by="Kim", reason="lips, identity, seam ok", ctx=self.ctx())

    def _legacy_provenance(self, shots: list) -> dict | None:
        """CARRY's anchor is the carry output of CUT's accepted take, so its legal record is carry evidence (CUT's adopt
        receipt), not an image approval. Written only once that adopt receipt exists."""
        provenance = super()._legacy_provenance(shots)
        adopt = self.out / CUT / "adopt.json"
        if provenance and CARRY in provenance["shots"] and adopt.is_file():
            provenance["shots"][CARRY] = {"carry_from": {"shot": CUT, "adopt": adopt.as_posix(),
                                                        "adopt_sha256": sha_file(adopt)}}
        return provenance

    def carry_anchor(self) -> dict:
        found = publish.carry_output(self.ctx(), self.out, CUT)
        return {"path": Path(found["path"]).as_posix(), "sha256": found["sha256"], "ports": [["30", "image"]]}

    def build(self, frames: int = FRAMES):
        return publish.build(self.ctx(), self.out, shots_file=self.skeleton, frames_of=lambda path, tool: frames)

    def publish(self, frames: int = FRAMES) -> dict:
        return publish.publish_shots(self.ctx(), self.out, shots_file=self.skeleton,
                                     frames_of=lambda path, tool: frames)


def two_shots(tmp_path: Path, fake: FakeComfy) -> PublishWorld:
    world = PublishWorld(tmp_path, fake)
    world.shot(CUT)
    world.shot(CARRY, anchor=world.carry_anchor())
    return world


def test_publish_writes_schema_valid_shots_from_accepted_takes_and_binds_the_carry(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    _name_mouth_boxes(world, named=True)  # an episode that names the file expects it: the gap is reported
    result = world.publish()
    path = Path(result["shots_file"])
    assert path.name == "shots-h3-v001.json" and path.parent == world.ctx().episode_file.parent
    doc = json.loads(path.read_text("utf-8"))
    taken = {r["shot"]: r for r in accept.accepted_takes(world.out, ctx=world.ctx())}
    cut, carry = doc["shots"]
    assert (doc["schema"], doc["episode_id"], [cut["shot"], carry["shot"]]) == ("jjv/shots/v1", EP, [CUT, CARRY])
    assert cut["entry"]["kind"] == "cut" and "from_shot" not in cut["entry"]
    assert carry["entry"]["kind"] == "carry" and carry["entry"]["from_shot"] == CUT
    assert carry["entry"]["frame"] == FRAMES - 1
    for row in (cut, carry):
        assert row["clip"]["sha256"] == taken[row["shot"]]["sha256"] and row["clip"]["frames"] == FRAMES
        assert sha_file(world.root / row["clip"]["path"]) == row["clip"]["sha256"]
        assert row["wav_binding"]["sha256"] == sha_file(world.wav) and row["wav_binding"]["offset_s"] == 0.0
        assert row["wav_binding"]["kind"] == "preparation_json_wav_sha256"
        assert (row["speaker"], row["listener"]) == ("mother", "alice")
    prep = json.loads((world.out / CARRY / "preparation.json").read_text("utf-8"))
    assert prep["anchor"]["sha256"] == publish.carry_output(world.ctx(), world.out, CUT)["sha256"]
    assert [g["code"] for g in result["unmet"]] == ["MOUTH_BOXES_NOT_DERIVABLE"]
    assert not list(path.parent.glob("mouth-boxes*"))  # a named gap, never a hand-made file
    again = world.publish()  # deterministic: same takes -> same bytes -> the same version is reused
    assert (again["shots_file"], again["shots_sha256"]) == (result["shots_file"], result["shots_sha256"])
    sidecar = json.loads(Path(result["publication"]).read_text("utf-8"))
    assert sidecar["shots_file"]["sha256"] == result["shots_sha256"] and len(sidecar["takes"]) == 2


def _name_mouth_boxes(world: PublishWorld, named: bool) -> None:
    """Rewrite the episode's ``files.mouth_boxes``: present (named) or removed (unnamed, M8b-e2 decision c)."""
    path = world.ctx().episode_file
    doc = json.loads(path.read_text("utf-8"))
    if named:
        doc["files"]["mouth_boxes"] = "mouth-boxes.json"
    else:
        doc["files"].pop("mouth_boxes", None)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_unmet_has_no_mouth_row_when_the_episode_names_no_mouth_boxes(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    _name_mouth_boxes(world, named=False)
    result = world.publish()
    assert result["unmet"] == [] and "MOUTH_BOXES" not in result["next"]
    sidecar = json.loads(Path(result["publication"]).read_text("utf-8"))
    assert sidecar["unmet"] == []


def test_unmet_keeps_the_mouth_row_when_the_episode_names_mouth_boxes(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    _name_mouth_boxes(world, named=True)
    result = world.publish()
    assert [g["code"] for g in result["unmet"]] == ["MOUTH_BOXES_NOT_DERIVABLE"]
    assert "MOUTH_BOXES_NOT_DERIVABLE" in result["next"]


def test_a_shot_without_an_accepted_take_refuses_and_writes_nothing(tmp_path, fake) -> None:
    world = PublishWorld(tmp_path, fake)
    world.shot(CUT)
    with pytest.raises(Refused, match=f"NOT_PREPARED {CARRY}"):
        world.publish()
    world.shot(CARRY, anchor=world.carry_anchor(), pick=False)
    with pytest.raises(Refused, match=f"NO_ACCEPTED_TAKE {CARRY}"):
        world.publish()
    sha = accept.status(world.out, ctx=world.ctx())[1]["sha256"]
    accept.decide(world.out, CARRY, "reject", by="Kim", reason="lips drift", sha256=sha, ctx=world.ctx())
    with pytest.raises(Refused, match=f"NO_ACCEPTED_TAKE {CARRY}"):
        world.publish()
    assert not list(world.ctx().episode_file.parent.glob("shots-h3-*"))


def test_carry_with_a_foreign_anchor_is_an_unbound_gap(tmp_path, fake) -> None:
    world = PublishWorld(tmp_path, fake)
    world.shot(CUT)
    world.shot(CARRY)  # anchored on the approved still, NOT on the cut's carry output
    with pytest.raises(Refused, match=f"CARRY_ANCHOR_UNBOUND {CARRY}"):
        world.build()
    world.write_skeleton(carry_kind="cut")  # declared as a cut, the same takes publish
    doc, _ = world.build()
    assert doc["shots"][1]["entry"]["kind"] == "cut"


def test_carry_frame_must_lie_inside_the_source_clip(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    with pytest.raises(Refused, match=f"CARRY_FRAME_OUTSIDE_CLIP {CARRY}"):
        world.build(frames=FRAMES - 1)


def test_tampered_job_receipt_or_take_is_refused(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    job = world.out / CUT / "comfy" / "job.json"
    body = json.loads(job.read_text("utf-8"))
    body["outputs"] = [o for o in body["outputs"] if o["node_id"] != "63"]
    job.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(Refused, match=f"TAKE_RECEIPTS_DISAGREE {CUT}"):
        world.build()


def test_tampered_editorial_file_drops_the_take(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    take = accept.accepted_takes(world.out, [CUT], ctx=world.ctx())[0]
    Path(take["path"]).write_bytes(b"re-encoded")
    with pytest.raises(Refused, match=f"NO_ACCEPTED_TAKE {CUT}"):
        world.build()


def test_carry_output_refuses_an_unaccepted_source_and_inputs_binds_it(tmp_path, fake) -> None:
    world = PublishWorld(tmp_path, fake)
    world.shot(CUT, pick=False)
    with pytest.raises(Refused, match="NO_ACCEPTED_TAKE"):
        publish.carry_output(world.ctx(), world.out, CUT)
    accept.decide(world.out, CUT, "pick", by="Kim", reason="ok", ctx=world.ctx())
    listed = json.loads(world.skeleton.read_text("utf-8"))["shots"]
    path, sha, prov = inputs_mod.carried_anchor(world.ctx(), world.out, listed, listed[1])
    adopted = json.loads((world.out / CUT / "adopt.json").read_text("utf-8"))
    carry = next(o for o in adopted["outputs"] if o["role"] == "carry")
    assert (sha, sha_file(path), prov["carry_from"]["shot"], prov["carry_from"]["frame"]) == (
        carry["sha256"], carry["sha256"], CUT, FRAMES - 1)


def _pick_record(world: PublishWorld, shot: str) -> Path:
    return next(p for p in sorted((world.out / shot / "acceptance").glob("*-pick.json")))


def test_acceptance_pins_the_adopt_receipt_and_publication_reports_the_pin(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    for shot in (CUT, CARRY):
        subject = json.loads(_pick_record(world, shot).read_text("utf-8"))["subject"]
        assert subject["adopt_sha256"] == sha_file(world.out / shot / "adopt.json")
    sidecar = json.loads(Path(world.publish()["publication"]).read_text("utf-8"))
    assert all(t["adopt_pinned_by_acceptance"] for t in sidecar["takes"])


def _tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_coordinated_edit_of_adopt_and_job_receipts_is_refused(tmp_path, fake) -> None:
    """Same editorial bytes, but adopt.json + job.json both rewritten to claim another run (CR-M8be MAJOR)."""
    world = two_shots(tmp_path, fake)
    for name in ("adopt.json", "comfy/job.json"):
        path = world.out / CUT / name
        body = json.loads(path.read_text("utf-8"))
        body["prompt_id"] = "forged-prompt"
        path.write_text(json.dumps(body), encoding="utf-8")
    # Two refusals guard the same tamper. Stage A's load-time carry recheck (prepare.py, carry_from branch: the adopt.json
    # sha pinned when the manifest was written) runs first and says 'legacy carry adoption hash mismatch'; publish's own
    # TAKE_RECEIPTS_DISAGREE check is the original message. Either is a refusal; neither may publish or write acceptance.
    before, accepted = _tree(tmp_path), accept.accepted_takes(world.out, ctx=world.ctx())
    with pytest.raises(Refused, match=rf"(TAKE_RECEIPTS_DISAGREE {CUT}.*(acceptance prompt|adopt\.json sha)|legacy carry adoption hash mismatch)"):
        world.build()
    assert _tree(tmp_path) == before and accept.accepted_takes(world.out, ctx=world.ctx()) == accepted


def test_adopt_receipt_changed_after_acceptance_is_refused(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    path = world.out / CUT / "adopt.json"
    body = json.loads(path.read_text("utf-8"))
    body["note"] = "edited after the pick"
    path.write_text(json.dumps(body), encoding="utf-8")
    # Two refusals guard the same tamper. Stage A's load-time carry recheck (prepare.py, carry_from branch: the adopt.json
    # sha pinned when the manifest was written) runs first and says 'legacy carry adoption hash mismatch'; publish's own
    # TAKE_RECEIPTS_DISAGREE check is the original message. Either is a refusal; neither may publish or write acceptance.
    before, accepted = _tree(tmp_path), accept.accepted_takes(world.out, ctx=world.ctx())
    with pytest.raises(Refused, match=rf"(TAKE_RECEIPTS_DISAGREE {CUT}.*(acceptance prompt|adopt\.json sha)|legacy carry adoption hash mismatch)"):
        world.build()
    assert _tree(tmp_path) == before and accept.accepted_takes(world.out, ctx=world.ctx()) == accepted


def test_legacy_pick_without_adopt_pin_still_publishes_and_is_flagged(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    record = _pick_record(world, CUT)
    body = json.loads(record.read_text("utf-8"))
    del body["subject"]["adopt_sha256"]
    record.write_text(json.dumps(body), encoding="utf-8")
    _, receipt = world.build()
    pinned = {t["shot"]: t["adopt_pinned_by_acceptance"] for t in receipt["takes"]}
    assert pinned == {CUT: False, CARRY: True}


@pytest.mark.parametrize("failing", ["publication", "shots"])
def test_publication_pair_is_all_or_nothing(tmp_path, fake, monkeypatch, failing) -> None:
    world = two_shots(tmp_path, fake)
    real = publish.write_once

    def broken(path, payload):
        is_sidecar = Path(path).name.endswith(".publication.json")
        if is_sidecar == (failing == "publication"):
            raise OSError("disk full")
        return real(path, payload)

    monkeypatch.setattr(publish, "write_once", broken)
    with pytest.raises(OSError, match="disk full"):
        world.publish()
    assert not list(world.ctx().episode_file.parent.glob("shots-h3-*"))
    monkeypatch.setattr(publish, "write_once", real)
    result = world.publish()  # a clean retry takes v001
    assert Path(result["shots_file"]).name == "shots-h3-v001.json" and Path(result["publication"]).is_file()


def test_orphan_publication_sidecar_never_blocks_a_version(tmp_path, fake) -> None:
    world = two_shots(tmp_path, fake)
    (world.ctx().episode_file.parent / "shots-h3-v001.publication.json").write_text("{}", encoding="utf-8")
    assert Path(world.publish()["shots_file"]).name == "shots-h3-v002.json"


def test_cli_round_trip(tmp_path, fake, monkeypatch) -> None:
    world = two_shots(tmp_path, fake)
    _name_mouth_boxes(world, named=True)
    monkeypatch.setattr(publish, "find_ffprobe", lambda explicit=None: "ffprobe")
    monkeypatch.setattr(publish, "probe_frames", lambda path, tool: FRAMES)
    base = ["--episode", str(world.root), "--out", str(world.out), "--machine", str(world.world.machine_path),
            "--shots", str(world.skeleton)]
    code, body = run_h3(["publish-shots", *base])
    assert code == 0 and body["shots"] == [CUT, CARRY] and body["clip_frames_total"] == 2 * FRAMES
    assert body["unmet"][0]["code"] == "MOUTH_BOXES_NOT_DERIVABLE"
    (world.out / CARRY / "acceptance").rename(world.out / CARRY / "acceptance-moved")
    code, body = run_h3(["publish-shots", *base])
    assert code == 1 and "NO_ACCEPTED_TAKE" in body["error"]
