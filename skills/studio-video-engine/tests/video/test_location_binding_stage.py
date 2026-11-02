import json
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
import pytest
from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.video.anchor_refs import location_refs
from engine.h3 import pack_refs

@pytest.fixture
def scratch():
    path = Path(__file__).resolve().parents[2] / "scratch" / uuid4().hex
    path.mkdir(parents=True)
    return path

def test_receipt_id_and_current_approval_reach_h3(scratch, monkeypatch):
    tmp_path = scratch
    image = tmp_path / "place.png"
    image.write_bytes(b"location")
    sha = sha256_file(image)
    receipt = tmp_path / "place.json"
    receipt.write_text(json.dumps({"schema": "jjv/library-image-receipt/v1", "route": "codex-exec", "prompt_id": "PLACE_1", "output": {"sha256": sha}}))
    approval = tmp_path / "approval.json"
    approval.write_text("{}")
    ctx = SimpleNamespace(machine=None)
    seen = []
    def lookup(path, pid, digest):
        seen.append((path, pid, digest))
        return "approved", str(approval)
    ref = location_refs(ctx, [{"path": str(image), "sha256": sha, "receipt": str(receipt)}], "S1", approval_lookup=lookup)[0]
    assert seen == [(receipt, "PLACE_1", sha)]
    assert (ref["prompt_id"], ref["approval_record"], ref["approval"]) == ("PLACE_1", str(approval), "approved")
    monkeypatch.setattr(pack_refs, "_library_out", lambda *args: tmp_path)
    monkeypatch.setattr(pack_refs.image_library, "current_approval", lambda out, pid: {"schema": pack_refs.image_library.APPROVAL_SCHEMA, "status": "accepted_library_image", "candidate_sha256": sha, "path": str(approval)})
    pack_refs._require_ref_approval(ctx, {"shot": "S1"}, ref)
    with pytest.raises(Refused, match="prompt_id does not match"):
        pack_refs._require_ref_approval(ctx, {"shot": "S1"}, {**ref, "prompt_id": "OTHER"})
    monkeypatch.setattr(pack_refs.image_library, "current_approval", lambda out, pid: {"schema": pack_refs.image_library.APPROVAL_SCHEMA, "status": "accepted_library_image", "candidate_sha256": "a" * 64, "path": str(approval)})
    with pytest.raises(Refused, match=pack_refs.APPROVAL_SHA_MISMATCH):
        pack_refs._require_ref_approval(ctx, {"shot": "S1"}, ref)

def test_unverified_sha_and_manual_approval_do_not_bypass_h3(scratch):
    tmp_path = scratch
    image = tmp_path / "place.png"
    image.write_bytes(b"location")
    ctx = SimpleNamespace(machine=None)
    sha = sha256_file(image)
    ref = location_refs(ctx, [{"path": str(image), "sha256": sha, "user_approved": {"by": "Kim"}}], "S1")[0]
    assert ref["prompt_id"] is None
    with pytest.raises(Refused, match=pack_refs.NOT_APPROVED):
        pack_refs._require_ref_approval(ctx, {"shot": "S1"}, ref)
    with pytest.raises(Refused, match="SHA_MISMATCH"):
        location_refs(ctx, [{"path": str(image), "sha256": "a" * 64, "user_approved": {"by": "Kim"}}], "S1")
