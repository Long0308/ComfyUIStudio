"""N52c: a provenance_required domain (NEWTECONS) refuses a REAL codex-exec submit unless a queue gates it."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
for p in (SKILL, SKILL / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.core.errors import Refused  # noqa: E402
from engine.images import codex  # noqa: E402
from engine.images.codex_queue import provenance_problem  # noqa: E402
from images_fixtures import LIVE  # noqa: E402
from test_images_n23fix import Lib  # noqa: E402


def write_true_queue(lib: Lib, batch: Path, extra_rows: int = 0, allowed=True) -> None:
    """Queue shaped like queue-r005b.json: one row per batch item plus many rows of other batches."""
    rows = []
    for it in json.loads(batch.read_text("utf-8")):
        rows.append({"prompt_id": it["prompt_id"], "dispatch_allowed": allowed, "domain": LIVE,
                     "prompt_sha256": hashlib.sha256(it["prompt_text"].encode("utf-8")).hexdigest()})
    rows += [{"prompt_id": f"other_{i}", "dispatch_allowed": True, "domain": LIVE, "prompt_sha256": "0" * 64} for i in range(extra_rows)]
    (batch.parent / "queue-r005b.json").write_text(json.dumps(rows), encoding="utf-8")


def no_job_started(lib: Lib) -> bool:
    return not lib.lib_out.exists() and not lib.calls("acct1") and not lib.calls("acct2")


def test_real_library_submit_without_queue_is_refused_for_provenance_domain(tmp_path):
    lib = Lib(tmp_path)
    with pytest.raises(Refused, match="provenance_required"):
        lib.run(lib.batch_file(auto_queue=False))
    assert no_job_started(lib)


def test_real_library_submit_with_boolean_true_queue_still_passes(tmp_path):
    lib = Lib(tmp_path)
    batch = lib.batch_file(auto_queue=False)
    write_true_queue(lib, batch, extra_rows=158)
    out = lib.run(batch)
    assert out["submitted"] is True and out["n"] == 2


def test_real_submit_with_false_queue_row_is_still_refused(tmp_path):
    lib = Lib(tmp_path)
    batch = lib.batch_file(auto_queue=False)
    write_true_queue(lib, batch, allowed="true")
    with pytest.raises(Refused):
        lib.run(batch)
    assert no_job_started(lib)


def test_real_prompt_file_path_is_refused_for_provenance_domain(tmp_path):
    lib = Lib(tmp_path)
    prompt = tmp_path / "p.txt"
    prompt.write_text("x", encoding="utf-8")
    with pytest.raises(Refused, match="--prompt-batch"):
        codex.submit_many(lib.world.ctx(), tmp_path / "out", "S01_A", prompt, lib.accounts, n=2,
                          codex_cmd=["x"], state_path=lib.state)
    assert not (tmp_path / "out").exists()


def test_dry_run_without_queue_plans_and_shows_the_gate(tmp_path):
    lib = Lib(tmp_path)
    out = lib.run(lib.batch_file(auto_queue=False), dry_run=True)
    assert out["dry_run"] is True and out["n"] == 2
    assert all("REAL SUBMIT WOULD BE REFUSED" in t["dispatch_gate"] for t in out["takes"])
    assert no_job_started(lib)


def test_other_domain_behaviour_is_unchanged():
    item = {"prompt_id": "P", "queue_present": False, "dispatch_allowed": None}
    assert provenance_problem(item, False) is None and provenance_problem(None, False) is None
    codex._refuse_blocked(item)  # default flag False: old behaviour, no queue accepted
    with pytest.raises(Refused, match="provenance_required"):
        codex._refuse_blocked(item, True)
