"""Gates Q2-Q5 of ``jjv qa review``: one module per gate, each returns a plain dict with a ``status`` of
``PASS``, ``FAIL`` or ``UNCERTAIN`` (see ``engine/qa/review.py`` for the roll-up and the exit code)."""

PASS, FAIL, UNCERTAIN = "PASS", "FAIL", "UNCERTAIN"


def roll_up(statuses) -> str:
    """FAIL beats UNCERTAIN beats PASS."""
    statuses = list(statuses)
    if FAIL in statuses:
        return FAIL
    return UNCERTAIN if UNCERTAIN in statuses else PASS
