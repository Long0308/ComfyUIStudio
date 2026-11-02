"""Shared world for the layout/images tests: a tiny episode, a cast manifest, a machine file, PNG helpers.

Nothing here touches the network, a GPU, the real lock path or any production folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

SKILL_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = SKILL_ROOT.parent / "comfyui-blender" / "assets" / "examples"
SHOTS = [("S01_A", "cut", "mother", "alice"), ("S01_B", "carry", "alice", "mother"),
         ("S02_A", "cut", "mother", "alice"), ("S03_A", "cut", "alice", "mother")]
CARTOON, LIVE = "jenniejoy_cartoon_3d", "newtecons_live_action"


def write_rollout(home: Path, session: str, name: str) -> Path:
    """A fake Codex rollout of ``session`` under ``<home>/sessions`` that names ``name`` (N25c provenance)."""
    path = home / "sessions" / "2026" / "10" / "30" / f"rollout-2026-10-30T00-00-00-{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"item": "saved generated_images/' + session + '/' + name + '"}', "utf-8")
    return path


def make_png(path: Path, color=(120, 160, 90), size=(160, 90)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


def sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class World:
    def __init__(self, tmp: Path, domain: str = CARTOON, comfy_url: str = "http://127.0.0.1:1") -> None:
        self.tmp, self.domain = Path(tmp), domain
        self.root = self.tmp / "ep"
        engine = self.root / "engine"
        engine.mkdir(parents=True)
        (engine / "episode.json").write_text(json.dumps(
            {"episode_id": "t-ep", "domain": domain, "files": {"shots": "shots.json"}}), encoding="utf-8")
        (engine / "shots.json").write_text(json.dumps({"shots": [
            {"shot": s, "entry": {"kind": k}, "speaker": a, "listener": b} for s, k, a, b in SHOTS]}), encoding="utf-8")
        self.cast_dir = self.tmp / "cast"
        self.alice = make_png(self.cast_dir / "alice.png", (240, 200, 160))
        self.mom = make_png(self.cast_dir / "mom.png", (200, 120, 120))
        self.cast = self.cast_dir / "cast.json"
        self.cast.write_text(json.dumps({"characters": [
            {"character_id": "alice", "canonical_png": self.alice.as_posix(), "canonical_sha256": sha(self.alice)},
            {"character_id": "mom-alice", "canonical_png": self.mom.as_posix(), "canonical_sha256": sha(self.mom)}]}),
            encoding="utf-8")
        self.comfy_root = self.tmp / "comfy"
        (self.comfy_root / "input").mkdir(parents=True)
        (self.comfy_root / "output").mkdir(parents=True)
        self.lock = self.tmp / "gpu.lock"
        self.machine_path = self.tmp / "machine.json"
        self.machine = {"comfy": {"url": comfy_url, "root": str(self.comfy_root), "output_dir": str(self.comfy_root / "output"),
                                  "container": "fake"}, "gpu_lock_path": str(self.lock)}
        self.write_machine()

    def write_machine(self) -> None:
        self.machine_path.write_text(json.dumps(self.machine), encoding="utf-8")

    def ctx(self):
        from engine.layout.context import load_context

        return load_context(str(self.root), self.machine_path)

    def plan_layout(self, out: Path) -> dict:
        from engine.layout import plan

        return plan.build_plan(self.ctx(), out, cast_file=self.cast, mapping={"mother": "mom-alice"}, allow_unbound=False)

    def fill_briefs(self, layout: Path) -> None:
        """Replace every scaffold brief by the real S01_A example (valid, final status) so check can pass."""
        example = json.loads((EXAMPLES / "scene-layout.example.ep04-S01_A.cartoon.json").read_text(encoding="utf-8"))
        plan = json.loads((layout / "layout-plan.json").read_text(encoding="utf-8"))
        for row in plan["shots"]:
            if row["brief"]:
                brief = {**example, "brief_id": f"t-{row['shot']}"}
                (layout / row["brief"]).write_text(json.dumps(brief), encoding="utf-8")

    def images_plan(self, out: Path, layout: Path, shots=("S01_A",)) -> Path:
        """A guide + placement text per shot made by hand (no Blender), then `images plan` through the real CLI."""
        from engine.images import cli

        (layout / "placement").mkdir(exist_ok=True)
        args = ["plan", "--episode", str(self.root), "--out", str(out), "--machine", str(self.machine_path), "--layout", str(layout)]
        for shot in shots:
            guide = make_png(self.tmp / "guides" / f"{shot}.png", (90, 110, 150), (160, 90))
            (layout / "placement" / f"{shot}.txt").write_text("Mother seated on the bench, lower centre-right\n", encoding="utf-8")
            args += ["--shot", shot, "--guide", f"{shot}={guide}"]
        code, _ = run_images(args)
        assert code == 0
        return out


def run_images(argv: list[str], capsys=None) -> tuple[int, dict]:
    """Through the real argparse wiring, in process; returns (exit code, parsed stdout JSON or {})."""
    import io
    from contextlib import redirect_stdout

    from engine.core.errors import EngineError, exit_code_for
    from engine.images import cli

    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    buffer = io.StringIO()
    code = 0
    with redirect_stdout(buffer):
        try:
            code = cli.run_images(parser.parse_args(["images", *argv]))
        except EngineError as error:
            code = exit_code_for(error)
            print(json.dumps({"ok": False, "error": str(error), "evidence": error.evidence}, default=str))
    text = buffer.getvalue().strip()
    return code, json.loads(text) if text else {}


def run_layout(argv: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout

    from engine.core.errors import EngineError, exit_code_for
    from engine.layout import cli

    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage", required=True))
    buffer = io.StringIO()
    code = 0
    with redirect_stdout(buffer):
        try:
            code = cli.run_layout(parser.parse_args(["layout", *argv]))
        except EngineError as error:
            code = exit_code_for(error)
            print(json.dumps({"ok": False, "error": str(error)}))
    text = buffer.getvalue().strip()
    return code, json.loads(text) if text else {}


def python_cmd(script: Path) -> list[str]:
    return [sys.executable, str(script)]
