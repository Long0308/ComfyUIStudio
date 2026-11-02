"""Shared helpers of the voice tests (no tests here): listen approval of every bound take."""

from __future__ import annotations

from pathlib import Path

from engine.voice import approval


def approve_all(out: Path, plan: dict, episode_root: Path, *, by: str = "Test Listener") -> int:
    """Approve every planned job whose take is bound (what a person does after listening); returns the count."""
    done = 0
    for job in plan["jobs"]:
        result = approval.approve(out, job, by=by, note="listened in the test", sha256=None, episode_root=episode_root)
        done += result["status"] == "APPROVED"
    return done
