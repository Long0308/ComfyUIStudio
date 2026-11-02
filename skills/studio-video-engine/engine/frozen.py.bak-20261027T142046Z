"""Read-only verification of the ep04 files a running 4K job re-hashes on resume.

Never writes, moves or locks anything.  Paths in FROZEN-EP04.json are relative
to the repository root (the folder that contains ``.agents``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[2]
MANIFEST_PATH = SKILL_ROOT / "FROZEN-EP04.json"


@dataclass(frozen=True)
class FrozenResult:
    path: str
    expected: str
    actual: str  # a sha256, or "MISSING"
    expected_bytes: int | None = None
    actual_bytes: int | None = None

    @property
    def match(self) -> bool:
        if self.actual != self.expected:
            return False
        return self.expected_bytes is None or self.expected_bytes == self.actual_bytes


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_and_size(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def verify_files(manifest: dict, repo_root: Path = REPO_ROOT) -> list[FrozenResult]:
    results: list[FrozenResult] = []
    for item in manifest["files"]:
        target = repo_root / item["path"]
        try:
            actual, size = _hash_and_size(target)
        except OSError:
            actual, size = "MISSING", None
        results.append(
            FrozenResult(item["path"], item["sha256"], actual, item.get("bytes"), size)
        )
    return results


def pid_alive(pid: int) -> bool:
    """True if a process with this PID exists and has not exited."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(manifest: dict, repo_root: Path = REPO_ROOT) -> int | None:
    pid_file = manifest.get("pid_file")
    if not pid_file:
        return None
    try:
        return int((repo_root / pid_file).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def add_verify_arguments(parser) -> None:
    """``jjv frozen verify`` options (``--tree``, ``--episode``)."""
    parser.add_argument("--tree", action="store_true",
                        help="also print engine_tree_sha256 (engine/** + recipes/** + bin/**)")
    parser.add_argument("--episode", default=None,
                        help="with --tree: compare with the episode's pinned engine_tree_sha256 (if it has one)")


def run_tree(episode: str | None = None, skill_root: Path = SKILL_ROOT) -> int:
    """Print the engine tree sha; 1 only when an episode pins a different tree."""
    from .core.provenance import engine_tree_sha256

    tree = engine_tree_sha256(skill_root)
    print(f"TREE     engine_tree_sha256 {tree['engine_tree_sha256']}  files {tree['file_count']}")
    if not episode:
        return 0
    from .config.loader import find_episode_file
    from .core.io import read_json

    pinned = read_json(find_episode_file(episode)).get("engine_tree_sha256")
    if pinned is None:
        print("TREE     episode pins no engine_tree_sha256 (null)")
        return 0
    same = pinned == tree["engine_tree_sha256"]
    print(f"TREE     episode pin {pinned}  {'MATCH' if same else 'MISMATCH'}")
    return 0 if same else 1


def run_verify(manifest_path: Path = MANIFEST_PATH, repo_root: Path = REPO_ROOT, *,
               tree: bool = False, episode: str | None = None) -> int:
    manifest = load_manifest(manifest_path)
    results = verify_files(manifest, repo_root)
    for item in results:
        tag = "MATCH   " if item.match else "MISMATCH"
        print(f"{tag} {item.path}  {item.actual}")
        if not item.match:
            print(f"         expected {item.expected}  bytes {item.expected_bytes}"
                  f" (found {item.actual_bytes})")
    pid = read_pid(manifest, repo_root)
    if pid is None:
        print("PID      unreadable or not configured")
    else:
        print(f"PID      {pid} {'ALIVE' if pid_alive(pid) else 'NOT RUNNING'}")
    ok = bool(results) and all(item.match for item in results)
    tree_code = run_tree(episode) if tree else 0
    print("RESULT   " + ("ALL MATCH" if ok else "MISMATCH PRESENT"))
    return 0 if ok and tree_code == 0 else 1
