"""Tests for comfy_guarded_submit.py against a fake local HTTP server.

No real ComfyUI is contacted; the fake server records every request so tests can
prove which methods were used and in which order files were written.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import comfy_guarded_submit as cgs

GRAPH = {
    "1": {"class_type": "LocalNode", "inputs": {"x": 1}},
    "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}},
}
OBJECT_INFO = {
    "LocalNode": {"python_module": "nodes", "category": "test"},
    "SaveVideo": {"python_module": "comfy_extras.nodes_video", "category": "image/video"},
    "CloudThing": {"python_module": "comfy_api_nodes.nodes_x", "category": "api node/x"},
    "ClaudeNode": {"python_module": "comfy_api_nodes.nodes_anthropic",
                   "category": "api node/text/Anthropic"},
}


class FakeComfy:
    def __init__(self) -> None:
        self.queue: dict[str, list] = {"queue_running": [], "queue_pending": []}
        self.history: dict[str, Any] = {}
        self.requests: list[tuple[str, str]] = []
        self.posts: list[dict] = []
        self.on_post: Any = None  # callable invoked before answering POST
        self.post_status = 200
        self.prompt_id = "pid-0001"
        self.leave_queue_after_polls = 0
        self.object_info_delay = 0.0
        self.queue_status = 200  # set to 500 to make GET /queue fail
        self.history_fail_count = 0  # first N GET /history/<id> answer 500
        self.queue_mode = "normal"  # "incomplete" -> truncated body (IncompleteRead)
        self.history_mode = "normal"
        self.post_mode = "normal"  # "drop" closes the socket without answering
        self._queue_polls = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _send(self, code: int, body: object) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _send_incomplete(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "500")
                self.end_headers()
                self.wfile.write(b'{"queue_run')
                self.wfile.flush()
                self.close_connection = True

            def do_GET(self) -> None:  # noqa: N802
                fake.requests.append(("GET", self.path))
                if self.path == "/queue" and fake.queue_mode == "incomplete":
                    self._send_incomplete()
                    return
                if self.path.startswith("/history/") and fake.history_mode == "incomplete":
                    self._send_incomplete()
                    return
                if self.path == "/queue":
                    if fake.queue_status != 200:
                        self._send(fake.queue_status, {"error": "down"})
                        return
                    fake._queue_polls += 1
                    if fake.leave_queue_after_polls and \
                            fake._queue_polls > fake.leave_queue_after_polls:
                        fake.queue = {"queue_running": [], "queue_pending": []}
                    self._send(200, fake.queue)
                elif self.path.startswith("/object_info/"):
                    time.sleep(fake.object_info_delay)
                    name = self.path.rsplit("/", 1)[1]
                    self._send(200, {name: OBJECT_INFO[name]} if name in OBJECT_INFO else {})
                elif self.path.startswith("/history/"):
                    if fake.history_fail_count > 0:
                        fake.history_fail_count -= 1
                        self._send(500, {"error": "flaky"})
                        return
                    pid = self.path.rsplit("/", 1)[1]
                    self._send(200, {pid: fake.history[pid]} if pid in fake.history else {})
                elif self.path == "/history":
                    self._send(200, fake.history)
                elif self.path == "/system_stats":
                    self._send(200, {"devices": [{"name": "gpu", "vram_free": 8 << 30,
                                                  "vram_total": 16 << 30}]})
                else:
                    self._send(404, {})

            def do_POST(self) -> None:  # noqa: N802
                fake.requests.append(("POST", self.path))
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                fake.posts.append(payload)
                if fake.on_post:
                    fake.on_post()
                if fake.post_mode == "drop":
                    self.close_connection = True
                    self.connection.close()
                    return
                if fake.post_status != 200:
                    self._send(fake.post_status, {"error": "bad prompt"})
                    return
                fake.queue["queue_running"] = [
                    [1, fake.prompt_id, payload["prompt"],
                     {"client_id": payload["client_id"]}, ["2"]]
                ]
                self._send(200, {"prompt_id": fake.prompt_id, "number": 1, "node_errors": {}})

        return Handler


@pytest.fixture()
def fake() -> Any:
    server = FakeComfy()
    server.thread.start()
    yield server
    server.server.shutdown()
    server.server.server_close()


def write_graph(tmp_path: Path, graph: dict = GRAPH) -> tuple[Path, str]:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def run(fake: FakeComfy, tmp_path: Path, *argv: str) -> int:
    return cgs.main([
        "--base-url", fake.url, "--lock-path", str(tmp_path / "submit.lock"),
        "--output-dir", str(tmp_path / "out"), "--lock-timeout", "0.2",
        "--poll", "0.01", *argv,
    ])


def submit_args(tmp_path: Path, graph: Path, *extra: str) -> list[str]:
    return ["submit", "--graph", str(graph), "--receipt-dir", str(tmp_path / "rc"),
            "--hold-timeout", "2", *extra]


def posts(fake: FakeComfy) -> list[tuple[str, str]]:
    return [r for r in fake.requests if r[0] == "POST"]


def test_sha_mismatch_refuses(fake: FakeComfy, tmp_path: Path, capsys: Any) -> None:
    graph, _ = write_graph(tmp_path)
    code = run(fake, tmp_path, *submit_args(tmp_path, graph, "--expect-sha", "0" * 64))
    assert code == cgs.EXIT_REFUSED
    assert "sha256 mismatch" in capsys.readouterr().err
    assert posts(fake) == []
    assert not (tmp_path / "rc" / "dispatch-intent.json").exists()


@pytest.mark.parametrize("cls", ["CloudThing", "ClaudeNode"])
def test_partner_node_refuses_unless_partner_ok(
    fake: FakeComfy, tmp_path: Path, capsys: Any, cls: str
) -> None:
    graph, _ = write_graph(tmp_path, {**GRAPH, "3": {"class_type": cls, "inputs": {}}})
    code = run(fake, tmp_path, *submit_args(tmp_path, graph))
    assert code == cgs.EXIT_REFUSED
    assert "partner" in capsys.readouterr().err
    assert posts(fake) == []
    assert not (tmp_path / "submit.lock").exists()


def test_partner_ok_allows(fake: FakeComfy, tmp_path: Path) -> None:
    graph, _ = write_graph(tmp_path, {**GRAPH, "3": {"class_type": "CloudThing", "inputs": {}}})
    fake.leave_queue_after_polls = 1
    assert run(fake, tmp_path, *submit_args(tmp_path, graph, "--partner-ok")) == cgs.EXIT_OK
    assert len(posts(fake)) == 1


def test_unknown_node_class_refuses(fake: FakeComfy, tmp_path: Path) -> None:
    graph, _ = write_graph(tmp_path, {"1": {"class_type": "Nope", "inputs": {}}})
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == cgs.EXIT_REFUSED
    assert posts(fake) == []


def test_busy_queue_refuses(fake: FakeComfy, tmp_path: Path, capsys: Any) -> None:
    fake.queue["queue_pending"] = [[1, "other", {}, {}, []]]
    graph, _ = write_graph(tmp_path)
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == cgs.EXIT_REFUSED
    assert "queue is busy" in capsys.readouterr().err
    assert posts(fake) == []
    assert not (tmp_path / "rc" / "dispatch-intent.json").exists()
    assert not (tmp_path / "submit.lock").exists(), "lock must be released on refusal"


def test_held_lock_refuses_and_is_preserved(
    fake: FakeComfy, tmp_path: Path, capsys: Any
) -> None:
    lock = tmp_path / "submit.lock"
    lock.write_text("pid=1 acquired_unix=0 token=abc\n")
    graph, _ = write_graph(tmp_path)
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == cgs.EXIT_REFUSED
    assert "lock is held" in capsys.readouterr().err
    assert lock.read_text() == "pid=1 acquired_unix=0 token=abc\n"
    assert posts(fake) == []
    assert not (tmp_path / "rc" / "dispatch-intent.json").exists()


def test_intent_written_before_post_and_receipts(fake: FakeComfy, tmp_path: Path) -> None:
    graph, sha = write_graph(tmp_path)
    seen: dict[str, Any] = {}

    def at_post() -> None:
        intent = tmp_path / "rc" / "dispatch-intent.json"
        seen["intent_exists"] = intent.exists()
        seen["lock_exists"] = (tmp_path / "submit.lock").exists()
        seen["intent"] = json.loads(intent.read_text()) if intent.exists() else None
        seen["submitted_exists"] = (tmp_path / "rc" / "submitted.json").exists()

    fake.on_post = at_post
    fake.leave_queue_after_polls = 1
    assert run(fake, tmp_path, *submit_args(tmp_path, graph, "--expect-sha", sha)) == 0
    assert seen["intent_exists"] and seen["lock_exists"] and not seen["submitted_exists"]
    assert seen["intent"]["graph_sha256"] == sha
    assert seen["intent"]["client_id"] == fake.posts[0]["client_id"]
    submitted = json.loads((tmp_path / "rc" / "submitted.json").read_text())
    assert submitted["prompt_id"] == "pid-0001"
    assert not (tmp_path / "submit.lock").exists(), "lock released after prompt left queue"


def test_second_submit_into_same_receipt_dir_refuses(fake: FakeComfy, tmp_path: Path) -> None:
    graph, _ = write_graph(tmp_path)
    fake.leave_queue_after_polls = 1
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == 0
    fake.queue = {"queue_running": [], "queue_pending": []}
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == cgs.EXIT_REFUSED
    assert len(posts(fake)) == 1


def test_comfy_rejection_releases_lock_and_records(fake: FakeComfy, tmp_path: Path) -> None:
    fake.post_status = 400
    graph, _ = write_graph(tmp_path)
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == cgs.EXIT_REFUSED
    assert (tmp_path / "rc" / "submit-rejected.json").exists()
    assert not (tmp_path / "rc" / "submitted.json").exists()
    assert not (tmp_path / "submit.lock").exists()


def test_wait_writes_job_json_with_output_hash(fake: FakeComfy, tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "submitted.json").write_text(json.dumps({"prompt_id": "pid-9", "client_id": "c"}))
    out = tmp_path / "out" / "sub"
    out.mkdir(parents=True)
    (out / "clip.mp4").write_bytes(b"video-bytes")
    fake.history["pid-9"] = {
        "status": {"status_str": "success", "completed": True},
        "outputs": {"2": {"images": [{"filename": "clip.mp4", "subfolder": "sub",
                                       "type": "output"}], "animated": [True]}},
    }
    assert run(fake, tmp_path, "wait", "--receipt-dir", str(rc), "--timeout", "2") == 0
    job = json.loads((rc / "job.json").read_text())
    assert job["status"] == "COMPLETED"
    (entry,) = job["outputs"]
    assert entry["node_id"] == "2" and entry["filename"] == "clip.mp4"
    assert entry["sha256"] == hashlib.sha256(b"video-bytes").hexdigest()
    assert posts(fake) == []


def test_wait_timeout_never_resubmits(fake: FakeComfy, tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "submitted.json").write_text(json.dumps({"prompt_id": "pid-x"}))
    code = run(fake, tmp_path, "wait", "--receipt-dir", str(rc), "--timeout", "0.1")
    assert code == cgs.EXIT_TIMEOUT
    assert json.loads((rc / "job.json").read_text())["status"] == "WAIT_TIMEOUT"
    assert posts(fake) == []


def test_reconcile_never_posts_and_finds_client_id(fake: FakeComfy, tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "guarded-abc"}))
    fake.history["pid-7"] = {"prompt": [3, "pid-7", {}, {"client_id": "guarded-abc"}, []],
                             "status": {"status_str": "success"}, "outputs": {}}
    assert run(fake, tmp_path, "reconcile", "--receipt-dir", str(rc)) == 0
    report = json.loads((rc / "reconcile-report.json").read_text())
    assert report["prompt_id"] == "pid-7" and report["location"] == "history"
    assert json.loads((rc / "reconciled.json").read_text())["prompt_id"] == "pid-7"
    assert posts(fake) == []


def test_reconcile_not_found_never_posts(fake: FakeComfy, tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "guarded-none"}))
    assert run(fake, tmp_path, "reconcile", "--receipt-dir", str(rc)) == 0
    assert json.loads((rc / "reconcile-report.json").read_text())["location"] == "not_found"
    assert not (rc / "reconciled.json").exists()
    assert posts(fake) == []


def test_check_reports_ready_and_busy(
    fake: FakeComfy, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(cgs, "run_docker_ps",
                        lambda: "Comfyui-Studio|running|Up 2 hours (healthy)\n")
    assert run(fake, tmp_path, "check") == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    fake.queue["queue_running"] = [[1, "p", {}, {}, []]]
    assert run(fake, tmp_path, "check") == cgs.EXIT_REFUSED
    monkeypatch.setattr(cgs, "run_docker_ps", lambda: "Comfyui-Studio|exited|Exited (1)\n")
    assert run(fake, tmp_path, "check") == cgs.EXIT_REFUSED
    assert posts(fake) == []


def test_default_lock_path_matches_executor() -> None:
    skill_root = Path(__file__).resolve().parents[4]  # ...\03 Voice
    executor = (skill_root / "production-local" / "JennieJoyKids-Story"
                / "04-milk-and-mom" / "tools" / "upscale_seedvr2_chunked.py")
    source = executor.read_text(encoding="utf-8")
    line = next(x for x in source.splitlines() if '"dispatch_lock":' in x)
    assert 'episode_resolved / "technical" / ".comfyui-image-submit.lock"' in line
    # EPISODE_ROOT = SCRIPT_PATH.parents[1] -> the episode folder holding tools/
    assert "EPISODE_ROOT = SCRIPT_PATH.parents[1]" in source
    expected = (executor.parents[1].resolve() / "technical"
                / ".comfyui-image-submit.lock")
    assert cgs.DEFAULT_LOCK_PATH.resolve() == expected


# ---------------------------------------------------------------- critic H4
def test_two_threads_same_receipt_dir_exactly_one_post(
    fake: FakeComfy, tmp_path: Path
) -> None:
    graph, _ = write_graph(tmp_path)
    fake.object_info_delay = 0.3  # both threads sit in the partner check together
    fake.leave_queue_after_polls = 1
    codes: list[int] = []

    def worker() -> None:
        codes.append(cgs.main([
            "--base-url", fake.url, "--lock-path", str(tmp_path / "submit.lock"),
            "--output-dir", str(tmp_path / "out"), "--lock-timeout", "20",
            "--poll", "0.01", *submit_args(tmp_path, graph)]))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(codes) == [cgs.EXIT_OK, cgs.EXIT_REFUSED]
    assert len(posts(fake)) == 1
    intent = json.loads((tmp_path / "rc" / "dispatch-intent.json").read_text())
    assert intent["client_id"] == fake.posts[0]["client_id"], "intent must not be overwritten"


def test_intent_created_exclusively_inside_lock(
    fake: FakeComfy, tmp_path: Path, monkeypatch: Any
) -> None:
    """A file planted after the pre-check (by a racing process) is never overwritten."""
    graph, _ = write_graph(tmp_path)
    rc = tmp_path / "rc"
    real_idle = cgs.require_idle_queue

    def plant_then_check(settings: Any) -> None:  # runs inside the lock
        rc.mkdir(exist_ok=True)
        (rc / "dispatch-intent.json").write_text('{"client_id": "other"}')
        real_idle(settings)

    monkeypatch.setattr(cgs, "require_idle_queue", plant_then_check)
    code = run(fake, tmp_path, *submit_args(tmp_path, graph))
    assert code == cgs.EXIT_REFUSED
    assert posts(fake) == []
    assert json.loads((rc / "dispatch-intent.json").read_text())["client_id"] == "other"
    assert not (tmp_path / "submit.lock").exists()


def test_post_success_then_hold_monitor_error_is_not_pre_post_error(
    fake: FakeComfy, tmp_path: Path, capsys: Any
) -> None:
    graph, _ = write_graph(tmp_path)

    def break_queue() -> None:
        fake.queue_status = 500

    fake.on_post = break_queue
    code = run(fake, tmp_path, *submit_args(tmp_path, graph))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == cgs.EXIT_OK
    assert out["prompt_id"] == "pid-0001"
    assert out["hold_monitor_error"]
    assert (tmp_path / "rc" / "submitted.json").exists()
    assert not (tmp_path / "submit.lock").exists()


@pytest.mark.parametrize("extra", [[], ["--partner-ok"]])
def test_claudenode_hard_refusal_ignores_partner_ok(
    fake: FakeComfy, tmp_path: Path, capsys: Any, extra: list[str]
) -> None:
    graph, _ = write_graph(tmp_path, {**GRAPH, "3": {"class_type": "ClaudeNode", "inputs": {}}})
    code = run(fake, tmp_path, *submit_args(tmp_path, graph, *extra))
    assert code == cgs.EXIT_REFUSED
    assert "never allowed" in capsys.readouterr().err
    assert posts(fake) == []
    assert not (tmp_path / "rc" / "dispatch-intent.json").exists()


def test_token_mismatch_on_release_preserves_lock_and_logs(
    fake: FakeComfy, tmp_path: Path, capsys: Any
) -> None:
    graph, _ = write_graph(tmp_path)
    lock = tmp_path / "submit.lock"
    fake.leave_queue_after_polls = 1

    def replace_lock() -> None:
        with lock.open("r+b") as stream:  # rewrite through the same path
            stream.write(b"pid=9 acquired_unix=0 token=ffff\n")

    fake.on_post = replace_lock
    run(fake, tmp_path, *submit_args(tmp_path, graph))
    assert lock.exists(), "a lock we do not own must be preserved"
    assert "lock" in capsys.readouterr().err.lower()


def test_hold_timeout_flag_in_stdout(fake: FakeComfy, tmp_path: Path, capsys: Any) -> None:
    graph, _ = write_graph(tmp_path)
    args = ["submit", "--graph", str(graph), "--receipt-dir", str(tmp_path / "rc"),
            "--hold-timeout", "0.1"]
    assert run(fake, tmp_path, *args) == cgs.EXIT_OK  # prompt never leaves the queue
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["hold_timeout"] is True
    assert not (tmp_path / "submit.lock").exists()


def test_post_exception_writes_submit_unknown(fake: FakeComfy, tmp_path: Path) -> None:
    fake.post_mode = "drop"
    graph, _ = write_graph(tmp_path)
    assert run(fake, tmp_path, *submit_args(tmp_path, graph)) == cgs.EXIT_ERROR
    unknown = json.loads((tmp_path / "rc" / "submit-unknown.json").read_text())
    assert unknown["status"] == "DISPATCH_STATUS_UNKNOWN"
    assert (tmp_path / "rc" / "dispatch-intent.json").exists()
    assert not (tmp_path / "rc" / "submitted.json").exists()
    assert not (tmp_path / "submit.lock").exists()
    assert len(posts(fake)) == 1


def test_wait_failed_status_exits_4(fake: FakeComfy, tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "submitted.json").write_text(json.dumps({"prompt_id": "pid-f"}))
    fake.history["pid-f"] = {"status": {"status_str": "error", "messages": []}, "outputs": {}}
    code = run(fake, tmp_path, "wait", "--receipt-dir", str(rc), "--timeout", "2")
    assert code == cgs.EXIT_FAILED
    assert json.loads((rc / "job.json").read_text())["status"] == "FAILED"


def test_wait_logs_poll_errors_to_stderr_and_job_json(
    fake: FakeComfy, tmp_path: Path, capsys: Any
) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "submitted.json").write_text(json.dumps({"prompt_id": "pid-e"}))
    fake.history["pid-e"] = {"status": {"status_str": "success"}, "outputs": {}}
    fake.history_fail_count = 2
    assert run(fake, tmp_path, "wait", "--receipt-dir", str(rc), "--timeout", "5") == 0
    job = json.loads((rc / "job.json").read_text())
    assert job["poll_errors"]["count"] == 2 and job["poll_errors"]["last"]
    assert "history" in capsys.readouterr().err.lower()


def test_reconcile_while_still_queued(fake: FakeComfy, tmp_path: Path) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "guarded-q"}))
    fake.queue["queue_running"] = [[4, "pid-q", {}, {"client_id": "guarded-q"}, []]]
    assert run(fake, tmp_path, "reconcile", "--receipt-dir", str(rc)) == 0
    report = json.loads((rc / "reconcile-report.json").read_text())
    assert report["location"] == "queue_running" and report["prompt_id"] == "pid-q"
    assert posts(fake) == []


def test_check_reports_lock_file(
    fake: FakeComfy, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(cgs, "run_docker_ps",
                        lambda: "Comfyui-Studio|running|Up 2 hours (healthy)\n")
    assert run(fake, tmp_path, "check") == 0
    assert json.loads(capsys.readouterr().out)["lock"]["exists"] is False
    (tmp_path / "submit.lock").write_text("pid=1 acquired_unix=0 token=abc\n")
    assert run(fake, tmp_path, "check") == cgs.EXIT_REFUSED
    report = json.loads(capsys.readouterr().out)
    assert report["lock"]["exists"] is True
    assert any("lock" in x for x in report["problems"])


# ---------------------------------------------------------------- critic H5
def test_hold_incomplete_read_after_post_is_success_with_monitor_error(
    fake: FakeComfy, tmp_path: Path, capsys: Any
) -> None:
    graph, _ = write_graph(tmp_path)

    def truncate_queue() -> None:
        fake.queue_mode = "incomplete"

    fake.on_post = truncate_queue
    code = run(fake, tmp_path, *submit_args(tmp_path, graph))
    captured = capsys.readouterr()
    assert code == cgs.EXIT_OK, captured.err
    out = json.loads(captured.out.strip().splitlines()[-1])
    assert out["prompt_id"] == "pid-0001"
    assert "IncompleteRead" in out["hold_monitor_error"]
    assert (tmp_path / "rc" / "submitted.json").exists()
    assert not (tmp_path / "submit.lock").exists()


def test_wait_history_incomplete_read_writes_job_json_not_refused(
    fake: FakeComfy, tmp_path: Path
) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "submitted.json").write_text(json.dumps({"prompt_id": "pid-i"}))
    fake.history_mode = "incomplete"
    fake.queue_mode = "incomplete"
    code = run(fake, tmp_path, "wait", "--receipt-dir", str(rc), "--timeout", "0.3")
    assert code == cgs.EXIT_TIMEOUT
    job = json.loads((rc / "job.json").read_text())
    assert job["status"] == "WAIT_TIMEOUT"
    assert job["poll_errors"]["count"] >= 1
    assert "IncompleteRead" in job["poll_errors"]["last"][-1]
    assert "IncompleteRead" in job["queue_error"]
    assert posts(fake) == []


def test_wait_unexpected_error_writes_job_json_and_distinct_exit(
    fake: FakeComfy, tmp_path: Path, monkeypatch: Any
) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "submitted.json").write_text(json.dumps({"prompt_id": "pid-u"}))
    fake.history["pid-u"] = {"status": {"status_str": "success"}, "outputs": {}}

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("hash exploded")

    monkeypatch.setattr(cgs, "collect_outputs", boom)
    code = run(fake, tmp_path, "wait", "--receipt-dir", str(rc), "--timeout", "2")
    assert code == cgs.EXIT_ERROR
    job = json.loads((rc / "job.json").read_text())
    assert job["status"] == "WAIT_ERROR" and "hash exploded" in job["error"]
    assert job["prompt_id"] == "pid-u"


def test_unexpected_exception_never_maps_to_refused(
    fake: FakeComfy, tmp_path: Path, monkeypatch: Any
) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "x"}))

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cgs, "_find_client", boom)
    assert run(fake, tmp_path, "reconcile", "--receipt-dir", str(rc)) == cgs.EXIT_ERROR


def test_lock_write_failure_removes_tokenless_lock(tmp_path: Path, monkeypatch: Any) -> None:
    lock = tmp_path / "submit.lock"

    def failing_write(fd: int, data: bytes) -> int:
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(cgs.os, "write", failing_write)
        with pytest.raises(OSError):
            with cgs.existence_lock(lock, 0.1):
                pytest.fail("body must not run when the lock could not be stamped")
    assert not lock.exists()


@pytest.mark.parametrize("content", ['{"nope": 1}', "[1, 2]", '{"client_id": 5}'])
def test_reconcile_bad_intent_is_clear_error(
    fake: FakeComfy, tmp_path: Path, capsys: Any, content: str
) -> None:
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(content)
    assert run(fake, tmp_path, "reconcile", "--receipt-dir", str(rc)) == cgs.EXIT_ERROR
    err = capsys.readouterr().err
    assert "client_id" in err and "Traceback" not in err
    assert posts(fake) == []
