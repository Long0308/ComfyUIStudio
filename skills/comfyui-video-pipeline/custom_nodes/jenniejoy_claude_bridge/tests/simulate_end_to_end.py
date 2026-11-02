#!/usr/bin/env python3
"""Host-side end-to-end simulation of the Claude bridge (no ComfyUI, no Docker).

    python simulate_end_to_end.py

Steps (each is asserted; the script prints one line per step and exits 1 on any failure):
 1. the real MCP server is started over stdio and its first tool call writes the heartbeat;
 2. the node function ``JJClaudeBridge().run`` is called in ``mode=auto`` in a thread: with a
    live heartbeat it takes the chat route and writes ``inbox/<key>.json``;
 3. MCP ``bridge_pending`` sees that request;
 4. MCP ``bridge_answer`` (confirm=ANSWER) writes the outbox;
 5. the node returns the answer;
 6. a second call (mode=cache_only) is a cache hit with byte-identical outputs and the inbox
    is untouched.
Everything lives in a throw-away folder; the live ComfyUI folders are never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _jj_bridge_support import PACK_DIR, PACKAGE_NAME, load_pack  # noqa: E402

MCP_PATH = PACK_DIR.parents[1] / "mcp" / "jenniejoy_comfy_mcp.py"


class McpStdio:
    def __init__(self, env: dict[str, str]) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-I", MCP_PATH.name],
            cwd=MCP_PATH.parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )
        self.next_id = 1

    def call(self, tool: str, arguments: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        assert self.process.stdin is not None and self.process.stdout is not None
        message = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        self.next_id += 1
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        result = json.loads(self.process.stdout.readline())["result"]
        return bool(result["isError"]), json.loads(result["content"][0]["text"])

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)


def run_simulation(log: Any = print) -> dict[str, Any]:
    shared = Path(tempfile.mkdtemp(prefix="jj-bridge-sim-"))
    saved_env = {name: os.environ.get(name) for name in (
        "JJ_BRIDGE_SHARED", "JJ_BRIDGE_BASE_URL", "JJ_BRIDGE_MODEL", "JJ_BRIDGE_TOKEN")}
    os.environ["JJ_BRIDGE_SHARED"] = str(shared)
    for name in ("JJ_BRIDGE_BASE_URL", "JJ_BRIDGE_MODEL", "JJ_BRIDGE_TOKEN"):
        os.environ.pop(name, None)  # no router: proves the chat route did the work
    mcp = McpStdio(dict(os.environ))
    try:
        pack = load_pack()
        core = sys.modules[f"{PACKAGE_NAME}.bridge_core"]
        paths = core.BridgePaths.from_shared(shared)
        node = pack.NODE_CLASS_MAPPINGS["JJClaudeBridge"]()

        failed, idle = mcp.call("bridge_pending", {})
        assert not failed and idle["count"] == 0, idle
        assert core.chat_is_live(paths), "MCP tool call must write a fresh heartbeat"
        log("1 ok  MCP started, heartbeat fresh, nothing pending")

        prompt, system = "Describe the shot in one sentence.", "You are a terse director."
        outcome: dict[str, Any] = {}

        def run_node() -> None:
            try:
                outcome["first"] = node.run(prompt, system, "auto", 60)
            except BaseException as error:  # surfaced in the main thread
                outcome["error"] = error

        thread = threading.Thread(target=run_node)
        thread.start()
        log("2 ok  node.run(mode=auto) started in a thread")

        request_id = None
        for _ in range(200):
            failed, listing = mcp.call("bridge_pending", {})
            assert not failed, listing
            if listing["count"]:
                request_id = listing["pending"][0]["request_id"]
                break
            threading.Event().wait(0.05)
        assert request_id, "node never wrote a request"
        expected_key = core.cache_key(system, prompt, [])
        assert request_id == expected_key
        failed, detail = mcp.call("bridge_pending", {"request_id": request_id})
        assert not failed and detail["request"]["prompt"] == prompt
        assert detail["request"]["system"] == system
        log(f"3 ok  bridge_pending sees request {request_id[:12]}")

        failed, posted = mcp.call("bridge_answer", {
            "request_id": request_id, "answer": "A lone crane lifts steel into the dawn.",
            "confirm": "ANSWER", "model_reported": "claude-code-chat"})
        assert not failed, posted
        log("4 ok  bridge_answer wrote the outbox")

        thread.join(timeout=30)
        assert not thread.is_alive() and "error" not in outcome, outcome
        answer, receipt = outcome["first"]
        assert answer == "A lone crane lifts steel into the dawn."
        parsed = json.loads(receipt)
        assert parsed["route"] == "chat" and parsed["model_reported"] == "claude-code-chat"
        log("5 ok  node returned the chat answer; receipt route=chat")

        inbox_before = (paths.inbox / f"{request_id}.json").read_bytes()
        replay = core.resolve(paths, system=system, prompt=prompt, mode="cache_only", env={})
        again = node.run(prompt, system, "cache_only", 60)
        assert replay.cache_hit is True
        assert again == (answer, receipt), "replay must be byte-identical"
        assert (paths.inbox / f"{request_id}.json").read_bytes() == inbox_before
        failed, after = mcp.call("bridge_pending", {})
        assert not failed and after["count"] == 0
        log("6 ok  second call is a cache hit with identical outputs")
        return {"request_id": request_id, "answer": answer, "receipt": parsed}
    finally:
        mcp.close()
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(shared, ignore_errors=True)


def main() -> int:
    try:
        run_simulation()
    except AssertionError as error:
        print(f"SIMULATION FAILED: {error}")
        return 1
    print("SIMULATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
