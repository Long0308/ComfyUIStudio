"""Engine error taxonomy and the exit-code contract (domain-neutral).

Exit codes: 0 ok, 1 refused (nothing was sent), 2 error/uncertain,
3 wait timeout, 4 execution failed.  Exit code 1 must never be reported once a
POST to ComfyUI may have happened: use :func:`exit_code_for` with ``posted``.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_UNCERTAIN = 2
EXIT_TIMEOUT = 3
EXIT_FAILED = 4


class EngineError(Exception):
    """Base class; subclasses carry the exit code they map to."""

    exit_code: int = EXIT_UNCERTAIN

    def __init__(self, message: str = "", *, evidence: dict | None = None) -> None:
        super().__init__(message)
        self.evidence: dict = dict(evidence or {})


class Refused(EngineError):
    """A guard refused the operation before anything was sent (exit 1)."""

    exit_code = EXIT_REFUSED


class Uncertain(EngineError):
    """State is unknown or ambiguous; stop, never auto-resubmit (exit 2)."""

    exit_code = EXIT_UNCERTAIN


class WaitTimeout(EngineError):
    """A bounded wait elapsed without a verdict (exit 3)."""

    exit_code = EXIT_TIMEOUT


class Failed(EngineError):
    """The remote execution ran and failed (exit 4)."""

    exit_code = EXIT_FAILED


def exit_code_for(error: BaseException, *, posted: bool = False) -> int:
    """Map an exception to an exit code.

    ``posted`` is True once a POST may have been sent.  After that point a
    "refused" outcome is impossible by definition, so it is reported as 2.
    Unknown exception types are exit 2 (error/uncertain), never 1.
    """
    code = error.exit_code if isinstance(error, EngineError) else EXIT_UNCERTAIN
    if posted and code == EXIT_REFUSED:
        return EXIT_UNCERTAIN
    return code
