"""The per-episode delivery contract: film length is a fact of the episode, not of the domain.

``episode.contract`` holds the hashed frame budget (main film, end card, total, every section in
order, vocabulary count).  The domain only keeps size, fps and the allowed ranges
(``delivery.length``, ``delivery.end_card``, ``delivery.sections``).  ``DELIVERY-CONTRACT.json`` is
GENERATED from the episode contract (``jjv config contract --write``) and its file sha256 is bound
into ``config_sha256``; a stale or hand-edited file fails ``config validate``.

Pure functions plus two small readers; the planning arithmetic is in :mod:`engine.config.budget`.
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import EngineError
from ..core.io import canonical_sha256, read_json
from .budget import Section, fixed_section_kinds, section_kinds, totals

REVIEW_TOTAL_KEYS = ("total_frames_with_endlogo", "total_frames")


def contract_sha256(contract: dict) -> str:
    """Canonical (ascii) sha256 of the contract without its own ``sha256`` field."""
    return canonical_sha256({k: v for k, v in contract.items() if k != "sha256"}, mode="ascii")


def build_contract(sections: list[Section], *, fps: int, revision: str, brand_intro_frames: int = 0,
                   inputs_sha256: str | None = None, extra: dict | None = None) -> dict:
    """A hashed contract block from allocated sections (what ``--write`` stores in episode.json)."""
    parts = totals(sections)
    rows = []
    for section in sections:
        row = {"id": section.id, "kind": section.kind, "frames": section.frames}
        if section.kind == "vocab_card" and ": WAV" in section.note:
            row["term"] = section.note.split(": WAV", 1)[0]
        if section.kind == "end_plate" and section.note.startswith("end line "):
            row["speech_frames"] = int(section.note.split()[2])
        rows.append(row)
    contract: dict = {
        "revision": revision, "fps": fps, **parts, "brand_intro_frames": brand_intro_frames,
        "vocab_count": sum(1 for s in sections if s.kind == "vocab_card"), "sections": rows,
    }
    if inputs_sha256:
        contract["inputs_sha256"] = inputs_sha256
    if extra:
        contract["extra"] = extra
    contract["sha256"] = contract_sha256(contract)
    return contract


def timeline_from_contract(contract: dict) -> dict:
    """The episode ``timeline`` block a contract implies (intro / dialogue / outro seconds, end card)."""
    fps = contract["fps"]
    by_kind: dict[str, int] = {}
    for row in contract["sections"]:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + row["frames"]
    intro, dialogue = by_kind.get("intro", 0), by_kind.get("dialogue", 0)
    outro = contract["main_frames"] - intro - dialogue
    line = {"intro_s": round(intro / fps, 9), "dialogue_s": round(dialogue / fps, 9), "outro_s": round(outro / fps, 9)}
    if contract["end_card_frames"] or "end_card" in by_kind:
        line.update(end_card_s=round(contract["end_card_frames"] / fps, 9), end_card_frames=contract["end_card_frames"])
    return line


def check_contract(episode: dict, domain: dict, shots: list[dict] | None = None) -> list[str]:
    """Every way a contract can contradict itself, the domain ranges, the timeline or the shots."""
    contract = episode.get("contract")
    if contract is None:
        return []
    problems: list[str] = []
    name, delivery = domain["domain_id"], domain["delivery"]
    fps = domain["frame_rates"]["delivery_fps"]
    if contract["fps"] != fps:
        problems.append(f"contract.fps {contract['fps']} != domain delivery_fps {fps}")
    rows = contract["sections"]
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("contract.sections: duplicate section ids")
    declared = section_kinds(domain)
    unknown = sorted({r["kind"] for r in rows if r["kind"] not in declared})
    if unknown:
        problems.append(f"contract.sections use kind(s) not declared by domain {name}: {unknown}")
    elif not fixed_section_kinds(domain):
        rank = {kind: index for index, kind in enumerate(declared)}
        ranks = [rank[r["kind"]] for r in rows]
        if ranks != sorted(ranks):
            problems.append(f"contract.sections must follow the film order {list(declared)}")
    if rows:
        if rows[-1]["kind"] != "end_card" and any(r["kind"] == "end_card" for r in rows):
            problems.append("contract.sections: end_card must be the last section")
        if rows[0]["kind"] != "intro" and any(r["kind"] == "intro" for r in rows):
            problems.append("contract.sections: intro must be the first section")
    if sum(1 for r in rows if r["kind"] == "end_card") > 1 or sum(1 for r in rows if r["kind"] == "logo_hold") > 1:
        problems.append("contract.sections: at most one logo_hold and one end_card")
    main = sum(r["frames"] for r in rows if r["kind"] != "end_card")
    card = sum(r["frames"] for r in rows if r["kind"] == "end_card")
    for key, actual in (("main_frames", main), ("end_card_frames", card), ("total_frames", main + card)):
        if contract[key] != actual:
            problems.append(f"contract.{key} {contract[key]} != sum of its sections {actual}")
    cards = sum(1 for r in rows if r["kind"] == "vocab_card")
    if contract["vocab_count"] != cards:
        problems.append(f"contract.vocab_count {contract['vocab_count']} != {cards} vocab_card sections")
    if contract["sha256"] != contract_sha256(contract):
        problems.append("contract.sha256 does not match the contract content (edited by hand? "
                        "run `jjv config contract --write`)")
    problems.extend(_check_ranges(contract, rows, name, delivery))
    problems.extend(_check_timeline(contract, episode["timeline"], fps))
    if shots is not None:
        problems.extend(_check_dialogue(rows, shots, domain))
    return problems


def _check_ranges(contract: dict, rows: list[dict], name: str, delivery: dict) -> list[str]:
    problems: list[str] = []
    length = delivery["length"]
    if not length["main_frames_min"] <= contract["main_frames"] <= length["main_frames_max"]:
        problems.append(f"contract.main_frames {contract['main_frames']} is outside the domain {name} range "
                        f"{length['main_frames_min']}..{length['main_frames_max']}")
    declared = set(section_kinds({"domain_id": name, "delivery": delivery}))
    allowed = {kind: section_block for kind in declared
               for kind, section_block in ((kind, (delivery.get("sections") or {}).get(kind)),)
               if section_block is not None}
    for row in rows:
        kind, frames = row["kind"], row["frames"]
        if kind in ("intro", "dialogue"):
            if frames < 1:
                problems.append(f"contract section {row['id']}: needs at least 1 frame")
        elif kind == "end_card":
            rule = delivery.get("end_card")
            if rule is None:
                problems.append(f"contract has an end_card but domain {name} delivery has no end_card allowance")
            elif not rule["frames_min"] <= frames <= rule["frames_max"]:
                problems.append(f"contract end card {frames} f is outside the domain {rule['frames_min']}.."
                                f"{rule['frames_max']}")
        elif kind not in allowed:
            problems.append(f"contract section {row['id']}: domain {name} defines no delivery.sections.{kind}")
        else:
            problems.extend(_check_section(row, allowed[kind], kind))
    return problems


def _check_section(row: dict, rule: dict, kind: str) -> list[str]:
    frames, label = row["frames"], row["id"]
    if kind == "end_plate":
        speech = row.get("speech_frames")
        if speech is None:
            return [f"contract section {label}: end_plate needs speech_frames (the end line length)"]
        low = speech + rule["lead_min"] + rule["tail_min"]
        if not low <= frames <= max(low, rule["max"]):
            return [f"contract section {label}: {frames} f outside {low}..{max(low, rule['max'])} "
                    f"(end line {speech} f + lead {rule['lead_min']} + tail {rule['tail_min']} minimum)"]
        return []
    if not rule["min"] <= frames <= rule["max"]:
        return [f"contract section {label} ({kind}): {frames} f is outside the domain range {rule['min']}..{rule['max']}"]
    return []


def _check_timeline(contract: dict, line: dict, fps: int) -> list[str]:
    implied = timeline_from_contract(contract)
    problems: list[str] = []
    for key in ("intro_s", "dialogue_s", "outro_s"):
        if round(line[key] * fps) != round(implied[key] * fps) or abs(line[key] * fps - round(line[key] * fps)) > 1e-4:
            problems.append(f"episode.timeline.{key} {line[key]} s disagrees with the contract "
                            f"({round(implied[key] * fps)} f)")
    if (line.get("end_card_frames") or 0) != contract["end_card_frames"]:
        problems.append(f"episode.timeline.end_card_frames {line.get('end_card_frames')} != contract "
                        f"{contract['end_card_frames']}")
    return problems


def _check_dialogue(rows: list[dict], shots: list[dict], domain: dict) -> list[str]:
    rates = domain["frame_rates"]
    num, den = rates["mapping"]["num"], rates["mapping"]["den"]
    dialogue = [r for r in rows if r["kind"] == "dialogue"]
    problems: list[str] = []
    if [r["id"] for r in dialogue] != [s["shot"] for s in shots]:
        return [f"contract dialogue sections {[r['id'] for r in dialogue]} differ from shots.json "
                f"{[s['shot'] for s in shots]}"]
    for row, shot in zip(dialogue, shots):
        expected = shot["clip"]["frames"] * num // den
        if row["frames"] != expected:
            problems.append(f"contract section {row['id']}: {row['frames']} f != clip {shot['clip']['frames']} native "
                            f"frames delivered as {expected} f")
    return problems


def render_delivery_contract(episode: dict, domain: dict) -> dict:
    """The DELIVERY-CONTRACT.json document generated from the episode contract (deterministic)."""
    contract, delivery = episode["contract"], domain["delivery"]
    master, fps = delivery["master"], contract["fps"]
    total, main, card = contract["total_frames"], contract["main_frames"], contract["end_card_frames"]
    extra = contract.get("extra") or {}
    status = extra.get("status", "not_rendered")
    document: dict = {
        "generated_by": "jjv config contract --write (do not edit by hand)",
        "film_id": episode["film_id"], "title": episode["title"], "production_domain": domain["domain_id"],
        "contract_revision": contract["revision"], "contract_sha256": contract["sha256"],
        "master": {"width": master["width"], "height": master["height"], "fps": fps,
                   "duration_s": round(total / fps, 9), "frames": total,
                   "main_film_duration_s": round(main / fps, 9), "main_film_frames": main,
                   "end_card_frames": card, "end_card_duration_s": round(card / fps, 9), "status": status},
        "sections": contract["sections"], "vocab_count": contract["vocab_count"],
        "brand_intro_frames": contract["brand_intro_frames"],
        "review": dict(delivery["review"]),
        "native_motion_fps": domain["frame_rates"]["native_fps"],
    }
    if card:
        document["end_card"] = {"frames": card, "duration_s": round(card / fps, 9), "starts_at_frame": main,
                                "separate_from_main_film": True, "status": status}
    film_2k = delivery.get("film_2k")
    if film_2k:
        document["film_2k"] = {"width": film_2k["width"], "height": film_2k["height"], "fps": fps,
                               "duration_s": round(total / fps, 9), "frames": total, "method": film_2k["method"],
                               "source": film_2k["source"], "status": status}
    document.update({k: v for k, v in extra.items() if k not in document and k != "status"})
    return document


def check_delivery_file(path: Path, episode: dict, domain: dict) -> list[str]:
    """The DELIVERY-CONTRACT.json on disk must equal the document generated from the episode."""
    if episode.get("contract") is None:
        return []
    try:
        found = read_json(path)
    except EngineError as error:
        return [f"delivery contract file: {error}"]
    if canonical_sha256(found, mode="ascii") != canonical_sha256(render_delivery_contract(episode, domain), mode="ascii"):
        return [f"{path.name} is not the file generated from episode.contract "
                f"(sha256 {contract_sha256(episode['contract'])[:12]}...): run `jjv config contract --write`"]
    return []


def review_config_total(document: dict) -> tuple[int | None, int | None]:
    """``(main_frames, total_frames)`` as a review config states them (None when it does not)."""
    main = document.get("main_frames")
    total = next((document[k] for k in REVIEW_TOTAL_KEYS if isinstance(document.get(k), int)), None)
    if total is None and isinstance(main, int) and isinstance(document.get("end_hold_frames"), int):
        total = main + document["end_hold_frames"]
    return (main if isinstance(main, int) else None), total


def check_review_config(path: Path, contract: dict) -> list[str]:
    """A review config whose lengths disagree with the contract fails validation."""
    try:
        document = read_json(path)
    except EngineError as error:
        return [f"files.review_config: {error}"]
    main, total = review_config_total(document if isinstance(document, dict) else {})
    problems: list[str] = []
    if total is None:
        problems.append(f"{path.name}: states no total frame count to compare with the contract")
    elif total != contract["total_frames"]:
        problems.append(f"{path.name}: total {total} f != contract total_frames {contract['total_frames']}")
    if main is not None and main != contract["main_frames"]:
        problems.append(f"{path.name}: main_frames {main} != contract main_frames {contract['main_frames']}")
    return problems
