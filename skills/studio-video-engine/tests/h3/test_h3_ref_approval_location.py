"""CRFIX #02 (critic V3-CR-ENGINE-APPLIED): a ``location`` pack ref passes the SAME sha-bound library approval as face/body.

Before the fix ``pack_refs._require_ref_approval`` refused every role outside face/body (wardrobe aside), so a location with a
valid library approval could never reach H3.  ``prop`` is not a role of anchor_pack, so it stays refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from h3_fixtures import SHOT
from test_h3_inputs_m8b import LIB, approval_path, library_stub  # noqa: F401  (library_stub: fixture)

from engine.core.errors import Refused
from engine.h3 import pack_refs

pytestmark = pytest.mark.usefixtures("library_stub")
SHA = "a" * 64


@pytest.fixture(autouse=True)
def receipt_stub(monkeypatch):
    # This unit suite exercises approval decisions; real receipt/hash binding is
    # exercised by test_location_binding_stage.py using files on disk.
    monkeypatch.setattr(pack_refs.anchor_verify, "_receipt_problem", lambda ref, machine: None)
    monkeypatch.setattr(pack_refs, "read_json", lambda path: {"schema": "jjv/library-image-receipt/v1", "prompt_id": Path(path).stem})

@pytest.fixture()
def ctx(tmp_path):
    from test_h3_inputs_m8b import InputsWorld

    return InputsWorld(tmp_path).ctx()


def location_ref(**over) -> dict:
    """A location ref shaped like a face ref: library prompt_id + receipt + approval record, approval ``approved``."""
    prompt_id = over.pop("prompt_id", LIB + SHA)
    ref = {"role": "location", "name": "office", "sha256": SHA, "prompt_id": prompt_id,
           "receipt": {"path": f"/lib/receipts/{prompt_id}.json"}, "approval_record": approval_path(LIB + SHA), "approval": "approved"}
    return {**ref, **over}


def test_approved_location_ref_passes(ctx) -> None:
    pack_refs._require_ref_approval(ctx, {"shot": SHOT}, location_ref())  # no raise


def test_unapproved_location_ref_is_refused(ctx) -> None:
    with pytest.raises(Refused, match=pack_refs.NOT_APPROVED):
        pack_refs._require_ref_approval(ctx, {"shot": SHOT}, location_ref(prompt_id=None))


def test_location_recorded_as_candidate_is_refused(ctx) -> None:
    with pytest.raises(Refused, match="pack records this ref as 'candidate'"):
        pack_refs._require_ref_approval(ctx, {"shot": SHOT}, location_ref(approval="candidate"))


def test_location_approved_for_another_sha_is_refused(ctx) -> None:
    with pytest.raises(Refused, match=pack_refs.APPROVAL_SHA_MISMATCH):
        pack_refs._require_ref_approval(ctx, {"shot": SHOT}, location_ref(prompt_id=LIB + "b" * 64))


def test_a_user_approved_mark_alone_is_not_a_library_approval(ctx) -> None:
    """anchor_refs.location_refs produces ``user_approved`` marks with no library prompt_id: still refused (not silently passed)."""
    ref = {"role": "location", "name": "office", "sha256": SHA, "source_route": "user-approved", "approval": "approved",
           "user_approved": {"by": "Kim", "note": "ok"}, "receipt": None}
    with pytest.raises(Refused, match=pack_refs.NOT_APPROVED):
        pack_refs._require_ref_approval(ctx, {"shot": SHOT}, ref)


def test_prop_role_is_still_refused(ctx) -> None:
    with pytest.raises(Refused, match=pack_refs.NOT_APPROVED):
        pack_refs._require_ref_approval(ctx, {"shot": SHOT}, location_ref(role="prop"))


def test_library_roles_are_exactly_face_body_location() -> None:
    assert pack_refs.LIBRARY_ROLES == ("face", "body", "location")
