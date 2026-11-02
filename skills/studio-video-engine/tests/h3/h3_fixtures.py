"""World for the H3 tests: a tiny cartoon episode, a template graph, approved voice evidence, a fake ComfyUI.

Nothing here touches a GPU, the network beyond 127.0.0.1, the real lock or any production folder.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from contextlib import redirect_stdout
from pathlib import Path

from fake_comfy import FakeComfy
from images_fixtures import World, make_png

EP = "t-ep"
SHOT = "S02_A"
FACE_ID = "mom-alice"  # the one face of an H3World row; the cast file binds it to a library approval
LIB = "lib-"  # test convention for library_stub: prompt_id "lib-<sha256>" is a current approval of exactly that sha256


def approval_path(prompt_id: str) -> str:
    return f"/lib/_review/{prompt_id}/approvals/approval-v001.json"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(Path(path).read_bytes())


def template_graph() -> dict:
    return {
        "30": {"class_type": "LoadImage", "inputs": {"image": "STALE-scene.png"}},
        "31": {"class_type": "LoadImage", "inputs": {"image": "STALE-face.png"}},
        "7": {"class_type": "LoadAudio", "inputs": {"audio": "STALE.wav"}},
        "19": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "template prompt"}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
        "6": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "prompt": ["19", 0], "length": 141, "ref_images.ref_image_0": ["30", 0],
            "ref_images.ref_image_1": ["31", 0], "ref_audios.ref_audio_0": ["7", 0]}},
        "17": {"class_type": "CreateVideo", "inputs": {"images": ["6", 0], "fps": 24, "audio": ["7", 0]}},
        "18": {"class_type": "SaveVideo", "inputs": {"video": ["17", 0], "filename_prefix": "x"}},
        "63": {"class_type": "SaveVideo", "inputs": {"video": ["17", 0], "filename_prefix": "y"}},
    }


def _ref(root: Path, path: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha_file(path)}


class H3World:
    """Episode + approved voice evidence + manifest.  ``comfy_url`` points at a FakeComfy when given."""

    def __init__(self, tmp: Path, comfy_url: str = "http://127.0.0.1:1", domain: str = "jenniejoy_cartoon_3d",
                 legacy_cast: bool = True) -> None:
        self.world = World(tmp, domain=domain, comfy_url=comfy_url)
        self.root = self.world.root
        self.tmp = Path(tmp)
        self.out = self.tmp / "h3out"
        (self.root / "assets").mkdir()
        self.template = self.root / "assets" / "template.api.json"
        self.template.write_text(json.dumps(template_graph()), encoding="utf-8")
        self.anchor = make_png(self.root / "assets" / "anchor.png", (10, 20, 30), (864, 480))
        self.face = make_png(self.root / "assets" / "face.png", (200, 10, 10), (64, 64))
        self.wav = self._file("assets/line.wav", b"RIFF-receipt-wav")
        self.native_wav = self._file("assets/native.wav", b"RIFF-native-take")
        self.trimmed_wav = self._file("assets/trimmed.wav", b"RIFF-trimmed-later")
        self.voice = self.root / "voice"
        self._voice_evidence()
        self.manifest = self.tmp / "h3-inputs.json"
        # legacy_cast=True: the manifest carries an explicit legacy_cast_faces approval record (no anchor pack in this world);
        # legacy_cast=False: neither an anchor pack nor that record, so prepare must refuse ANCHOR_PACK_MISSING.
        self.legacy_cast = legacy_cast
        self.write_manifest()

    def _file(self, rel: str, data: bytes) -> Path:
        path = self.root / rel
        path.write_bytes(data)
        return path

    def _voice_evidence(self, approve: bool = True) -> None:
        rid, req_sha = "req-1", "r" * 64
        self.voice.mkdir(exist_ok=True)
        (self.voice / "voice-plan.json").write_text(json.dumps(
            {"episode_id": EP, "jobs": [{"request_id": rid, "request_sha256": req_sha}]}), encoding="utf-8")
        (self.voice / "voice-bindings.json").write_text(json.dumps({
            "episode_id": EP, "dialogue": [{"id": SHOT, "request_id": rid, "audio": {"sha256": sha_file(self.wav)}}]}),
            encoding="utf-8")
        (self.voice / "voice-finalize.json").write_text(json.dumps({"entries": [{
            "request_id": rid, "category": "dialogue", "native": {"sha256": sha_file(self.native_wav)},
            "base": {"sha256": sha_file(self.native_wav)}, "editorial": {"sha256": sha_file(self.trimmed_wav)},
            "receipt_wav": {"sha256": sha_file(self.wav)}}]}), encoding="utf-8")
        if approve:
            approval = self.voice / "jobs" / rid / "approval.json"
            approval.parent.mkdir(parents=True, exist_ok=True)
            approval.write_text(json.dumps({
                "schema": "jjv/voice-approval/v1", "request_id": rid, "request_sha256": req_sha,
                "subject": {"kind": "native_take", "sha256": sha_file(self.native_wav)},
                "approved_by": "Kim", "note": "listened"}), encoding="utf-8")

    def revoke_approval(self) -> None:
        (self.voice / "jobs" / "req-1" / "approval.json").unlink()

    def row(self, **overrides) -> dict:
        def asset(path: Path, ports=None) -> dict:
            return {"path": path.relative_to(self.root).as_posix(), "sha256": sha_file(path),
                    **({"ports": ports} if ports else {})}
        row = {"shot": SHOT, "template": asset(self.template),
               "anchor": asset(self.anchor, [["30", "image"]]), "wav": asset(self.wav, [["7", "audio"]]),
               "faces": [{**asset(self.face, [["31", "image"]]), "character_id": FACE_ID}],
               "mouth": {"19.value": "Alice speaks to <Audio 1>", "6.length": 141, "11.noise_seed": 20261029},
               "editorial_node": "63", "sinks": {"native": "18"},
               "output_ports": [["18", "filename_prefix"], ["63", "filename_prefix"]]}
        row.update(overrides)
        return row

    def write_manifest(self, rows: list[dict] | None = None, **top) -> None:
        shots = rows if rows is not None else [self.row()]
        legacy = self._legacy_provenance([row.get("shot") for row in shots])
        document = {"schema": "jjv/h3-inputs/v1", "episode_id": EP, "domain": self.world.domain,
                    "voice_dir": "voice", "shots": shots,
                    **({"provenance": legacy} if legacy else {}), **top}
        self.manifest.write_text(json.dumps(document), encoding="utf-8")

    def _legacy_provenance(self, shots: list) -> dict | None:
        """The explicit ``legacy_cast_faces`` approval record that prepare re-reads, for every shot of the manifest.

        This world has no anchor pack, so each shot is approved on the legacy path: its scene anchor is the native receipt
        of an approved image candidate naming ``assets/anchor.png`` by sha, and the one face is approved by a sha-bound
        library record (``lib-<sha>``, answered by the ``library_stub`` fixture). Unsafe shot names get no record."""
        if not self.legacy_cast:
            return None
        from engine.images.native import NATIVE_SCHEMA

        images = self.root / "legacy-images"
        cast = self.root / "legacy-cast.json"
        face_prompt = LIB + sha_file(self.face)
        cast.write_text(json.dumps({"characters": [{
            "character_id": FACE_ID, "canonical_png": self.face.as_posix(), "canonical_sha256": sha_file(self.face),
            "prompt_id": face_prompt, "receipt": {"path": f"/lib/receipts/{FACE_ID}.json"},
            "approval_record": approval_path(face_prompt), "approval": "approved"}]}), encoding="utf-8")
        entries = {}
        for shot in shots:
            if isinstance(shot, str) and re.fullmatch(r"[A-Za-z0-9_]+", shot):
                entries[shot] = self._legacy_shot(images, shot, NATIVE_SCHEMA)
        return {"legacy_cast_faces": {"enabled": True, "shots": sorted(entries)}, "cast": _ref(self.root, cast),
                "images_dir": images.as_posix(), "shots": entries}

    def _legacy_shot(self, images: Path, shot: str, native_schema: str) -> dict:
        folder = images / shot
        source = make_png(folder / "candidates" / "source.png", (90, 80, 70), (1728, 960))
        full = sha_file(source)
        (folder / "candidates").mkdir(parents=True, exist_ok=True)
        (folder / "candidates" / f"{full[:12]}.receipt.json").write_text(json.dumps({
            "schema": "jjv/image-receipt/v1", "episode_id": EP, "shot": shot, "created_at": 1.0,
            "output": {"path": source.as_posix(), "sha256": full}}), encoding="utf-8")
        approval = folder / "approvals" / "approval-v001.json"
        approval.parent.mkdir(parents=True, exist_ok=True)
        approval.write_text(json.dumps({"schema": "jjv/image-approval/v1", "episode_id": EP, "shot": shot,
                                        "candidate_sha256": full, "reviewer": "Kim"}), encoding="utf-8")
        native = folder / "native" / f"{shot}-native864-{full[:12]}.receipt.json"
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_text(json.dumps({
            "schema": native_schema, "episode_id": EP, "shot": shot, "source": {"sha256": full},
            "native": {"path": self.anchor.as_posix(), "sha256": sha_file(self.anchor)},
            "anchor_approved": True, "approval": approval.as_posix()}), encoding="utf-8")
        return {"image_approval": _ref(self.root, approval), "native_receipt": _ref(self.root, native)}

    def ctx(self):
        return self.world.ctx()

    def settings(self):
        from engine.comfy.settings import settings_from_machine

        return settings_from_machine(self.world.machine).with_overrides(poll_seconds=0.05, lock_timeout_seconds=2.0)

    def prepare(self, out: Path | None = None, shots=None) -> dict:
        from engine.h3 import prepare

        return prepare.prepare(self.ctx(), self.manifest, out or self.out, shots=shots)


class FakeProbe:
    """DockerProbe stand-in: a running container with a fixed StartedAt."""

    def state(self, container: str):
        from engine.comfy.docker_probe import ContainerState

        return ContainerState(started_at=1.0, started_at_text="2026-10-28T00:00:00Z", running=True, restart_count=0)


def ok_ps(name: str) -> str:
    return f"{name}|running|Up 5 minutes\n"


def fake_with_video(world: H3World, fake: FakeComfy) -> list[str]:
    """auto-complete POSTs and write one mp4 per SaveVideo node under the fake ComfyUI output dir."""
    fake.auto_complete = True
    written: list[str] = []

    def on_post(payload: dict, prompt_id: str) -> dict:
        outputs = {}
        for node in ("18", "63"):
            name = f"{prompt_id}-{node}.mp4"
            (world.world.comfy_root / "output" / name).write_bytes(f"video-{prompt_id}-{node}".encode())
            outputs[node] = {"videos": [{"filename": name, "subfolder": "", "type": "output"}]}
            written.append(name)
        return outputs

    fake.on_post = on_post
    return written


def run_h3(argv: list[str]) -> tuple[int, dict]:
    """Through the real argparse wiring, in process; returns (exit code, parsed stdout JSON or {})."""
    from engine.core.errors import EngineError, exit_code_for
    from engine.h3 import cli

    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    buffer = io.StringIO()
    code = 0
    with redirect_stdout(buffer):
        try:
            code = cli.run_h3(parser.parse_args(["h3", *argv]))
        except EngineError as error:
            code = exit_code_for(error)
            print(json.dumps({"ok": False, "error": str(error)}))
    text = buffer.getvalue().strip()
    return code, json.loads(text) if text.startswith("{") else {}


__all__ = ["H3World", "FakeProbe", "ok_ps", "fake_with_video", "run_h3", "sha_file", "EP", "SHOT"]
