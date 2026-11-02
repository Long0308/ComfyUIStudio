"""Keep the review UI alive and unload models after five idle minutes."""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main():
    child = subprocess.Popen([sys.executable, *sys.argv[1:]])
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    idle_since = time.monotonic()
    delay = int(os.environ.get("COMFY_IDLE_SECONDS", "300"))
    while child.poll() is None:
        if not stopping:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=5) as response:
                    queue = json.load(response)
                if queue["queue_running"] or queue["queue_pending"]:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= delay:
                    request = urllib.request.Request(
                        "http://127.0.0.1:8188/free",
                        data=b'{"unload_models":true,"free_memory":true}',
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        response.read()
                    print("[idle-release] Requested model unload; review UI remains available.", flush=True)
                    idle_since = time.monotonic()
            except Exception as exc:  # never let the PID-1 watcher die: a reset/timeout under heavy model load used to crash it, which stopped the container and lost queued jobs (01/11/2026, RestartCount=4)
                print(f"[idle-release] Waiting for ComfyUI: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(5)
    return child.returncode


if __name__ == "__main__":
    sys.exit(main())
