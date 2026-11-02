"""N95: manual adopt binds the bytes it verified, not the mutable source path."""

from __future__ import annotations

from pathlib import Path

from engine.core.io import sha256_file
from engine.images import adopt as adopt_mod
from images_fixtures import make_png, write_rollout
from test_images_n25 import live_flow
from test_images_n25b import adopt_args

SESSION = "019a3c1e-0000-7000-8000-00000000000a"


def test_adopt_refuses_a_source_swapped_between_verification_and_register(tmp_path, monkeypatch):
    flow = live_flow(tmp_path, tmp_path / "home")
    verified = make_png(tmp_path / "verified.png", (1, 2, 3), (1672, 941))
    replacement = make_png(tmp_path / "replacement.png", (9, 8, 7), (1672, 941))
    source = tmp_path / "home" / "generated_images" / SESSION / "exec-1.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(verified.read_bytes())
    write_rollout(tmp_path / "home", SESSION, source.name)
    verified_sha = sha256_file(verified)
    replacement_sha = sha256_file(replacement)
    real_register = adopt_mod.register

    def swap_then_register(*args, **kwargs):
        verified.write_bytes(replacement.read_bytes())
        return real_register(*args, **kwargs)

    monkeypatch.setattr(adopt_mod, "register", swap_then_register)
    code, out = adopt_args(flow, verified, source)

    assert code == 1, out
    assert verified_sha in out["error"] and replacement_sha in out["error"]
    staged = Path(out["evidence"]["staged_path"])
    assert str(staged) in out["error"]
    assert staged.parent == flow.out / "S01_A" / "candidates"
    assert staged.is_file() and staged.read_bytes() == replacement.read_bytes()
    assert sha256_file(staged) == replacement_sha
    assert not list(staged.parent.glob("*.png"))
    assert not list(staged.parent.glob("*.receipt.json"))
