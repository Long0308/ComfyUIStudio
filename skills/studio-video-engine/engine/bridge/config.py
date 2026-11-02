"""Bridge settings: where state lives, which codex account labels may run, how children are started."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..config.loader import DEFAULT_MACHINE_PATH, SKILL_ROOT
from ..core.errors import Refused
from ..core.io import read_json

DEFAULT_PORT = 8797
SECRET_NAME = "secret"
CONFIG_NAME = "config.json"
JJV = SKILL_ROOT / "bin" / "jjv.py"
# user rule 2026-10-30: these codex account labels never run bridge jobs, whatever a flag or config.json says
FORBIDDEN_LABELS = ("acct1", "acct2")


def default_state_dir() -> Path:
    """``<machine.json folder>/bridge`` (secret, config.json, jobs/); never inside the engine tree."""
    return Path(DEFAULT_MACHINE_PATH).parent / "bridge"


def config_accounts(state_dir: Path) -> list[str]:
    """``accounts`` of ``<state>/config.json`` (labels only), or [] when the file is absent."""
    path = Path(state_dir) / CONFIG_NAME
    if not path.is_file():
        return []
    data: Any = read_json(path)
    labels = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise Refused(f"{path}: 'accounts' must be a list of codex account labels")
    return labels


def config_section(state_dir: Path, key: str) -> dict[str, Any]:
    """Object ``key`` of ``<state>/config.json`` (domain id -> block), or {} when absent."""
    path = Path(state_dir) / CONFIG_NAME
    data: Any = read_json(path) if path.is_file() else {}
    block = data.get(key) if isinstance(data, dict) else None
    if block is not None and not isinstance(block, dict):
        raise Refused(f"{path}: {key!r} must be an object keyed by domain id")
    return block or {}


def config_wardrobe(state_dir: Path) -> dict[str, Any]:
    """``wardrobe`` of ``<state>/config.json`` (domain id -> preset block, see ``wardrobe.py``), or {} when absent."""
    return config_section(state_dir, "wardrobe")


def resolve_accounts(state_dir: Path, override: str | None) -> list[str]:
    """Effective allow-list: ``config.json`` when present, optionally NARROWED by ``--accounts`` (intersection only;
    a flag never adds a label the file does not list).  Without a config.json the flag is the list."""
    flag = [a.strip() for a in (override or "").split(",") if a.strip()]
    configured = config_accounts(state_dir)
    if not configured:
        return flag
    if not flag:
        return configured
    narrowed = [a for a in configured if a in flag]
    if not narrowed:
        raise Refused(f"--accounts {flag} shares no label with the config.json allow-list {configured}: "
                      "the flag can only narrow the allow-list, never widen it")
    return narrowed


@dataclass
class BridgeConfig:
    state_dir: Path
    accounts: tuple[str, ...]
    machine_path: Path | None = None
    codex_cmd: list[str] | None = None
    timeout: float | None = None
    base_env: Mapping[str, str] | None = None
    jjv_cmd: list[str] = field(default_factory=lambda: [sys.executable, "-I", str(JJV)])
    wardrobe: dict[str, Any] = field(default_factory=dict)  # domain id -> wardrobe preset block (config.json)
    workspace_root: Path | None = None  # video episode/out must resolve inside it (default: <machine.json folder>/..)

    def __post_init__(self) -> None:
        self.state_dir = Path(self.state_dir)
        labels = tuple(a.strip() for a in self.accounts if isinstance(a, str) and a.strip())
        if not labels:
            raise Refused("the bridge needs an explicit codex account allow-list (--accounts LABEL[,LABEL] or "
                          "<state>/config.json accounts); there is no default to every account")
        banned = [a for a in labels if a in FORBIDDEN_LABELS]
        if banned:
            raise Refused(f"account labels {banned} are forbidden for the bridge (user rule: acct1/acct2 never run)")
        self.accounts = labels
        if self.workspace_root is None:
            self.workspace_root = Path(self.machine_path or DEFAULT_MACHINE_PATH).resolve().parent.parent
        self.workspace_root = Path(self.workspace_root)

    @property
    def secret_path(self) -> Path:
        return self.state_dir / SECRET_NAME

    @property
    def jobs_dir(self) -> Path:
        return self.state_dir / "jobs"
