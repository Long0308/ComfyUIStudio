"""ComfyUI connection settings, built from machine config (never from module constants).

Tests build this directly with temp paths and a fake server URL; nothing here has a default
path, so an unconfigured caller cannot reach the real lock or the real ComfyUI folders.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path


EXECUTOR_LOCK_NAME = "EXECUTOR-RUN-LOCK.json"


@dataclass(frozen=True)
class ComfySettings:
    base_url: str
    lock_path: Path
    input_dir: Path
    output_dir: Path
    container: str
    lock_timeout_seconds: float = 30.0
    poll_seconds: float = 2.0
    http_timeout_seconds: float = 30.0
    history_timeout_seconds: float = 3600.0
    min_history_timeout_seconds: float = 900.0
    # crash recovery (machine.resilience; see SKILL.md "Crash recovery and lost prompts")
    max_lost_retries: int = 1
    stall_factor: float = 3.0
    lost_recheck_seconds: float = 5.0
    expected_chunk_seconds: float | None = None  # None: use the plan's per-chunk estimate

    @property
    def executor_lock_path(self) -> Path:
        """Machine-level executor lock: ``EXECUTOR-RUN-LOCK.json`` in the folder of ``lock_path`` (the
        machine's gpu_lock_path), so it is shared by every plan that uses this machine config."""
        return self.lock_path.parent / EXECUTOR_LOCK_NAME

    def with_overrides(self, **values: object) -> "ComfySettings":
        return replace(self, **{k: v for k, v in values.items() if v is not None})


def settings_from_machine(machine: dict) -> ComfySettings:
    """Settings from a validated ``machine`` block (schema ``jjv/machine/v1``)."""
    comfy = machine["comfy"]
    root = Path(comfy["root"])
    resilience = machine.get("resilience") or {}
    return ComfySettings(
        base_url=comfy["url"].rstrip("/"),
        lock_path=Path(machine["gpu_lock_path"]),
        input_dir=root / "input",
        output_dir=Path(comfy.get("output_dir") or root / "output"),
        container=comfy["container"],
        **{key: resilience[key] for key in ("max_lost_retries", "stall_factor", "lost_recheck_seconds",
                                            "expected_chunk_seconds") if key in resilience},
    )
