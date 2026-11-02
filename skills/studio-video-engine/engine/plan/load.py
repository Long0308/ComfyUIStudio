"""Read one version of the episode inputs (read-only) into :class:`PlanInputs`.

A version is a directory.  Either it holds ``plan-inputs.json`` (``jjv/plan-inputs/v1``: explicit pointers) or the legacy
review-hd layout is discovered: ``config/review-config*.json`` (or ``review-config*.json``), ``RECEIPT.json`` (mix plan + mix wav
sha), ``render-record-picture-*.json`` (pins), ``mix-plan*.json``.  Ambiguity is ``Refused`` (never a silent pick).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path

SCHEMA = "jjv/plan-inputs/v1"
DESCRIPTOR = "plan-inputs.json"
_SHA = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class PlanInputs:
    """One version of the inputs.  Documents are read-only by convention (never mutated by the planner)."""

    label: str
    root: str
    config: dict
    config_sha256: str
    segments_doc: dict | None = None
    mix_plan: dict | None = None
    mix_plan_sha256: str | None = None
    mix_wav_sha256: str | None = None
    gpu_cores: dict = field(default_factory=dict)
    core_receipts: dict = field(default_factory=dict)     # shot -> {"path", "verified"}
    pins: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    warnings: tuple = ()
    review_evidence: tuple = ()                           # M9b-4: descriptor refs {receipt, receipt_sha256, stage, shot, artifact_sha256}
    config_core_sha256: str | None = None                 # machine+domain+recipes+episode (contract included): see config/hashes.py
    unresolved: tuple = ()                                # inputs this version names that are not on disk: their nodes are UNCERTAIN


def _path(base: Path, value: str) -> Path:
    p = Path(value)
    return resolve_data_path(p) if p.is_absolute() else base / p


def _one(root: Path, patterns: tuple[str, ...], what: str) -> Path | None:
    for pattern in patterns:
        found = sorted(root.glob(pattern))
        if len(found) > 1:
            raise Refused(f"{root}: {len(found)} files match {pattern} ({', '.join(f.name for f in found)}); "
                          f"name the {what} in {DESCRIPTOR}")
        if found:
            return found[0]
    return None


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA


def _shas_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_shas_in(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_shas_in(v) for v in value)) if value else set()
    return {value} if _is_sha(value) else set()


def _checked(path: Path, expected: str | None, warnings: list[str], what: str) -> dict | None:
    """Read ``path``; a sha that disagrees with the receipt that named it is Refused, a missing file a warning."""
    if not path.is_file():
        warnings.append(f"{what} {path} is not on disk; its leaves are not compared")
        return None
    if expected and sha256_file(path) != expected:
        raise Refused(f"{what} {path}: sha256 {sha256_file(path)[:12]} differs from the {expected[:12]} its receipt names")
    return read_json(path)


def _mix_plan(root: Path, desc: dict, config: dict, receipt: dict | None,
              warnings: list[str]) -> tuple[dict | None, str | None, str | None, str | None]:
    """``(document, sha256, path, unresolved)``: a receipt/config path is read where it lives now (``resolve_data_path``);
    a plan that is still not on disk leaves ``unresolved`` naming it (audio.mix is then UNCERTAIN, never CHANGED)."""
    wav = ((receipt or {}).get("separate_deliverables") or {}).get("mix_wav") or {}
    outro = (config.get("mix") or {}).get("outro") or {}
    if desc.get("mix_plan"):
        path, expected = _path(root, desc["mix_plan"]), None
    elif wav.get("plan"):
        path, expected = resolve_data_path(wav["plan"]), wav.get("plan_sha256")
    elif _one(root, ("mix-plan*.json",), "mix_plan"):
        path, expected = _one(root, ("mix-plan*.json",), "mix_plan"), None
    elif outro.get("mix_plan"):
        path, expected = resolve_data_path(outro["mix_plan"]), outro.get("mix_plan_sha256")
    else:
        warnings.append("no mix plan found: audio.mix is compared on the config's mix block only")
        return None, None, None, None
    document = _checked(path, expected, warnings, "mix plan")
    if document is None:
        return None, None, str(path), f"mix plan {path} is not on disk"
    return document, sha256_file(path), str(path), None


def _mix_wav_sha(desc: dict, plan: dict | None, receipt: dict | None, config: dict) -> str | None:
    wav = ((receipt or {}).get("separate_deliverables") or {}).get("mix_wav") or {}
    candidates = (desc.get("mix_wav_sha256"), ((plan or {}).get("mix") or {}).get("sha256"), wav.get("sha256"),
                  ((config.get("mix") or {}).get("mix_wav") or {}).get("sha256"))
    return next((c for c in candidates if _is_sha(c)), None)


def _pins(root: Path, desc: dict, keys: list[str], warnings: list[str]) -> tuple[dict, str | None]:
    pins: dict = dict(desc.get("pins") or {})
    record = _path(root, desc["render_record"]) if desc.get("render_record") else _one(
        root, ("render-record-picture-*.json", "render-record*.json"), "render_record")
    if record is not None and record.is_file():
        data = read_json(record)
        found = {"compositor_sha256": (data.get("compositor") or {}).get("sha256"),
                 "remotion_version": data.get("remotion_version"), "chromium_gl": data.get("chromium_gl")}
        pins = {**{k: v for k, v in found.items() if v}, **pins}
    if not pins:
        warnings.append("no pins declared (no render record): pins are not compared")
    return {k: pins[k] for k in keys if k in pins}, (str(record) if record else None)


def _core_receipts(base: Path, desc: dict, config: dict) -> dict:
    out: dict = {}
    shas = {d["id"]: {s.get("sha256") for s in d.get("segments", [])} for d in config.get("dialogue", [])}
    for shot, spec in (desc.get("gpu_cores") or {}).items():
        ref = spec.get("core_receipt") if isinstance(spec, dict) else None
        if not ref:
            continue
        path = _path(base, ref)
        ok = path.is_file() and bool(shas.get(shot)) and shas[shot] <= _shas_in(read_json(path))
        out[shot] = {"path": str(path), "verified": ok}
    return out


_EVIDENCE_KEYS = ("receipt", "receipt_sha256", "stage", "shot", "artifact_sha256")


def _evidence(desc: dict, root: Path) -> tuple:
    """Optional ``review_evidence`` list of the descriptor (old descriptors have none -> notes stay unbound)."""
    raw = desc.get("review_evidence")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(e, dict) for e in raw):
        raise Refused(f"{root}: review_evidence must be a list of objects")
    for item in raw:
        if not isinstance(item.get("receipt"), str) or not _is_sha(item.get("receipt_sha256")):
            raise Refused(f"{root}: review_evidence needs receipt (str) and receipt_sha256 (64 hex)")
    return tuple({k: item.get(k) for k in _EVIDENCE_KEYS} for item in raw)


def load_inputs(location: str | Path, *, pin_keys: list[str], label: str | None = None) -> PlanInputs:
    """Load the version at ``location`` (a directory, or a descriptor file)."""
    target = Path(location)
    root = target.parent if target.is_file() else target
    if not root.is_dir():
        raise Refused(f"{target} is not a directory")
    descriptor = target if target.is_file() else root / DESCRIPTOR
    desc: dict = read_json(descriptor) if descriptor.is_file() else {}
    if desc and desc.get("schema") != SCHEMA:
        raise Refused(f"{descriptor}: schema must be {SCHEMA!r}")
    warnings: list[str] = []
    config_path = _path(root, desc["config"]) if desc.get("config") else _one(
        root, ("config/review-config*.json", "review-config*.json"), "config")
    if config_path is None or not config_path.is_file():
        raise Refused(f"{root}: no review config (config/review-config*.json) and none named in {DESCRIPTOR}")
    config = read_json(config_path)
    receipt_path = root / "RECEIPT.json"
    receipt = read_json(receipt_path) if receipt_path.is_file() else None
    plan, plan_sha, plan_path, unresolved = _mix_plan(root, desc, config, receipt, warnings)
    segments = read_json(_path(root, desc["segments"])) if desc.get("segments") else None
    pins, record = _pins(root, desc, pin_keys, warnings)
    core = desc.get("config_core_sha256", config.get("config_core_sha256"))
    if core is not None and not _is_sha(core):
        raise Refused(f"{root}: config_core_sha256 must be a 64-hex sha256, got {core!r}")
    evidence = _evidence(desc, root)
    sources = {"config": str(config_path), "mix_plan": plan_path, "render_record": record,
               "segments": str(_path(root, desc["segments"])) if desc.get("segments") else None}
    return PlanInputs(
        label=label or root.name, root=str(root), config=config, config_sha256=sha256_file(config_path),
        segments_doc=segments, mix_plan=plan, mix_plan_sha256=plan_sha,
        mix_wav_sha256=_mix_wav_sha(desc, plan, receipt, config), gpu_cores=dict(desc.get("gpu_cores") or {}),
        core_receipts=_core_receipts(descriptor.parent, desc, config), pins=pins, sources=sources,
        warnings=tuple(warnings), config_core_sha256=core, review_evidence=evidence,
        unresolved=(unresolved,) if unresolved else ())
