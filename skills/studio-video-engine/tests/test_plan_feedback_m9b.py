"""M9b-3: engine-side feedback reader/validator (tmp_path only, read-only on inputs).

Same corpus as the Studio writer tests (CORPUS_SHA pinned in both). No uniquely
needed conftest: this file relies on the shared tests/conftest.py only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engine.plan import feedback as fb
from engine.plan.feedback import FeedbackError, read_feedback

ART = "b" * 64
BASE_ID = "3c361f57-8485-4e9a-b58a-9fd25f4f765f"
RECEIPT = "engine/runs/r003/h3/S01_A/adopt.json"
SCRIPT_RECEIPT = "engine/runs/r003/script/note.json"
DOMAIN = "jenniejoy_cartoon_3d"
EPISODE = "05-example"
SHOTS = frozenset({"S01_A", "S02_B"})

CORPUS = [
    ("valid_base", {}, True),
    ("valid_frame_0", {"frame": 0}, True),
    ("valid_frame_last", {"frame": 99}, True),
    ("valid_episode_note", {"shot": None, "stage": "review", "frame": None}, True),
    ("valid_receipt_only", {"stage": "script", "shot": None, "receipt": "$SCRIPT_RECEIPT",
                            "receipt_sha256": "$SCRIPT_SHA", "artifact_sha256": None, "frame": None}, True),
    ("valid_unicode_separators", {"note": "d\u00f2ng\u2028m\u1edbi\u2029x\nxu\u1ed1ng \"d\u00f2ng\" \u65e5\u672c\u8a9e"}, True),
    ("valid_note_2000", {"note": "$X2000"}, True),
    ("valid_author_80", {"author": "$A80"}, True),
    ("valid_supersedes_ref", {"supersedes": "7f0e6c5a-0b1d-4f6e-8a1b-2c3d4e5f6a7b"}, True),
    ("bad_schema", {"schema": "jjv/studio-feedback/v2"}, False),
    ("bad_id_uppercase", {"id": "3C361F57-8485-4E9A-B58A-9FD25F4F765F"}, False),
    ("bad_id_not_uuid", {"id": "note-1"}, False),
    ("bad_domain_unknown", {"domain": "other"}, False),
    ("bad_domain_mismatch", {"domain": "newtecons_live_action"}, False),
    ("bad_episode_mismatch", {"episode": "99-other"}, False),
    ("bad_shot_unknown", {"shot": "S99_Z"}, False),
    ("bad_shot_empty", {"shot": ""}, False),
    ("bad_stage", {"stage": "render"}, False),
    ("bad_verdict", {"verdict": "reject"}, False),
    ("bad_note_empty", {"note": ""}, False),
    ("bad_note_padded", {"note": " x "}, False),
    ("bad_note_2001", {"note": "$X2001"}, False),
    ("bad_note_type", {"note": 5}, False),
    ("bad_author_empty", {"author": ""}, False),
    ("bad_author_81", {"author": "$A81"}, False),
    ("bad_ts_month", {"ts": "2026-13-01T00:00:00.000Z"}, False),
    ("bad_ts_no_millis", {"ts": "2026-10-28T14:00:00Z"}, False),
    ("bad_ts_second_60", {"ts": "2026-10-28T14:00:60.000Z"}, False),
    ("bad_receipt_absolute", {"receipt": "/engine/runs/r003/h3/S01_A/adopt.json"}, False),
    ("bad_receipt_drive", {"receipt": "C:/x/adopt.json"}, False),
    ("bad_receipt_dotdot", {"receipt": "engine/../engine/runs/r003/h3/S01_A/adopt.json"}, False),
    ("bad_receipt_escape", {"receipt": "../outside.json"}, False),
    ("bad_receipt_backslash", {"receipt": "engine" + chr(92) + "adopt.json"}, False),
    ("bad_receipt_missing", {"receipt": "engine/runs/r003/h3/S01_A/none.json"}, False),
    ("bad_receipt_sha_stale", {"receipt_sha256": "0" * 64}, False),
    ("bad_receipt_sha_upper", {"receipt_sha256": "$SHA_UPPER"}, False),
    ("bad_artifact_null_for_h3", {"artifact_sha256": None}, False),
    ("bad_artifact_unbound", {"artifact_sha256": "c" * 64}, False),
    ("bad_frame_negative", {"frame": -1}, False),
    ("bad_frame_bool", {"frame": True}, False),
    ("bad_frame_float", {"frame": 1.5}, False),
    ("bad_frame_out_of_range", {"frame": 100}, False),
    ("bad_extra_key", {"extra": 1}, False),
    ("bad_missing_note", {"note": "$DEL"}, False),
    ("bad_supersedes_self", {"supersedes": "3c361f57-8485-4e9a-b58a-9fd25f4f765f"}, False),
    ("bad_supersedes_format", {"supersedes": "abc"}, False),
]

# Both test files carry the SAME corpus; this pin proves they are identical.
CORPUS_SHA = "4a1d17f44f3be126363b26601f05894d87b6967f1a0db2738f5ae818a05ef539"


def corpus_digest() -> str:
    return hashlib.sha256(json.dumps(CORPUS, sort_keys=True).encode()).hexdigest()


def make_world(root: Path) -> dict:
    for rel, doc in ((RECEIPT, {"frame_count": 100, "media": {"sha256": ART}}),
                     (SCRIPT_RECEIPT, {"stage": "script"})):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(json.dumps(doc, indent=2).encode())
    sha = hashlib.sha256((root / RECEIPT).read_bytes()).hexdigest()
    return {"sha": sha, "script_sha": hashlib.sha256((root / SCRIPT_RECEIPT).read_bytes()).hexdigest()}


def base_record(world: dict, **over) -> dict:
    rec = {"schema": "jjv/studio-feedback/v1", "id": BASE_ID, "domain": DOMAIN,
           "episode": EPISODE, "shot": "S01_A", "stage": "h3", "verdict": "changes",
           "note": "Listener mouth should stay closed.", "author": "Director",
           "ts": "2026-10-28T14:00:00.000Z", "receipt": RECEIPT,
           "receipt_sha256": world["sha"], "artifact_sha256": ART, "frame": 72,
           "supersedes": None}
    rec.update(over)
    return rec


def build(world: dict, patch: dict) -> dict:
    tokens = {"$SCRIPT_RECEIPT": SCRIPT_RECEIPT, "$SCRIPT_SHA": world["script_sha"],
              "$SHA_UPPER": world["sha"].upper(), "$X2000": "x" * 2000, "$X2001": "x" * 2001,
              "$A80": "a" * 80, "$A81": "a" * 81}
    rec = base_record(world)
    for key, value in patch.items():
        if value == "$DEL":
            rec.pop(key)
        else:
            rec[key] = tokens.get(value, value) if isinstance(value, str) else value
    return rec


SECOND_ID = "7f0e6c5a-0b1d-4f6e-8a1b-2c3d4e5f6a7b"
KW = dict(episode=EPISODE, domain=DOMAIN, shots=SHOTS)


def line_of(rec: dict) -> bytes:
    return (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def put(root: Path, *records, raw: bytes | None = None) -> Path:
    target = fb.feedback_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw if raw is not None else b"".join(line_of(r) for r in records))
    return target


def test_corpus_is_pinned():
    assert corpus_digest() == CORPUS_SHA


@pytest.mark.parametrize("name,patch,ok", CORPUS, ids=[c[0] for c in CORPUS])
def test_validate_record_corpus(tmp_path, name, patch, ok):
    world = make_world(tmp_path)
    rec = build(world, patch)
    kw = dict(domain=DOMAIN, episode=EPISODE, shots=SHOTS, root=tmp_path)
    if ok:
        fb.validate_record(rec, **kw)
    else:
        with pytest.raises(FeedbackError):
            fb.validate_record(rec, **kw)


def test_absent_default_is_zero_notes_not_error(tmp_path):
    snap = read_feedback(None, root=tmp_path, **KW)
    assert snap.present is False and snap.notes == () and snap.sha256 is None


def test_explicit_absent_file_is_refused(tmp_path):
    with pytest.raises(FeedbackError) as err:
        read_feedback(tmp_path / "nope.jsonl", root=tmp_path, **KW)
    assert err.value.kind == "missing"
    with pytest.raises(FeedbackError):
        read_feedback(None, root=tmp_path, require=True, **KW)


def test_reads_typed_notes_bound_to_receipt_sha(tmp_path):
    world = make_world(tmp_path)
    path = put(tmp_path, base_record(world), base_record(world, id=SECOND_ID, verdict="comment",
                                                         note="dòng mới", supersedes=BASE_ID))
    snap = read_feedback(None, root=tmp_path, **KW)
    first, second = snap.notes
    assert (first.line, second.line) == (1, 2) and first.receipt_sha256 == world["sha"]
    assert first.superseded is True and second.superseded is False and second.note == "dòng mới"
    assert snap.unresolved_changes == () and snap.line_count == 2
    assert snap.sha256 == hashlib.sha256(path.read_bytes()).hexdigest() and snap.bytes == path.stat().st_size


def test_unresolved_changes_listed(tmp_path):
    world = make_world(tmp_path)
    put(tmp_path, base_record(world))
    assert read_feedback(None, root=tmp_path, **KW).unresolved_changes == (BASE_ID,)


def test_note_with_stale_receipt_is_refused_or_marked(tmp_path):
    world = make_world(tmp_path)
    put(tmp_path, base_record(world))
    (tmp_path / RECEIPT).write_bytes(b'{"frame_count":100,"media":{"sha256":"%s"},"v":2}' % ART.encode())
    with pytest.raises(FeedbackError) as err:
        read_feedback(None, root=tmp_path, **KW)
    assert err.value.kind == "stale" and err.value.line == 1
    snap = read_feedback(None, root=tmp_path, on_stale="mark", **KW)
    assert snap.stale == (BASE_ID,) and snap.notes[0].stale is True


@pytest.mark.parametrize("raw", [
    b'\xef\xbb\xbf{"x":1}\n',
    b"{not json}\n",
    b"\n",
    b'{"a":1,"a":2}\n',
    b'{"schema":NaN}\n',
    b"\xff\xfe\n",
    b"[1]\n",
])
def test_malformed_lines_are_refused_with_line_number(tmp_path, raw):
    make_world(tmp_path)
    put(tmp_path, raw=raw)
    with pytest.raises(FeedbackError) as err:
        read_feedback(None, root=tmp_path, **KW)
    assert err.value.line == 1


def test_torn_tail_is_refused_not_repaired(tmp_path):
    world = make_world(tmp_path)
    torn = line_of(base_record(world)) + b'{"schema":"jjv/stu'
    path = put(tmp_path, raw=torn)
    with pytest.raises(FeedbackError) as err:
        read_feedback(None, root=tmp_path, **KW)
    assert err.value.kind == "corrupt" and err.value.line == 2
    assert path.read_bytes() == torn


def test_duplicate_id_and_bad_supersedes_scope_refused(tmp_path):
    world = make_world(tmp_path)
    put(tmp_path, base_record(world), base_record(world))
    with pytest.raises(FeedbackError) as dup:
        read_feedback(None, root=tmp_path, **KW)
    assert dup.value.line == 2
    put(tmp_path, base_record(world), base_record(world, id=SECOND_ID, shot="S02_B", supersedes=BASE_ID))
    with pytest.raises(FeedbackError) as scope:
        read_feedback(None, root=tmp_path, **KW)
    assert scope.value.kind == "supersedes"
    put(tmp_path, base_record(world, id=SECOND_ID, supersedes=BASE_ID))  # parent not earlier
    with pytest.raises(FeedbackError):
        read_feedback(None, root=tmp_path, **KW)


def test_wrong_domain_or_episode_never_gives_clean_result(tmp_path):
    world = make_world(tmp_path)
    put(tmp_path, base_record(world))
    with pytest.raises(FeedbackError):
        read_feedback(None, root=tmp_path, episode="other", domain=DOMAIN, shots=SHOTS)
    with pytest.raises(FeedbackError):
        read_feedback(None, root=tmp_path, episode=EPISODE, domain="newtecons_live_action", shots=SHOTS)


def test_unicode_separators_are_not_line_breaks(tmp_path):
    world = make_world(tmp_path)
    put(tmp_path, base_record(world, note="a b c\x85d\x0be\x0cf"))
    snap = read_feedback(None, root=tmp_path, **KW)
    assert snap.line_count == 1 and snap.notes[0].note == "a b c\x85d\x0be\x0cf"


def test_receipt_path_escape_via_file_is_refused(tmp_path):
    root = tmp_path / "R"
    root.mkdir()
    world = make_world(tmp_path / "other")
    (tmp_path / "outside.json").write_text("{}")
    put(root, base_record(world, receipt="../outside.json"))
    with pytest.raises(FeedbackError) as err:
        read_feedback(None, root=root, **KW)
    assert err.value.kind == "path"


def test_reader_never_modifies_inputs(tmp_path):
    world = make_world(tmp_path)
    path = put(tmp_path, base_record(world))
    before = (path.read_bytes(), (tmp_path / RECEIPT).read_bytes(), path.stat().st_mtime_ns)
    read_feedback(None, root=tmp_path, **KW)
    assert before == (path.read_bytes(), (tmp_path / RECEIPT).read_bytes(), path.stat().st_mtime_ns)


def test_module_stays_small_and_free_of_process_or_network_imports():
    text = Path(fb.__file__).read_text(encoding="utf-8")
    assert len(text.splitlines()) < 400
    for banned in ("import subprocess", "import socket", "import requests", "urllib"):
        assert banned not in text
