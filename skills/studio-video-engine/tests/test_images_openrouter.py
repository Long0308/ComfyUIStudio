"""``jjv images submit --provider openrouter`` against a FAKE OpenRouter on loopback (no network, no real key)."""

from __future__ import annotations

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from engine.core.errors import Failed, Refused, Uncertain
from engine.images import openrouter
from images_fixtures import LIVE, World, make_png, run_images, run_layout

KEY = "sk-or-FAKE-KEY-0123456789"


def png_b64(size=(1024, 576)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class FakeOpenRouter:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.status = 200
        self.cost: float | None = 0.18
        self.model: str | None = "openai/gpt-5.4-image-2-2026-01"
        self.size = (1024, 576)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                fake.headers.append(dict(self.headers))
                if fake.status != 200:
                    self.send_response(fake.status)
                    self.end_headers()
                    self.wfile.write(b'{"error":"nope"}')
                    return
                reply = {"id": "gen-123", "data": [{"b64_json": png_b64(fake.size)}], "usage": {"cost": fake.cost}}
                if fake.model:
                    reply["model"] = fake.model
                raw = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("x-request-id", "req-abc")
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/api/v1/images"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class Setup:
    def __init__(self, tmp: Path, domain: str = "jenniejoy_cartoon_3d") -> None:
        self.world = World(tmp, domain=domain)
        self.layout, self.out = tmp / "layout", tmp / "images"
        self.world.plan_layout(self.layout)
        self.world.images_plan(self.out, self.layout)
        self.prompt = tmp / "brief.txt"
        self.prompt.write_text("Garden scene, mother seated.", encoding="utf-8")

    def submit(self, url: str, **kw):
        defaults = {"spend_ok": True, "dry_run": False, "endpoint": url, "env": {openrouter.KEY_VAR: KEY}}
        return openrouter.submit(self.world.ctx(), self.out, "S01_A", self.prompt, **{**defaults, **kw})


def test_success_records_cost_models_request_hash_and_never_the_key(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        result = setup.submit(fake.url)
        assert fake.headers[0]["Authorization"] == f"Bearer {KEY}"
    assert result["cost_usd"] == 0.18 and result["resolved_model"] == "openai/gpt-5.4-image-2-2026-01"
    body = fake.requests[0]
    assert body["model"] == "openai/gpt-5.4-image-2" and body["n"] == 1 and body["provider"]["allow_fallbacks"] is False
    assert len(body["input_references"]) == 3                                  # guide + two cast refs, guide first
    receipt = json.loads(Path(result["receipt"]).read_text("utf-8"))
    assert receipt["route"] == "openrouter" and receipt["requested_model"] == "openai/gpt-5.4-image-2"
    assert receipt["usage"]["cost"] == 0.18 and receipt["runtime_id"] == "gen-123"
    assert receipt["request_sha256"] == result["request_sha256"] and len(receipt["request_sha256"]) == 64
    saved = json.loads((setup.out / "S01_A" / "openrouter" / "t001" / "request.json").read_text("utf-8"))
    assert saved["request_sha256"] == receipt["request_sha256"]
    assert all("url" not in ref.get("image_url", {}) and ref["sha256"] for ref in saved["request"]["input_references"])
    graph = json.loads(Path(result["workflow"]["workflow"]).read_text("utf-8"))
    assert {node["type"] for node in graph["nodes"]} == {"LoadImage", "Note"}
    leaked = [p for p in tmp_path.rglob("*") if p.is_file() and KEY.encode() in p.read_bytes()]
    assert not leaked, leaked


def test_resolved_model_is_null_when_the_provider_does_not_say(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        fake.model = None
        result = setup.submit(fake.url)
    assert result["resolved_model"] is None
    assert json.loads(Path(result["receipt"]).read_text("utf-8"))["resolved_model"] is None


@pytest.mark.parametrize("kw, match", [({"spend_ok": False}, "--spend-ok"), ({"env": {}}, "OPENROUTER_API_KEY")])
def test_refuses_without_spend_ok_or_without_the_key_and_sends_nothing(tmp_path, kw, match):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        with pytest.raises(Refused, match=match):
            setup.submit(fake.url, **kw)
        assert fake.requests == []
    assert not (setup.out / "S01_A" / "openrouter").exists()


def test_dry_run_saves_the_request_without_a_key_and_sends_nothing(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        result = setup.submit(fake.url, dry_run=True, spend_ok=False, env={})
        assert fake.requests == []
    assert result["dry_run"] and result["key_present"] is False and result["request_sha256"]
    assert (setup.out / "S01_A" / "openrouter" / "t001" / "request.json").is_file()


def test_a_402_writes_a_stop_sentinel_and_every_later_call_is_refused(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        fake.status = 402
        with pytest.raises(Failed, match="HTTP 402"):
            setup.submit(fake.url)
        assert (setup.out / openrouter.STOP_FILE).is_file() and len(fake.requests) == 1
        fake.status = 200
        with pytest.raises(Refused, match="credit/auth/rate stop"):
            setup.submit(fake.url, take="t900")
        assert len(fake.requests) == 1                                          # not retried, not re-sent
    assert not list((setup.out / "S01_A" / "candidates").glob("*.png")) if (setup.out / "S01_A" / "candidates").exists() else True


def test_an_error_that_is_not_a_stop_status_does_not_write_the_sentinel(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        fake.status = 500
        with pytest.raises(Failed, match="HTTP 500"):
            setup.submit(fake.url)
    assert not (setup.out / openrouter.STOP_FILE).exists()


def test_budget_counts_reported_cost_and_refuses_the_next_call(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        setup.submit(fake.url, budget_usd=0.5)
        assert openrouter.spent_usd(setup.out) == pytest.approx(0.18)
        with pytest.raises(Refused, match="budget"):
            setup.submit(fake.url, budget_usd=0.4, take="t900")                 # 0.18 + 0.24 > 0.4
        assert len(fake.requests) == 1


def test_a_non_openrouter_https_host_or_plain_remote_http_is_refused_so_the_key_cannot_leak(tmp_path):
    setup = Setup(tmp_path)
    for url in ("https://evil.example.com/v1/images", "http://203.0.113.9/v1/images"):
        with pytest.raises(Refused, match="not allowed"):
            setup.submit(url)
    assert not (setup.out / "S01_A" / "openrouter").exists()


def test_a_dropped_connection_after_the_intent_is_uncertain_and_leaves_proof(tmp_path):
    setup = Setup(tmp_path)

    def boom(request, timeout):
        raise ConnectionResetError("reset")

    with pytest.raises(Uncertain, match="outcome unknown"):
        setup.submit("https://openrouter.ai/api/v1/images", opener=boom)
    folder = setup.out / "S01_A" / "openrouter" / "t001"
    assert (folder / "intent.json").is_file() and (folder / "unknown.json").is_file()


def test_an_image_below_the_minimum_side_is_kept_but_not_registered(tmp_path):
    setup = Setup(tmp_path)
    with FakeOpenRouter() as fake:
        fake.size = (200, 100)
        with pytest.raises(Uncertain, match="below the 512 px minimum"):
            setup.submit(fake.url)
    assert (setup.out / "S01_A" / "openrouter" / "t001" / "output.png").is_file()
    assert not (setup.out / "S01_A" / "candidates").exists()


def test_the_live_action_domain_refuses_openrouter_only(tmp_path):  # routes-v002: adopt + exec are allowed now
    setup = Setup(tmp_path, domain=LIVE)
    with FakeOpenRouter() as fake:
        with pytest.raises(Refused, match="not allowed for domain 'newtecons_live_action'"):
            setup.submit(fake.url)
        assert fake.requests == []
    png = make_png(tmp_path / "x.png")
    for argv, who in ((["submit", "--provider", "openrouter", "--spend-ok", "--prompt-file", str(setup.prompt)], "openrouter"),):
        code, out = run_images([argv[0], "--episode", str(setup.world.root), "--out", str(setup.out), "--machine",
                                str(setup.world.machine_path), "--shot", "S01_A", *argv[1:]])
        assert code == 1 and "not allowed for domain" in out["error"] and who in out["error"], (who, out)
    code, out = run_images(["plan", "--episode", str(setup.world.root), "--out", str(tmp_path / "p2"), "--machine",
                            str(setup.world.machine_path), "--shot", "S01_A", "--provider", "openrouter",
                            "--guide", f"S01_A={make_png(tmp_path / 'g.png')}", "--placement", f"S01_A={setup.layout / 'placement' / 'S01_A.txt'}"])
    assert code == 1 and "not allowed" in out["error"]
    _ = run_layout
