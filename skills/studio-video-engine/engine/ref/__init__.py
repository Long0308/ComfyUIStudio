"""Local reference-library search and deliberately one-at-a-time image fetch."""

from .fetch import ALLOWED_HOSTS, FetchResult, fetch_one
from .library import SUPPORTED_TYPES, RefEntry, default_library_root, find_entry_by_id, search_entries
from .stage import StagePlan, apply_stage, plan_stage

__all__ = [
    "ALLOWED_HOSTS",
    "FetchResult",
    "RefEntry",
    "StagePlan",
    "SUPPORTED_TYPES",
    "apply_stage",
    "default_library_root",
    "fetch_one",
    "find_entry_by_id",
    "plan_stage",
    "search_entries",
]
