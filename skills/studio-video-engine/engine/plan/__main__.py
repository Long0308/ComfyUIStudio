"""``python engine/plan/__main__.py explain --old DIR --new DIR`` (works under ``python -I``: the skill root is added here)."""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from engine.plan.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
