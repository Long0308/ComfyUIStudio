"""``jjv text build``: the Remotion kit's ``episode-text.json`` generated from the locked script.

No text is typed by hand.  Sources, in order:

* the locked script: ``title``, per-shot ``speech_text`` + ``dialogue_vi`` (EN/VI captions), the
  ``vocabulary_cards`` (IPA, Vietnamese meaning, example line);
* the icon registry: every card's icon (path + sha256) -- the only place the kit learns icon files;
* ``recipes/editorial/episode-text-v001.json``: brand strings that are true for every episode of the
  domain (kicker, card headers, closing line) and the layout rules (title break, two-line captions);
* an optional copy file (``jjv/episode-copy/v1``) for episode copy the script does not carry yet
  (``intro.pill``, ``title_vi``): a missing pill is ``Refused``, never invented.

``assets.music`` / ``assets.ambience`` / ``ending`` are render parameters, not text: they are bound from
the files and the params document named on the command line, and listed in ``missing`` when absent.
The output has the same keys the kit adapter reads (``adapter-engine.cjs`` ``requireText``) plus
``title``, ``captions`` and ``endPlate``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import icons as reg

SCHEMA = "jjk-remotion-kit/episode-text/v1"
COPY_SCHEMA = "jjv/episode-copy/v1"
DEFAULT_RECIPE = reg.SKILL_ROOT / "recipes" / "editorial" / "episode-text-v001.json"
RECIPE_SCHEMA = "jjv/episode-text-recipe/v1"


def load_recipe(path: Path | None = None) -> tuple[dict, str]:
    target = Path(path) if path else DEFAULT_RECIPE
    recipe = read_json(target)
    if not isinstance(recipe, dict) or recipe.get("schema") != RECIPE_SCHEMA:
        raise Refused(f"{target.name}: not a {RECIPE_SCHEMA} document")
    return recipe, sha256_file(target)


def check_locked(script_path: Path, shot_pack: dict) -> None:
    """The script must be the one the locked shot pack was built from (its recorded sha256)."""
    want = (shot_pack.get("source_provenance") or {}).get("script_sha256")
    have = sha256_file(Path(script_path))
    if want != have:
        raise Refused(f"E_SCRIPT_NOT_LOCKED: {Path(script_path).name} sha256 {have[:12]} is not the script the shot pack "
                      f"was built from ({str(want)[:12]})")


def bind_asset(root: Path, path: str, label: str) -> dict:
    """``{path, sha256}`` of an episode-relative file (the adapter re-verifies it)."""
    target = Path(root) / path
    if not target.is_file():
        raise Refused(f"{label}: {target} does not exist")
    return {"path": Path(path).as_posix(), "sha256": sha256_file(target)}


def opening_from_pack(shot_pack: dict, root: Path, recipe: dict, *, required: bool = True) -> dict | None:
    """The intro image the shot pack approved; None when the pack has none and ``required`` is False."""
    anchor = (shot_pack.get("approved_anchors") or {}).get(recipe["opening_anchor"])
    if not anchor:
        if not required:
            return None
        raise Refused(f"shot pack has no approved anchor {recipe['opening_anchor']!r} (the intro image)")
    bound = bind_asset(root, anchor["path"], "opening anchor")
    if bound["sha256"] != anchor["sha256"]:
        raise Refused(f"opening anchor {anchor['path']}: sha256 differs from the shot pack's")
    return bound


def load_copy(path: Path | None) -> dict:
    if path is None:
        return {}
    doc = read_json(Path(path))
    if not isinstance(doc, dict) or doc.get("schema") != COPY_SCHEMA:
        raise Refused(f"{path}: not a {COPY_SCHEMA} document")
    return doc


def title_lines(title: str, breakers: list[str]) -> list[str]:
    """``Cats and Dogs`` -> [Cats, and Dogs]: break before the first connecting word; else one line."""
    words = title.split()
    for i, word in enumerate(words):
        if i > 0 and word.lower() in {b.lower() for b in breakers}:
            return [" ".join(words[:i]), " ".join(words[i:])]
    return [title]


def _pair(pair: dict, joiner: str) -> str:
    return f"{pair['vi']}{joiner}{pair['en']}"


def _shots(script: dict, recipe: dict) -> tuple[dict, dict, dict]:
    vi, captions, lines = {}, {}, {}
    for shot in script.get("shots") or []:
        en = shot.get("speech_text") or shot.get("speech_text_draft")
        if not en or not shot.get("dialogue_vi"):
            raise Refused(f"script shot {shot.get('id')!r}: speech_text and dialogue_vi are required")
        two = len(shot["dialogue_vi"]) >= recipe["captions"]["two_line_min_chars_vi"]
        vi[shot["id"]] = shot["dialogue_vi"]
        captions[shot["id"]] = {"en": en, "vi": shot["dialogue_vi"], "lines": 2 if two else 1}
        if two:
            lines[shot["id"]] = 2
    if not vi:
        raise Refused("script has no shots")
    return vi, captions, lines


def _cards(script: dict, registry: dict) -> dict:
    out = {}
    for card in script.get("vocabulary_cards") or []:
        for key in ("term", "ipa", "vi", "example_en"):
            if not card.get(key):
                raise Refused(f"script vocabulary card {card.get('term')!r}: {key} is required")
        out[card["term"]] = {"ipa": card["ipa"], "vi": card["vi"], "exampleEn": card["example_en"],
                             "icon": reg.icon_ref(reg.icon_for_card(registry, card["term"]))}
        if card.get("example_vi"):
            out[card["term"]]["exampleVi"] = card["example_vi"]
    if not out:
        raise Refused("script has no vocabulary_cards")
    return out


def build_text(script: dict, registry: dict, recipe: dict, *, copy: dict | None = None, opening: dict | None = None,
               music: dict | None = None, ambience: dict | None = None,
               ending: dict | None = None) -> tuple[dict, list[str]]:
    """(episode text document, ``missing``: what the adapter will still demand and no input supplied)."""
    copy = copy or {}
    brand = recipe["brand"]
    joiner = brand["header_joiner"]
    vi, captions, lines = _shots(script, recipe)
    cards = _cards(script, registry)
    intro_src = (script.get("structure") or {}).get("intro") or {}
    pill = intro_src.get("pill_vi") or (copy.get("intro") or {}).get("pill")
    if not pill:
        raise Refused("E_COPY_MISSING: the intro pill line is in neither the script (structure.intro.pill_vi) nor the "
                      "copy file (intro.pill); it is not invented")
    title = script.get("title")
    if not title:
        raise Refused("script has no title")
    footer = recipe["intro"]["footer_template"].format(vocab_count=len(cards), shot_count=len(vi))
    doc: dict[str, Any] = {
        "schema": SCHEMA, "note": recipe["note"],
        "strings": {"cardsHeader": _pair(brand["cards_header"], joiner), "cardsHeaderClosing": _pair(brand["closing"], joiner)},
        "intro": {"kicker": brand["kicker"], "titleLines": title_lines(title, recipe["intro"]["title_break_before"]),
                  "pill": pill, "footer": footer, "mark": brand["intro_mark"]},
        "captionLines": lines, "shotVi": vi, "cards": cards}
    assets = {k: v for k, v in (("opening", opening), ("music", music), ("ambience", ambience)) if v}
    if assets:
        doc["assets"] = assets
    if ending:
        doc["ending"] = ending
    doc["title"] = {"en": title, "vi": script.get("title_vi") or copy.get("title_vi")}
    doc["captions"] = captions
    doc["endPlate"] = {"lines": [{"en": brand["closing"]["en"], "vi": brand["closing"]["vi"]}]}
    missing = [name for name, value in (("assets.opening", opening), ("assets.music", music), ("ending", ending)) if not value]
    if doc["title"]["vi"] is None:
        missing.append("title.vi (not in the script or the copy file; the kit does not read it)")
    return doc, missing


def diff_documents(generated: Any, reference: Any, *, ignore: tuple[str, ...] = ()) -> dict:
    """Field-by-field comparison of two JSON documents (dotted paths): ``equal`` count and ``diffs``."""
    equal = 0
    diffs: list[dict] = []

    def walk(a: Any, b: Any, path: str) -> None:
        nonlocal equal
        if path in ignore:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in list(b) + [k for k in a if k not in b]:
                sub = f"{path}.{key}" if path else key
                if key not in a:
                    if sub not in ignore:
                        diffs.append({"path": sub, "kind": "only_reference", "reference": b[key]})
                elif key not in b:
                    if sub not in ignore:
                        diffs.append({"path": sub, "kind": "only_generated", "generated": a[key]})
                else:
                    walk(a[key], b[key], sub)
        elif a == b:
            equal += 1
        else:
            diffs.append({"path": path, "kind": "changed", "generated": a, "reference": b})

    walk(generated, reference, "")
    return {"equal_fields": equal, "diff_count": len(diffs), "diffs": diffs}
