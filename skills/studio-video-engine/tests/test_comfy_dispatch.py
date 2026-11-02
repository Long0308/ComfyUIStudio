"""M4: dispatch / reconcile against a fake ComfyUI.  Ports the guarded-helper tests
(intent before POST, busy queue, held lock, unknown POST outcome, two-thread race, ...)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from engine.comfy import dispatch as dsp
from engine.comfy.client import ComfyClient
from engine.comfy.reconcile import reconcile_intent, record_reconciled, verify_known_prompt
from engine.comfy.settings import ComfySettings
from engine.core.errors import Refused, Uncertain, exit_code_for
from engine.core.io import canonical_sha256
from fake_comfy import FakeComfy

GRAPH = {"1": {"class_type": "LocalNode", "inputs": {"x": 1}},
         "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}}}
GRAPH_SHA = canonical_sha256(GRAPH, mode="ascii")


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def make(fake: FakeComfy, tmp_path: Path, lock_timeout: float = 0.2):
    settings = ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=tmp_path / "in",
                             output_dir=tmp_path / "out", container="c", lock_timeout_seconds=lock_timeout,
                             poll_seconds=0.01)
    return ComfyClient(fake.url, timeout_seconds=5), settings


def go(fake, tmp_path, receipt="rc", graph=GRAPH, **kw):
    client, settings = make(fake, tmp_path, kw.pop("lock_timeout", 0.2))
    return dsp.dispatch(client, settings, graph=graph, receipt_dir=tmp_path / receipt,
                        identity={"kind": "t", "n": 1}, **kw)


def test_intent_exists_before_post_under_the_lock_and_submitted_after(fake, tmp_path) -> None:
    seen: dict = {}

    def at_post(payload, prompt_id):
        intent = tmp_path / "rc" / "dispatch-intent.json"
        seen.update(intent=json.loads(intent.read_text()) if intent.exists() else None,
                    lock=(tmp_path / "gpu.lock").exists(),
                    submitted=(tmp_path / "rc" / "submitted.json").exists())

    fake.on_post = at_post
    result = go(fake, tmp_path)
    assert seen["intent"] and seen["lock"] and not seen["submitted"]
    assert seen["intent"]["client_id"] == fake.posts[0]["client_id"] == result.client_id
    assert seen["intent"]["graph_sha256"] == GRAPH_SHA and seen["intent"]["canonicalization"] == "ascii"
    assert seen["intent"]["queue_before_post"] == {"queue_running": [], "queue_pending": []}
    submitted = json.loads((tmp_path / "rc" / "submitted.json").read_text())
    assert submitted["prompt_id"] == result.prompt_id == "pid-0001"
    assert not (tmp_path / "gpu.lock").exists(), "lock released once the POST was answered"


def test_busy_queue_refuses_before_intent_or_post_and_releases_lock(fake, tmp_path) -> None:
    fake.queue["queue_pending"] = [[1, "other", {}, {}, []]]
    with pytest.raises(Refused, match="busy"):
        go(fake, tmp_path)
    assert fake.posts_made() == []
    assert not (tmp_path / "rc" / "dispatch-intent.json").exists()
    assert not (tmp_path / "gpu.lock").exists()


def test_held_lock_refuses_and_is_preserved(fake, tmp_path) -> None:
    (tmp_path / "gpu.lock").write_text("pid=1 acquired_unix=0 token=abc\n")
    with pytest.raises(Refused, match="lock is held"):
        go(fake, tmp_path)
    assert (tmp_path / "gpu.lock").read_text() == "pid=1 acquired_unix=0 token=abc\n"
    assert fake.requests == [] and not (tmp_path / "rc").exists()


def test_second_dispatch_into_a_used_receipt_dir_refuses(fake, tmp_path) -> None:
    fake.auto_complete = True
    go(fake, tmp_path)
    with pytest.raises(Refused, match="receipt dir was used"):
        go(fake, tmp_path)
    assert len(fake.posts_made()) == 1


@pytest.mark.parametrize("mode", ["drop", "incomplete", "status:400", "status:500", "no_prompt_id"])
def test_any_post_problem_is_uncertain_exit_two_and_keeps_the_intent(fake, tmp_path, mode) -> None:
    fake.post_mode = mode
    with pytest.raises(dsp.PostOutcomeUnknown) as error:
        go(fake, tmp_path)
    assert exit_code_for(error.value, posted=True) == 2 and error.value.exit_code == 2
    assert (tmp_path / "rc" / "dispatch-intent.json").exists()
    unknown = json.loads((tmp_path / "rc" / "submit-unknown.json").read_text())
    assert unknown["status"] == "DISPATCH_STATUS_UNKNOWN" and "reconcile" in unknown["next_action"]
    assert not (tmp_path / "rc" / "submitted.json").exists()
    assert not (tmp_path / "gpu.lock").exists()
    assert len(fake.posts_made()) == 1


def test_http_exception_after_post_is_uncertain_exit_two(fake, tmp_path) -> None:
    fake.post_mode = "incomplete"
    with pytest.raises(dsp.PostOutcomeUnknown) as error:
        go(fake, tmp_path)
    assert "IncompleteRead" in error.value.evidence["error"] and exit_code_for(error.value) == 2


def test_http_status_is_recorded_in_the_evidence(fake, tmp_path) -> None:
    fake.post_mode = "status:400"
    with pytest.raises(dsp.PostOutcomeUnknown) as error:
        go(fake, tmp_path)
    assert error.value.evidence["http_status"] == 400


def test_submitted_receipt_failure_after_post_keeps_the_prompt_and_reports_it(fake, tmp_path, monkeypatch) -> None:
    real = dsp.write_json_once

    def flaky(path, value, mode):
        if path.name == "submitted.json":
            raise OSError("disk full")
        return real(path, value, mode=mode)

    fake.auto_complete = True
    monkeypatch.setattr(dsp, "write_json_once", flaky)
    result = go(fake, tmp_path)  # the prompt IS queued: success, receipt error recorded, never "refused"
    assert result.prompt_id and "disk full" in result.submitted_receipt_error


def test_unexpected_error_after_intent_becomes_uncertain(fake, tmp_path, monkeypatch) -> None:
    def boom(self, path, payload, timeout=None):
        raise TypeError("not serialisable")
    monkeypatch.setattr(ComfyClient, "post", boom)
    with pytest.raises(dsp.PostOutcomeUnknown):
        go(fake, tmp_path)
    assert (tmp_path / "rc" / "dispatch-intent.json").exists()


def test_two_threads_same_receipt_dir_exactly_one_post(fake, tmp_path) -> None:
    fake.auto_complete = True
    fake.get_delay = 0.05
    outcomes: list = []

    def worker() -> None:
        try:
            outcomes.append(go(fake, tmp_path, lock_timeout=20))
        except Refused as error:
            outcomes.append(error)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert sorted(type(o).__name__ for o in outcomes) == ["DispatchResult", "Refused"]
    assert len(fake.posts_made()) == 1
    intent = json.loads((tmp_path / "rc" / "dispatch-intent.json").read_text())
    assert intent["client_id"] == fake.posts[0]["client_id"], "the intent was not overwritten"


def test_intent_planted_by_a_racing_process_is_never_overwritten(fake, tmp_path, monkeypatch) -> None:
    rc = tmp_path / "rc"
    real_get = ComfyClient.get

    def plant_then_get(self, path, **kw):  # runs inside the lock, before our intent
        if path == "/queue":
            rc.mkdir(exist_ok=True)
            (rc / "dispatch-intent.json").write_text('{"client_id": "other"}')
        return real_get(self, path, **kw)

    monkeypatch.setattr(ComfyClient, "get", plant_then_get)
    with pytest.raises(Refused):
        go(fake, tmp_path)
    assert fake.posts_made() == []
    assert json.loads((rc / "dispatch-intent.json").read_text()) == {"client_id": "other"}


def test_reserved_identity_keys_are_rejected(fake, tmp_path) -> None:
    client, settings = make(fake, tmp_path)
    with pytest.raises(ValueError):
        dsp.dispatch(client, settings, graph=GRAPH, receipt_dir=tmp_path / "rc", identity={"client_id": "x"})


# ---- reconcile (I3) ----------------------------------------------------------------------
def test_reconcile_matches_exact_graph_and_client_in_history_and_queue(fake, tmp_path) -> None:
    client, _ = make(fake, tmp_path)
    fake.add_history("p-hist", GRAPH, "jjv-a")
    found = reconcile_intent(client, graph_sha256=GRAPH_SHA, client_id="jjv-a")
    assert (found.status, found.prompt_id, found.location) == ("matched", "p-hist", "history")
    fake.history.clear()
    fake.queue["queue_running"] = [[4, "p-q", GRAPH, {"client_id": "jjv-a"}, []]]
    found = reconcile_intent(client, graph_sha256=GRAPH_SHA, client_id="jjv-a")
    assert (found.prompt_id, found.location) == ("p-q", "queue_running")
    assert fake.posts_made() == []


def test_reconcile_needs_both_graph_and_client(fake, tmp_path) -> None:
    client, _ = make(fake, tmp_path)
    other = {**GRAPH, "3": {"class_type": "X", "inputs": {}}}
    fake.add_history("same-client-other-graph", other, "jjv-a")
    fake.add_history("same-graph-other-client", GRAPH, "jjv-b")
    assert reconcile_intent(client, graph_sha256=GRAPH_SHA, client_id="jjv-a").status == "none"


def test_reconcile_ambiguous_is_uncertain_and_none_is_not_an_error(fake, tmp_path) -> None:
    client, _ = make(fake, tmp_path)
    assert reconcile_intent(client, graph_sha256=GRAPH_SHA, client_id="jjv-a").prompt_id is None
    fake.add_history("p1", GRAPH, "jjv-a")
    fake.add_history("p2", GRAPH, "jjv-a")
    with pytest.raises(Uncertain, match="multiple"):
        reconcile_intent(client, graph_sha256=GRAPH_SHA, client_id="jjv-a")


def test_verify_known_prompt_checks_graph_and_client(fake, tmp_path) -> None:
    client, _ = make(fake, tmp_path)
    with pytest.raises(Uncertain, match="no structured"):
        verify_known_prompt(client, prompt_id="p1", graph_sha256=GRAPH_SHA, client_id="jjv-a")
    fake.add_history("p1", GRAPH, "jjv-a")
    assert verify_known_prompt(client, prompt_id="p1", graph_sha256=GRAPH_SHA, client_id="jjv-a")
    with pytest.raises(Uncertain, match="differs"):
        verify_known_prompt(client, prompt_id="p1", graph_sha256=GRAPH_SHA, client_id="jjv-zzz")


def test_record_reconciled_is_idempotent(fake, tmp_path) -> None:
    client, _ = make(fake, tmp_path)
    fake.add_history("p1", GRAPH, "jjv-a")
    found = reconcile_intent(client, graph_sha256=GRAPH_SHA, client_id="jjv-a")
    first = record_reconciled(tmp_path / "rc", result=found, client_id="jjv-a", graph_sha256=GRAPH_SHA)
    assert record_reconciled(tmp_path / "rc", result=found, client_id="jjv-a", graph_sha256=GRAPH_SHA) == first


def test_a_twin_prompt_in_history_blocks_a_second_post_even_without_receipts(fake, tmp_path) -> None:
    fake.auto_complete = True
    go(fake, tmp_path, receipt="rc1")
    with pytest.raises(Uncertain, match="exact graph") as error:
        go(fake, tmp_path, receipt="rc2")  # receipts of the first POST are "lost": other dir, same graph
    assert error.value.exit_code == 2 and len(fake.posts_made()) == 1
    assert not (tmp_path / "rc2" / "dispatch-intent.json").exists()
