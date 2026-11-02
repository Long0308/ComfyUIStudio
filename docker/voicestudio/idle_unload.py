"""PID-1 wrapper for VoiceStudio. The backend already unloads its model after OMNIVOICE_IDLE_TIMEOUT_S
(services/model_manager.py idle_worker). This wrapper adds what the backend cannot do alone: once the
model status is 'idle' (unloaded) and the process RSS is still above IDLE_RESTART_RSS_MB, restart the
uvicorn child (container stays up) so the OS really gets the memory back. Next request cold-starts it.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

PORT = os.environ.get("OMNIVOICE_PORT", "8080")
RSS_LIMIT_KB = int(os.environ.get("IDLE_RESTART_RSS_MB", "1500")) * 1024
POLL = 30


def rss_kb(pid):
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def model_status():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/model/status", timeout=5) as r:
        return json.load(r).get("status")


def main():
    args = [sys.executable, *sys.argv[1:]]
    stopping = False
    child = subprocess.Popen(args)

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    idle_since = None
    while True:
        rc = child.poll()
        if rc is not None:
            if stopping:
                return rc
            if rc == -signal.SIGTERM or rc == 0:  # restart requested by us
                child = subprocess.Popen(args)
                idle_since = None
            else:
                return rc  # crash: let docker restart policy handle it
        elif not stopping:
            try:
                if model_status() == "idle":
                    idle_since = idle_since or time.monotonic()
                    if time.monotonic() - idle_since >= 60 and rss_kb(child.pid) > RSS_LIMIT_KB:
                        print(f"[idle-unload] model idle, RSS {rss_kb(child.pid)//1024} MB > limit; restarting backend", flush=True)
                        child.send_signal(signal.SIGTERM)
                        idle_since = None
                else:
                    idle_since = None
            except Exception as exc:  # never let PID 1 die on a poll failure
                print(f"[idle-unload] waiting: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL if child.poll() is None else 1)


if __name__ == "__main__":
    sys.exit(main())
