"""Host-side tests of client.py (stdlib only; a fake bridge on 127.0.0.1, no ComfyUI, no torch)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("lane_client", Path(__file__).with_name("client.py"))
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def serve(tmp_path, states, secret="s" * 40):
    png = tmp_path / "input" / "codex-lane" / "j1" / "01_x.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"\x89PNG fake")
    image = {"input_relpath": "codex-lane/j1/01_x.png", "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, doc):
            data = json.dumps(doc).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get("Authorization") != "Bearer " + secret:
                return self._send(401, {"ok": False, "error": "missing or wrong bridge secret"})
            state = states.pop(0) if len(states) > 1 else states[0]
            self._send(200, {"ok": True, "job_id": "j1", "state": state, "images": [image] if state == "done" else []})

        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self._send(202, {"ok": True, "job_id": "j1", "state": "queued"})

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, tmp_path / "input", seen


def test_poll_until_done_and_verify_hash(tmp_path, monkeypatch):
    server, input_dir, seen = serve(tmp_path, ["running", "running", "done"])
    monkeypatch.setenv("CODEX_BRIDGE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    started = client.call("POST", "/v1/images/codex", "s" * 40, {"n": 1})
    doc = client.wait_job(started["job_id"], "s" * 40, 10, poll_seconds=0.01)
    assert doc["state"] == "done" and client.landed_paths(doc, input_dir)[0].is_file() and seen == [{"n": 1}]
    (input_dir / "codex-lane/j1/01_x.png").write_bytes(b"changed")
    with pytest.raises(client.BridgeError, match="hashes"):
        client.landed_paths(doc, input_dir)
    server.shutdown()


def test_wrong_secret_and_timeout_are_clear_errors(tmp_path, monkeypatch):
    server, _, _ = serve(tmp_path, ["running"])
    monkeypatch.setenv("CODEX_BRIDGE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    with pytest.raises(client.BridgeError, match="HTTP 401"):
        client.call("GET", "/v1/jobs/j1", "wrong")
    with pytest.raises(client.BridgeError, match="still 'running'"):
        client.wait_job("j1", "s" * 40, 0.05, poll_seconds=0.01)
    server.shutdown()


def test_missing_secret_file_names_where_it_looked(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_BRIDGE_SECRET_FILE", str(tmp_path / "none"))
    monkeypatch.setattr(client, "SECRET_FILES", (str(tmp_path / "also-none"),))
    with pytest.raises(client.BridgeError, match="secret file not found"):
        client.read_secret()


# ---------------------------------------------------------------- prompts input (one per line)
def test_split_prompts_one_per_line_in_order_blank_lines_dropped():
    assert client.split_prompts("a\n\n  b  \r\nc\n") == ["a", "b", "c"]
    assert client.split_prompts("") is None and client.split_prompts(None) is None  # empty => prompt/count mode


def test_split_prompts_refuses_blank_only_and_more_than_ten():
    with pytest.raises(ValueError, match="blank"):
        client.split_prompts(" \n\n \t\n")
    assert len(client.split_prompts("\n".join(f"p{i}" for i in range(10)))) == 10
    with pytest.raises(ValueError, match="at most 10"):
        client.split_prompts("\n".join(f"p{i}" for i in range(11)))


def test_build_body_prompts_override_prompt_and_count():
    body = client.build_body(prompt="ignored", count=7, episode="e", kind="SHOT", client_id="c", prompts_text="x\ny")
    assert body["prompts"] == ["x", "y"] and "prompt_text" not in body and "n" not in body
    body = client.build_body(prompt="solo", count=3, episode="e", kind="SHOT", client_id="c", prompts_text="")
    assert body["prompt_text"] == "solo" and body["n"] == 3 and "prompts" not in body
    with pytest.raises(ValueError, match="prompt is empty"):
        client.build_body(prompt=" ", count=1, episode="e", kind="SHOT", client_id="c", prompts_text="")


# ---------------------------------------------------------------- wardrobe context + ref_set in job_info
def test_build_body_sends_context_only_when_chosen():
    plain = client.build_body("p", 1, "e", "SHOT", "c", "", client.DEFAULT_CONTEXT)
    assert "context" not in plain  # the bridge's domain default (wardrobe preset) applies
    assert client.build_body("p", 1, "e", "SHOT", "c", "", None) == plain
    assert client.build_body("p", 1, "e", "SHOT", "c", "", " van_phong ")["context"] == "van_phong"
    assert client.build_body("p", 1, "e", "SHOT", "c", "a\nb", "cong_truong")["context"] == "cong_truong"


def test_ref_set_summary_shows_which_refs_the_bridge_attached():
    doc = {"ref_set": {"source": "preset", "context": "cong_truong",
                       "refs": [{"name": "UNIFORM_HELMET.png", "role": "helmet", "sha256": "ab" * 32}]}}
    assert client.ref_set_summary(doc)["refs"][0]["name"] == "UNIFORM_HELMET.png"
    assert client.ref_set_summary({})["source"] == "none"  # an older bridge: shown as none, never invented
