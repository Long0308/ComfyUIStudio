"""Cờ tạo tiến trình con: không bật cửa sổ console đen trên Windows (CREATE_NO_WINDOW); nơi khác = 0."""
from __future__ import annotations

import subprocess
import sys


def no_window() -> int:
    """``subprocess.CREATE_NO_WINDOW`` trên win32, 0 ở nền khác (getattr: an toàn khi thiếu hằng)."""
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)) if sys.platform == "win32" else 0
