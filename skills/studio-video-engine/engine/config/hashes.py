"""The two config hashes: the full one and the core one (which stage binds which: see HASHES.md).

``config_sha256``       every layer, including ``shots.json`` and ``mouth-boxes.json`` (when named; ``null``
                        otherwise) and the bytes of the generated DELIVERY-CONTRACT.json.  Stages whose output
                        depends on the shots bind this.
``config_core_sha256``  machine (without the private ``voicestudio`` / ``timing`` / ``audio`` blocks, the free-text
                        ``note``, the delivery/tool blocks ``brand`` / ``remotion`` / ``publish``: those are
                        delivery and tool paths, not render content, and ``legacy_roots``: where a retired tree
                        lives now, see engine/core/paths.py), domain, recipes and episode (without
                        ``engine_tree_sha256``): the parts a plan depends on whatever the shots say.  Writing
                        ``shots.json`` after a voice plan does not change it.
``stage_machine_sha256`` the one private machine block a stage reads (its tool paths / URL).

Nothing here touches the filesystem.
"""

from __future__ import annotations

from ..core.io import canonical_sha256

STAGE_MACHINE_KEYS = ("voicestudio", "timing", "audio")
_NOT_CORE_MACHINE = (*STAGE_MACHINE_KEYS, "note", "brand", "remotion", "publish",  # delivery/tool paths, not render content
                     "legacy_roots")                                                 # where a retired tree lives now: a location fact
_NOT_CORE_EPISODE = ("engine_tree_sha256",)


def core_body(machine: dict, domain: dict, recipes: dict, episode: dict) -> dict:
    return {
        "machine": {k: v for k, v in machine.items() if k not in _NOT_CORE_MACHINE},
        "domain": domain, "recipes": recipes,
        "episode": {k: v for k, v in episode.items() if k not in _NOT_CORE_EPISODE},
    }


def config_core_sha256(machine: dict, domain: dict, recipes: dict, episode: dict) -> str:
    return canonical_sha256(core_body(machine, domain, recipes, episode), mode="ascii")


def stage_machine_sha256(machine: dict, stage: str) -> str:
    """sha256 of ``machine[stage]`` (``{}`` when the block is absent), for ``stage`` in STAGE_MACHINE_KEYS."""
    if stage not in STAGE_MACHINE_KEYS:
        raise ValueError(f"stage must be one of {STAGE_MACHINE_KEYS}, got {stage!r}")
    return canonical_sha256(machine.get(stage) or {}, mode="ascii")


def full_body(body: dict, delivery_contract_sha256: str | None) -> dict:
    """The document ``config_sha256`` hashes: the resolved layers plus the delivery-contract file sha."""
    if delivery_contract_sha256 is None:
        return body
    return {**body, "delivery_contract_sha256": delivery_contract_sha256}
