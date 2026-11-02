"""Install tested candidates using flushed sibling temporary files and os.replace."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
NAMES = ("codex_queue", "codex", "local", "prompt_route")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def install():
    log = (BASE / "green-ready.txt").read_text("utf-8")
    if "85 passed" not in log or "EXIT_CODE 0" not in log:
        raise RuntimeError("required candidate tests have not passed")
    prepared = []
    for name in NAMES:
        target = ROOT / "engine/images" / (name + ".py")
        original = (BASE / "original" / (name + ".py")).read_bytes()
        if target.read_bytes() != original:
            raise RuntimeError(f"concurrent edit detected: {target}")
        data = (BASE / "candidate" / (name + ".py")).read_bytes()
        compile(data, str(target), "exec")
        prepared.append((target, original, data))
    result = []
    for target, original, data in prepared:
        if target.read_bytes() != original:
            raise RuntimeError(f"concurrent edit detected before replace: {target}")
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".IMGRT-FIX-", suffix=".tmp", dir=target.parent)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        assert target.read_bytes() == data
        result.append({"file": str(target.relative_to(ROOT)), "before_sha256": sha(original),
                       "after_sha256": sha(data), "method": "fsync temporary + os.replace"})
    receipt = {"test_log": "green-ready.txt", "test_log_sha256": sha((BASE / "green-ready.txt").read_bytes()),
               "files": result, "running_processes_restarted": False}
    (BASE / "install-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    install()
