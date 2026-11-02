"""A FAKE Codex CLI for the codex-exec tests (never the real one, never a network call).

Behaviour is chosen by marker files in ``$CODEX_HOME`` (so one binary plays several accounts):
  quota.flag   -> exit 1 with a usage-limit message (text inside = the message, default "usage limit ... in 2 hours")
  auth.flag    -> exit 1 "not logged in"
  hang.flag    -> sleep (the engine's timeout kills it)
  two.flag     -> make TWO images
  nothing.flag -> exit 0 without making an image
  FAKE_CODEX_SLEEP=<s> (env) -> work for that long first; start/end go to spans.jsonl (lane-overlap tests)
  otherwise    -> write generated_images/<session>/exec-<uuid>.png (copy of $FAKE_CODEX_PNG), print its path.
Every call appends {argv, stdin} to calls.jsonl in the home. The fake never reads auth.json.
"""

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

home = Path(os.environ["CODEX_HOME"])
stdin = sys.stdin.read()
with (home / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin}) + "\n")


_t0 = time.time()
time.sleep(float(os.environ.get("FAKE_CODEX_SLEEP", "0")))
with (home / "spans.jsonl").open("a", encoding="utf-8") as spans:
    spans.write(json.dumps({"start": _t0, "end": time.time()}) + chr(10))


def flag(name):
    return (home / name).read_text(encoding="utf-8").strip() if (home / name).exists() else None


if (home / "hang.flag").exists():
    time.sleep(60)
if (home / "quota.flag").exists():
    print(flag("quota.flag") or "You've hit your usage limit. Try again in 2 hours 30 minutes.", file=sys.stderr)
    sys.exit(1)
if (home / "auth.flag").exists():
    print("Not logged in. Please log in.", file=sys.stderr)
    sys.exit(1)
session = str(uuid.uuid4())
print(json.dumps({"type": "thread.started", "thread_id": session}))
if (home / "nothing.flag").exists():
    sys.exit(0)
folder = home / "generated_images" / session
folder.mkdir(parents=True)
made = []
for _ in range(2 if (home / "two.flag").exists() else 1):
    target = folder / f"exec-{uuid.uuid4()}.png"
    shutil.copyfile(os.environ["FAKE_CODEX_PNG"], target)
    made.append(target)
    # distinct bytes per image so two images never collide
    target.write_bytes(target.read_bytes() + uuid.uuid4().bytes)
print(made[-1])
sys.exit(0)
