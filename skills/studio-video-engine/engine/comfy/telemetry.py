"""Optional resource sampler (docker stats / nvidia-smi) through an injected runner.

Never required: nothing in the engine needs telemetry to be correct, and every probe failure
is swallowed into a ``None`` sample.  Tests inject a fake runner; no real command is run there.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..core.io import sha256_file, write_json_atomic

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
_UNITS = {"b": 0, "kb": 1, "kib": 1, "mb": 2, "mib": 2, "gb": 3, "gib": 3, "tb": 4, "tib": 4}
_PAIR = re.compile(r"([0-9.]+)\s*([KMGT]?i?B)\s*/\s*([0-9.]+)\s*([KMGT]?i?B)", re.I)


def default_runner(command: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)


def _bytes(amount: str, unit: str) -> int:
    return int(float(amount) * 1024 ** _UNITS[unit.lower()])


class TelemetrySampler:
    """Context manager: samples every ``interval_seconds`` into ``samples_path`` (atomic)."""

    def __init__(self, *, container: str, samples_path: Path, runner: Runner = default_runner,
                 interval_seconds: float = 2.0) -> None:
        self.container, self.samples_path = container, Path(samples_path)
        self.runner, self.interval_seconds = runner, interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = time.monotonic()

    def _container_memory(self) -> tuple[int | None, int | None]:
        try:
            match = _PAIR.search(self.runner(["docker", "stats", "--no-stream", self.container]).stdout or "")
            return (_bytes(match[1], match[2]), _bytes(match[3], match[4])) if match else (None, None)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            return None, None

    def _gpu_memory(self) -> int | None:
        try:
            out = self.runner(["nvidia-smi", "--query-gpu=memory.used",
                               "--format=csv,noheader,nounits"]).stdout or ""
            return int(out.strip().splitlines()[0].strip())
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    def _sample(self) -> None:
        used, limit = self._container_memory()
        self.samples.append({"elapsed_s": round(time.monotonic() - self._started, 3), "at": time.time(),
                             "container_memory_used_bytes": used, "container_memory_limit_bytes": limit,
                             "gpu_memory_used_mib": self._gpu_memory()})
        try:
            write_json_atomic(self.samples_path, self.samples, mode="ascii")
        except OSError:
            pass  # telemetry must never break a run

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval_seconds)

    def __enter__(self) -> "TelemetrySampler":
        self._sample()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.interval_seconds * 2))
        self._sample()
        return False

    def summary(self) -> dict[str, Any]:
        def peak(key: str) -> int | None:
            values = [s[key] for s in self.samples if isinstance(s.get(key), int)]
            return max(values) if values else None
        return {"samples_path": str(self.samples_path),
                "samples_sha256": sha256_file(self.samples_path) if self.samples_path.is_file() else None,
                "sample_count": len(self.samples),
                "container_memory_peak_bytes": peak("container_memory_used_bytes"),
                "container_memory_limit_bytes": peak("container_memory_limit_bytes"),
                "gpu_memory_peak_mib": peak("gpu_memory_used_mib")}
