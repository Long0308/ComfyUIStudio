"""N52b (queue gate fail-closed) + N25c-exact (rollout match exact) - cases probed by critic N63."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
for p in (SKILL, SKILL / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.core.errors import Refused  # noqa: E402
from engine.core.io import sha256_bytes  # noqa: E402
from engine.images import adopt, codex  # noqa: E402
from images_fixtures import make_png  # noqa: E402
from test_images_n25 import live_flow  # noqa: E402
from test_images_n25b import adopt_args  # noqa: E402

UUID = "019a3c1e-1111-7222-8333-944455556666"
OTHER = "019a3c1e-9999-7222-8333-944455556666"
SHA = sha256_bytes(b"hello")


def real_rollout(home: Path, text: str, session: str = UUID, suffix: str = ".jsonl") -> Path:
    path = home / "sessions" / "2026" / "10" / "30" / f"rollout-2026-10-30T09-00-00-{session}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    if suffix.endswith(".zst"):
        from compression import zstd
        data = zstd.compress(data)
    path.write_bytes(data)
    return path


def put(png: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(png, dst)
    return dst


def named(name: str) -> str:
    return json.dumps({"path": f"generated_images/{UUID}/{name}"})


def adopt_case(tmp_path, rel: str, rollout_text: str, rollout_session: str = UUID, seed=(1, 2, 3)):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "comfy.png", seed, (1672, 941))
    real_rollout(tmp_path / "home", rollout_text, rollout_session)
    src = put(png, tmp_path / "home" / "generated_images" / rel)
    return adopt_args(flow, png, src)


def test_adopt_exact_session_and_file_is_accepted(tmp_path):
    code, out = adopt_case(tmp_path, f"{UUID}/exec-001.png", named("exec-001.png"))
    assert code == 0, out


@pytest.mark.parametrize("rel,text", [
    ("0/1.png", named("exec-001.png")),                       # substring session + substring file
    ("-/.png", named("exec-abc.png")),                        # ".png" name
    ("[0-9]/exec-001.png", named("exec-001.png")),            # glob char class as session
])
def test_adopt_substring_or_glob_is_refused(tmp_path, rel, text):
    code, out = adopt_case(tmp_path, rel, text, seed=(1, 2, 4))
    assert code == 1, out


def test_adopt_file_named_only_in_another_session_path_is_refused(tmp_path):
    # rollout of UUID mentions OTHER/exec-001.png only; source is UUID/exec-001.png
    text = json.dumps({"path": f"generated_images/{OTHER}/exec-001.png"})
    code, out = adopt_case(tmp_path, f"{UUID}/exec-001.png", text, seed=(1, 2, 5))
    assert code == 1, out


def test_adopt_partial_file_name_is_refused(tmp_path):
    code, out = adopt_case(tmp_path, f"{UUID}/1.png", named("exec-001.png"), seed=(1, 2, 6))
    assert code == 1, out


def test_find_rollout_unit(tmp_path):
    home = tmp_path / "h"
    real_rollout(home, named("a.png"))
    assert adopt.find_rollout(home, UUID, "a.png") is not None
    assert adopt.find_rollout(home, UUID[:8], "a.png") is None          # prefix of the session
    assert adopt.find_rollout(home, "*", "a.png") is None
    assert adopt.find_rollout(home, UUID, "a.pn") is None
    assert adopt.find_rollout(home, OTHER, "a.png") is None
    stray = home / "sessions" / f"rollout-x-{UUID}.jsonl.bak"
    stray.write_text(named("b.png"), "utf-8")
    assert adopt.find_rollout(home, UUID, "b.png") is None              # wrong extension


def test_adopt_zst_rollout_still_read(tmp_path):
    flow = live_flow(tmp_path, tmp_path / "home")
    png = make_png(tmp_path / "comfy.png", (1, 2, 8), (1672, 941))
    real_rollout(tmp_path / "home", named("exec-001.png"), suffix=".jsonl.zst")
    src = put(png, tmp_path / "home" / "generated_images" / UUID / "exec-001.png")
    code, out = adopt_args(flow, png, src)
    assert code == 0, out


# ---------------- N52b ----------------

def batch_dir(tmp_path: Path, queues: dict, pid: str = "P1", text: str = "hello") -> Path:
    d = tmp_path / "batches"
    d.mkdir(parents=True, exist_ok=True)
    ref = make_png(d / "ref.png", (5, 5, 5), (64, 64))
    batch = d / "batch-x.json"
    batch.write_text(json.dumps([{"prompt_id": pid, "prompt_text": text,
                                  "ref_images": [{"path": str(ref), "role": "identity"}]}]), "utf-8")
    for name, rows in queues.items():
        (d / name).write_text(rows if isinstance(rows, str) else json.dumps(rows), "utf-8")
    return batch


def row(allowed, pid="P1", sha=SHA):
    r = {"prompt_id": pid, "prompt_sha256": sha}
    if allowed != "MISSING":
        r["dispatch_allowed"] = allowed
    return r


def real_gate(tmp_path, queues):
    items = codex.load_batch(batch_dir(tmp_path, queues), allowed=[tmp_path], forbidden=[])
    for it in items:
        codex._refuse_blocked(it)
    return items


@pytest.mark.parametrize("queues", [
    {"queue-a.json": [row(False)]},
    {"queue-a.json": [row("false")]},
    {"queue-a.json": [row("true")]},
    {"queue-a.json": [row(None)]},
    {"queue-a.json": [row(0)]},
    {"queue-a.json": [row(1)]},
    {"queue-a.json": [row("MISSING")]},
    {"queue-a.json": [row(True, pid="OTHER")]},                       # row missing for this id
    {"queue-a.json": []},                                             # empty queue, no row
    {"queue-a.json": [row(False)], "queue-zz.json": [row(True)]},     # later true must not override
    {"queue-a.json": [row(True)], "queue-zz.json": [row(True)]},      # duplicate across files, both true
    {"queue-a.json": [row(False), row(True)]},                        # duplicate in one file
])
def test_n52b_real_submit_is_refused(tmp_path, queues):
    with pytest.raises(Refused):
        real_gate(tmp_path, queues)


def test_n52b_queues_with_different_sha_are_refused_at_load(tmp_path):
    with pytest.raises(Refused):
        real_gate(tmp_path, {"queue-a.json": [row(True, sha="0" * 64)], "queue-zz.json": [row(True)]})


def test_n52b_boolean_true_single_row_is_allowed(tmp_path):
    assert real_gate(tmp_path, {"queue-a.json": [row(True)]})[0]["dispatch_allowed"] is True


def test_n52b_other_queue_without_the_id_but_unique_true_is_allowed(tmp_path):
    assert real_gate(tmp_path, {"queue-a.json": [row(True)], "queue-b.json": [row(False, pid="OTHER")]})


def test_n52b_no_queue_keeps_old_behaviour(tmp_path):
    assert real_gate(tmp_path, {})[0]["dispatch_allowed"] is None


def test_n52b_dry_run_plans_and_reports_the_refusal(tmp_path):
    items = codex.load_batch(batch_dir(tmp_path, {"queue-a.json": [row("false")]}), allowed=[tmp_path], forbidden=[])
    assert items[0]["queue_present"] is True and items[0]["dispatch_allowed"] == "false"
