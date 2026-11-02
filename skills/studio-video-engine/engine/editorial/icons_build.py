"""``jjv icons build``: vocabulary asset manifest + locked script -> the icon registry (version 1).

Spoken words come from the script's ``vocabulary_cards``.  A compound card (``Warm and Cold``) teaches
one spoken word per part: when the asset set has an icon for every part (``warm``, ``cold``) each word
gets its own and the card keeps its own icon; when it has not, every part points at the card icon and
the registry gate refuses it as a shared icon unless ``--allow-shared`` marks it as intentional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import icons as reg


def load_attributes(*paths: Path | None) -> dict[str, str]:
    """``{icon id: distinguishing attribute}`` from ``{id: text}`` files or the prompt document
    (``icons[]`` with ``id`` + ``attribute`` or ``prompt``); later files override earlier ones."""
    out: dict[str, str] = {}
    for path in (p for p in paths if p):
        doc = read_json(Path(path))
        if isinstance(doc, dict) and isinstance(doc.get("icons"), list):
            for row in doc["icons"]:
                text = row.get("attribute") or row.get("prompt")
                if row.get("id") and isinstance(text, str) and text.strip():
                    out[row["id"]] = text.strip()
        elif isinstance(doc, dict):
            out.update({k: v.strip() for k, v in doc.items() if isinstance(v, str) and v.strip()})
        else:
            raise Refused(f"{path}: expected an object of icon id -> attribute or a prompt document")
    return out


def plan_terms(cards: list[dict], icon_ids: set[str], separators: list[str]) -> tuple[dict, dict]:
    """(terms, cards) of the registry from the script's vocabulary cards and the available icon ids."""
    terms: dict[str, dict] = {}
    card_rows: dict[str, dict] = {}
    for card in cards:
        term, card_icon = card.get("term"), card.get("icon")
        if not term or not card_icon:
            raise Refused(f"script vocabulary card without term/icon: {card!r}")
        if card_icon not in icon_ids:
            raise Refused(f"card {term!r}: icon id {card_icon!r} is not in the asset manifest")
        parts = reg.split_compound(term, separators)
        if len(parts) > 1 and all(reg.slug(p) in icon_ids for p in parts):
            spoken = [(p.lower(), reg.slug(p)) for p in parts]
        else:
            spoken = [(p.lower(), card_icon) for p in parts]
        phrases = []
        for key, icon in spoken:
            if key in terms:
                raise Refused(f"spoken term {key!r} appears in two vocabulary cards")
            terms[key] = {"icon": icon, "aliases": [], "card": term}
        for alias in card.get("aliases", []):
            hits = [k for k, _ in spoken if set(reg.norm(k).split()) & set(reg.norm(alias).split())]
            if len(spoken) == 1 or len(hits) == 1:
                key = spoken[0][0] if len(spoken) == 1 else hits[0]
                if reg.norm(alias) != reg.norm(key) and alias not in terms[key]["aliases"]:
                    terms[key]["aliases"].append(alias)
            elif alias not in phrases:
                phrases.append(alias)
        card_rows[term] = {"icon": card_icon, "spoken": [k for k, _ in spoken], "phrases": phrases}
    return terms, card_rows


def _pairs(terms: dict, recipe: dict) -> dict[str, str]:
    """icon id -> icon id of its opposite (recipe pairs, matched on spoken terms), both directions."""
    by_norm = {reg.norm(k): row["icon"] for k, row in terms.items()}
    out: dict[str, str] = {}
    for a, b in recipe["opposite_pairs"]:
        ia, ib = by_norm.get(reg.norm(a)), by_norm.get(reg.norm(b))
        if ia and ib and ia != ib:
            out[ia], out[ib] = ib, ia
    return out


def _manifest_icons(manifest_path: Path, root: Path) -> dict[str, dict]:
    manifest = read_json(manifest_path)
    rows = manifest.get("terms") if isinstance(manifest, dict) else None
    if not rows:
        raise Refused(f"{manifest_path}: no terms[] (not a vocabulary asset manifest)")
    out = {}
    for row in rows:
        png = Path(manifest_path).parent / "png" / Path(row["png_path"]).name
        if not png.is_file():
            raise Refused(f"manifest icon {row['id']!r}: {png} does not exist")
        if sha256_file(png) != row["png_sha256"]:
            raise Refused(f"manifest icon {row['id']!r}: {png.name} differs from the manifest sha256")
        out[row["id"]] = {"row": row, "png": png}
    return out


def build_registry(*, episode_id: str, root: Path, manifest_path: Path, script_path: Path, recipe: dict,
                   recipe_sha: str, ffmpeg: str, attributes: dict[str, str] | None = None,
                   allow_shared: tuple[str, ...] = (),
                   measure_fn: Callable[[Path, dict, str], dict] = reg.measure) -> dict:
    """Registry version 1 (not yet validated: ``icons_check.validate_registry`` is the gate)."""
    root = Path(root)
    available = _manifest_icons(Path(manifest_path), root)
    script = read_json(Path(script_path))
    if script.get("film_id") not in (None, episode_id):
        raise Refused(f"script film_id {script.get('film_id')!r} != episode {episode_id!r}")
    terms, cards = plan_terms(script.get("vocabulary_cards") or [], set(available), recipe["compound_separators"])
    used = {row["icon"] for row in terms.values()} | {row["icon"] for row in cards.values()}
    unknown = sorted(set(allow_shared) - used)
    if unknown:
        raise Refused(f"--allow-shared names icons the episode does not use: {unknown}")
    pairs, notes = _pairs(terms, recipe), attributes or {}
    spoken_ids = {row["icon"] for row in terms.values()}
    icons: dict[str, dict] = {}
    for icon_id in sorted(used, key=list(available).index):
        row, png = available[icon_id]["row"], available[icon_id]["png"]
        facts = measure_fn(png, recipe, ffmpeg)
        approved = bool(row.get("production_approved"))
        icons[icon_id] = {
            "id": icon_id, "label": row["term"], "kind": "spoken" if icon_id in spoken_ids else "card",
            "file": png.name, "png": reg.episode_relative(png, root), "sha256": row["png_sha256"],
            "bytes": png.stat().st_size, "size": facts["size"], "palette": facts["palette"],
            "attribute": notes.get(icon_id), "pair": pairs.get(icon_id),
            "status": "approved" if approved else "candidate", "approved": approved,
            "source_status": row.get("status"), "shared": icon_id in allow_shared}
    sources: dict[str, Any] = {
        "manifest": {"path": reg.episode_relative(Path(manifest_path), root), "sha256": sha256_file(Path(manifest_path))},
        "script": {"path": reg.episode_relative(Path(script_path), root), "sha256": sha256_file(Path(script_path))}}
    return reg.sealed({
        "schema": reg.SCHEMA, "episode_id": episode_id, "version": 1, "previous": None,
        "recipe": {"id": recipe["id"], "sha256": recipe_sha}, "sources": sources,
        "terms": terms, "cards": cards, "icons": icons,
        "history": [{"version": 1, "action": "build"}]})
