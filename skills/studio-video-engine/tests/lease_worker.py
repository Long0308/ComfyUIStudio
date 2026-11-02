"""Helper process for test_images_n20fix: hold the lease (mode ``race``: take it, record enter/exit; mode ``hold``: take
it, announce, sleep so the parent can kill it hard)."""

import json
import os
import sys
import time

sys.path.insert(0, sys.argv[1])
from engine.images.lease import lease  # noqa: E402

mode, lock, out, start_at, hold = sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]), float(sys.argv[6])
while time.time() < start_at:
    pass
rec = {"pid": os.getpid()}
try:
    with lease(lock, timeout_seconds=30, what="t"):
        rec["enter"] = time.time()
        if mode == "hold":
            with open(out, "a") as f:
                f.write(json.dumps(rec) + "\n")
            time.sleep(600)
        time.sleep(hold)
        rec["exit"] = time.time()
except Exception as error:  # reported through the file
    rec["err"] = repr(error)
if mode == "race":
    with open(out, "a") as f:
        f.write(json.dumps(rec) + "\n")
