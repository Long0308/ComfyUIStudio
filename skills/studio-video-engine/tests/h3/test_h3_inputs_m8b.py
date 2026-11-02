"""M8b (d): ``jjv h3 inputs`` builds the ``jjv/h3-inputs/v1`` manifest from engine receipts only (no GPU, no net)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from h3_fixtures import EP, SHOT, H3World, run_h3, sha_file, template_graph
from images_fixtures import make_png

from engine.core.errors import Refused
from engine.h3 import inputs as inputs_mod
from engine.h3 import pack_refs
from engine.h3 import prepare as prepare_mod
from engine.images import library as image_library
from engine.images.native import NATIVE_SCHEMA

MOUTH = {"19.value": "Mother speaks to <Audio 1>", "6.length": 141, "11.noise_seed": 20261029}
LIB = "lib-"  # test prompt_id convention: "lib-<sha256>" is a library approval of exactly that sha256


def approval_path(prompt_id: str) -> str:
    return f"/lib/_review/{prompt_id}/approvals/approval-v001.json"


@pytest.fixture()
def library_stub(monkeypatch):
    """Stub ``image_library.current_approval``: prompt_id ``lib-<sha>`` is a current accepted approval of ``<sha>``; else none.
    (The real reader is covered by the pack tests; this isolates the sha-bound check that pack_refs and the legacy path share.)"""
    def current(out, prompt_id):
        if not isinstance(prompt_id, str) or not prompt_id.startswith(LIB):
            return None
        return {"schema": image_library.APPROVAL_SCHEMA, "status": "accepted_library_image",
                "candidate_sha256": prompt_id[len(LIB):], "path": approval_path(prompt_id)}

    monkeypatch.setattr(pack_refs.image_library, "current_approval", current)


pytestmark = pytest.mark.usefixtures("library_stub")


class InputsWorld(H3World):
    """H3World + hand-written image receipts (candidate, approval, native) + full voice-bindings + a 2-face graph."""

    def __init__(self, tmp: Path) -> None:
        super().__init__(tmp)
        graph = template_graph()
        graph["32"] = {"class_type": "LoadImage", "inputs": {"image": "STALE-face2.png"}}
        graph["6"]["inputs"]["ref_images.ref_image_2"] = ["32", 0]
        self.template.write_text(json.dumps(graph), encoding="utf-8")
        self.images = self.root / "images"
        self._images()
        bindings = json.loads((self.voice / "voice-bindings.json").read_text("utf-8"))
        bindings["schema"] = "jjv/voice-bindings/v1"
        bindings["dialogue"][0]["audio"]["path"] = "assets/line.wav"
        (self.voice / "voice-bindings.json").write_text(json.dumps(bindings), encoding="utf-8")
        self.spec = self.tmp / "h3-spec.json"
        self.write_spec()
        self.set_cast({"alice": LIB + sha_file(self.world.alice), "mom-alice": LIB + sha_file(self.world.mom)})

    def set_cast(self, prompts: dict[str, str]) -> None:
        """Rewrite the cast file; ``prompts[character_id]`` = the library prompt_id approving that face (absent = unapproved)."""
        rows = []
        for cid, png in (("alice", self.world.alice), ("mom-alice", self.world.mom)):
            row = {"character_id": cid, "canonical_png": png.as_posix(), "canonical_sha256": sha_file(png)}
            if cid in prompts:
                row.update({"prompt_id": prompts[cid], "receipt": {"path": f"/lib/receipts/{cid}.json"},
                            "approval_record": approval_path(prompts[cid]), "approval": "approved"})
            rows.append(row)
        self.world.cast.write_text(json.dumps({"characters": rows}), encoding="utf-8")

    def _images(self, approved: bool = True) -> None:
        shot = self.images / SHOT
        source = make_png(shot / "candidates" / "source.png", (90, 80, 70), (1728, 960))
        full = sha_file(source)
        (shot / "candidates" / f"{full[:12]}.receipt.json").write_text(json.dumps({
            "schema": "jjv/image-receipt/v1", "episode_id": EP, "shot": SHOT, "created_at": 1.0,
            "output": {"path": source.as_posix(), "sha256": full}}), encoding="utf-8")
        approval = shot / "approvals" / "approval-v001.json"
        approval.parent.mkdir(parents=True)
        approval.write_text(json.dumps({"schema": "jjv/image-approval/v1", "episode_id": EP, "shot": SHOT,
                                        "candidate_sha256": full, "reviewer": "Kim"}), encoding="utf-8")
        native = shot / "native" / f"{SHOT}-native864-{full[:12]}.png"
        native.parent.mkdir(parents=True)
        native.write_bytes(self.anchor.read_bytes())
        self.native_receipt = native.with_suffix(".receipt.json")
        self.native_receipt.write_text(json.dumps({
            "schema": NATIVE_SCHEMA, "episode_id": EP, "shot": SHOT, "source": {"sha256": full},
            "native": {"path": native.as_posix(), "sha256": sha_file(native)},
            "anchor_approved": approved, "approval": approval.as_posix() if approved else None}), encoding="utf-8")
        self.native = native

    def spec_doc(self, **shot) -> dict:
        row = {"shot": SHOT, "mouth": {"19.value": MOUTH["19.value"]}, **shot}
        return {"schema": "jjv/h3-spec/v1", "episode_id": EP,
                "defaults": {"template": "assets/template.api.json", "anchor_ports": [["30", "image"]],
                             "wav_ports": [["7", "audio"]],
                             "faces": [{"role": "mother", "ports": [["31", "image"]]},
                                       {"role": "alice", "ports": [["32", "image"]]}],
                             "mouth": {"6.length": 141, "11.noise_seed": 20261029},
                             "editorial_node": "63", "sinks": {"native": "18"},
                             "output_ports": [["18", "filename_prefix"], ["63", "filename_prefix"]]},
                "shots": [row]}

    def write_spec(self, document: dict | None = None) -> None:
        self.spec.write_text(json.dumps(document or self.spec_doc()), encoding="utf-8")

    def build(self, out: Path | None = None, *, legacy: bool = True) -> dict:
        """``legacy=True`` (default here): the cast-face path, i.e. ``--legacy-cast-faces``; these tests have no anchor pack."""
        return inputs_mod.write_inputs(self.ctx(), self.spec, out or self.tmp / "built-inputs.json",
                                       images=self.images, voice=self.voice, cast_file=self.world.cast,
                                       mapping={"mother": "mom-alice"}, legacy_cast_faces=legacy)


def _hand_manifest(world: InputsWorld, provenance: dict | None = None) -> Path:
    """What a person would have typed for the same bytes: the M7 shape, shas copied by hand."""
    def asset(path: Path, ports=None) -> dict:
        return {"path": path.as_posix(), "sha256": sha_file(path), **({"ports": ports} if ports else {})}
    row = {"shot": SHOT, "template": asset(world.template), "anchor": asset(world.native, [["30", "image"]]),
           "wav": asset(world.wav, [["7", "audio"]]),
           "faces": [{**asset(world.world.mom, [["31", "image"]]), "character_id": "mom-alice"},
                     {**asset(world.world.alice, [["32", "image"]]), "character_id": "alice"}],
           "mouth": MOUTH, "editorial_node": "63", "sinks": {"native": "18"},
           "output_ports": [["18", "filename_prefix"], ["63", "filename_prefix"]]}
    path = world.tmp / "hand-inputs.json"
    path.write_text(json.dumps({"schema": "jjv/h3-inputs/v1", "episode_id": EP, "domain": world.world.domain,
                                "voice_dir": "voice", "shots": [row],
                                **({"provenance": provenance} if provenance else {})}), encoding="utf-8")
    return path


def test_built_manifest_binds_receipt_shas_and_prepares_to_the_hand_manifest_graph(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    summary = world.build()
    manifest = json.loads(Path(summary["inputs"]).read_text("utf-8"))
    assert "legacy_voice" not in manifest and manifest["voice_dir"] == "voice"
    row = manifest["shots"][0]
    for item in [row["template"], row["anchor"], row["wav"], *row["faces"]]:
        assert sha_file(world.root / item["path"]) == item["sha256"]
    assert row["anchor"]["sha256"] == sha_file(world.native) and row["wav"]["sha256"] == sha_file(world.wav)
    assert [f["sha256"] for f in row["faces"]] == [sha_file(world.world.mom), sha_file(world.world.alice)]
    assert row["mouth"] == MOUTH                                     # defaults merged, per-shot value kept
    assert manifest["provenance"]["shots"][SHOT]["native_receipt"]["sha256"] == sha_file(world.native_receipt)
    built = prepare_mod.prepare(world.ctx(), Path(summary["inputs"]), tmp_path / "h3-built")
    hand = prepare_mod.prepare(world.ctx(), _hand_manifest(world, manifest["provenance"]), tmp_path / "h3-hand")
    assert built["shots"][0]["graph_sha256"] == hand["shots"][0]["graph_sha256"] == summary["shots"][0]["graph_sha256"]


def _refused(world: InputsWorld, match: str) -> None:
    out = world.tmp / "refused-inputs.json"
    with pytest.raises(Refused, match=match):
        world.build(out)
    assert not out.exists()


def test_missing_image_approval_or_a_diagnostic_native_copy_is_refused(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    (world.images / SHOT / "approvals" / "approval-v001.json").unlink()
    _refused(world, "NO_IMAGE_APPROVAL")
    other = InputsWorld(tmp_path / "b")
    body = json.loads(other.native_receipt.read_text("utf-8"))
    other.native_receipt.write_text(json.dumps({**body, "anchor_approved": False}), encoding="utf-8")
    _refused(other, "NO_NATIVE_ANCHOR")


def test_unapproved_voice_is_refused_and_legacy_is_never_written(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    world.revoke_approval()
    _refused(world, "E_LISTEN_APPROVAL")
    world = InputsWorld(tmp_path / "b")
    world.write_spec({**world.spec_doc(), "legacy_voice": True})
    _refused(world, "LEGACY_REFUSED")


@pytest.mark.parametrize("shot, match", [
    ({"anchor": {"sha256": "0" * 64}}, "unknown"),                               # a hand-typed sha is not spec data
    ({"faces": [{"role": "mother", "ports": [["31", "image"]]}]}, "FACE_MISSING"),  # listener alice has no face
    ({"shot": "S99_Z"}, "UNKNOWN_SHOT"),
    ({"output_ports": [["7", "audio"]]}, "output port overwrites media"),     # prepare's own refusal, before write
])
def test_bad_spec_rows_are_refused_before_any_write(tmp_path, shot, match) -> None:
    world = InputsWorld(tmp_path)
    world.write_spec(world.spec_doc(**shot))
    _refused(world, match)


def test_missing_anchor_pack_is_refused_without_the_legacy_flag(tmp_path) -> None:
    world = InputsWorld(tmp_path)  # approved faces, but no anchor pack and no --legacy-cast-faces
    out = world.tmp / "no-pack-inputs.json"
    with pytest.raises(Refused, match=inputs_mod.ANCHOR_PACK_MISSING):
        world.build(out, legacy=False)
    assert not out.exists()


def test_legacy_flag_refuses_a_cast_face_without_a_library_approval(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    world.set_cast({"mom-alice": LIB + sha_file(world.world.mom)})  # the mother is approved, alice is not
    out = world.tmp / "unapproved-face.json"
    with pytest.raises(Refused, match=pack_refs.NOT_APPROVED):
        world.build(out)
    assert not out.exists()


def test_legacy_flag_refuses_a_cast_face_approved_for_another_sha(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    world.set_cast({"alice": LIB + "f" * 64, "mom-alice": LIB + sha_file(world.world.mom)})
    out = world.tmp / "mismatch-face.json"
    with pytest.raises(Refused, match=pack_refs.APPROVAL_SHA_MISMATCH):
        world.build(out)
    assert not out.exists()


def test_legacy_flag_with_approved_faces_passes_and_records_the_legacy_path(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    summary = world.build()
    manifest = json.loads(Path(summary["inputs"]).read_text("utf-8"))
    assert summary["legacy_cast_faces"] == [SHOT] and summary["shots"][0]["legacy_cast_faces"] is True
    assert manifest["provenance"]["legacy_cast_faces"] == {"enabled": True, "shots": [SHOT]}
    assert summary["warnings"][0].startswith("ANCHOR_PACK_MISSING") and "LEGACY" in summary["warnings"][0]
    assert [f["sha256"] for f in manifest["shots"][0]["faces"]] == [sha_file(world.world.mom), sha_file(world.world.alice)]
    prepare_mod.prepare(world.ctx(), Path(summary["inputs"]), tmp_path / "h3-legacy")  # the manifest still prepares


def test_cli_sub_verb_writes_once(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    out = tmp_path / "cli-inputs.json"
    argv = ["inputs", "--episode", str(world.root), "--machine", str(world.world.machine_path), "--spec", str(world.spec),
            "--images", str(world.images), "--voice", str(world.voice), "--cast", str(world.world.cast),
            "--map", "mother=mom-alice", "--out", str(out), "--legacy-cast-faces"]
    code, summary = run_h3(argv)
    assert code == 0 and summary["inputs_sha256"] == sha_file(out)
    first = sha_file(out)
    assert run_h3(argv)[0] == 0                                         # same bytes: idempotent
    world.write_spec(world.spec_doc(mouth={"19.value": "changed"}))
    code, summary = run_h3(argv)
    assert code == 1 and summary["ok"] is False                       # write-once: a different manifest is refused
    assert sha_file(out) == first


def test_cli_without_a_pack_or_the_flag_is_refused_and_writes_nothing(tmp_path) -> None:
    world = InputsWorld(tmp_path)
    out = tmp_path / "cli-nopack.json"
    code, _ = run_h3(["inputs", "--episode", str(world.root), "--machine", str(world.world.machine_path), "--spec", str(world.spec),
                      "--images", str(world.images), "--voice", str(world.voice), "--cast", str(world.world.cast),
                      "--map", "mother=mom-alice", "--out", str(out)])
    assert code == 1 and not out.exists()


def test_inputs_module_is_small_and_neutral() -> None:
    text = Path(inputs_mod.__file__).read_text(encoding="utf-8")
    assert len(text.splitlines()) < 400
    for token in ("jenniejoy", "newtecons", "ep04", "04-milk", "S02_A"):
        assert token not in text.lower(), token
