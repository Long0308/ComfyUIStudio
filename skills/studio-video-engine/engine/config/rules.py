"""Cross-field and cross-layer rules (pure functions over already schema-valid dicts).

Every function returns a list of violation strings; nothing here touches the filesystem.
Rules are domain-neutral: they compare layers with each other and never name a domain.
"""

from __future__ import annotations

import copy
import math
import os
from fractions import Fraction
from typing import Any

from ..seedvr2.recipe import ALLOWED_PORT_PATHS

# Override keys address a lower layer: ``machine.<path>``, ``domain.<path>`` or
# ``recipe.<family>.<path>``.  An episode can only tighten these list-valued domain rules.
SUPERSET_ONLY = {"domain.forbidden_node_classes"}  # may add classes, never drop one (exact spelling)
SUBSET_ONLY = {"domain.allowed_custom_nodes", "domain.allowed_recipes"}  # may drop, never add

# Every domain must forbid these classes in render graphs (cloud call / authoring-only bridge).
REQUIRED_FORBIDDEN_CLASSES = ("ClaudeNode", "JJClaudeBridge")

_GRAPH_GEOMETRY_KEYS = (
    "processing_width", "processing_height", "tile_size", "tile_overlap",
    "internal_sampler_max_pixel_frames",
)


def same_value(left: Any, right: Any) -> bool:
    """JSON-style equality: True is not 1, 1 equals 1.0, lists compare in order."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_value(left[k], right[k]) for k in left)
    return type(left) is type(right) and left == right


def _lower(items: list[str]) -> set[str]:
    return {item.lower() for item in items}


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def check_machine(machine: dict) -> list[str]:
    problems: list[str] = []
    if not str(machine["gpu_lock_path"]).lower().endswith(".lock"):
        problems.append("machine.gpu_lock_path must name a .lock file")
    output = machine["comfy"].get("output_dir")
    if output:
        root = os.path.normcase(machine["comfy"]["root"]).rstrip("\\/") + os.sep
        if not (os.path.normcase(output) + os.sep).startswith(root):
            problems.append("machine.comfy.output_dir must live inside machine.comfy.root")
    labels = [row["label"] for row in ((machine.get("images") or {}).get("codex_accounts") or [])]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        problems.append(f"machine.images.codex_accounts labels must be unique, duplicated: {duplicates}")
    return problems


def check_domain(domain: dict, stem: str) -> list[str]:
    problems: list[str] = []
    name = domain["domain_id"]
    if name != stem:
        problems.append(f"domain file {stem}.json declares domain_id {name!r}")
    rates, master = domain["frame_rates"], domain["delivery"]["master"]
    mapping = rates["mapping"]
    if rates["delivery_fps"] * mapping["den"] != rates["native_fps"] * mapping["num"]:
        problems.append(
            f"domain {name}: mapping {mapping['num']}/{mapping['den']} does not turn "
            f"{rates['native_fps']} fps into {rates['delivery_fps']} fps"
        )
    if master["fps"] != rates["delivery_fps"]:
        problems.append(f"domain {name}: master fps {master['fps']} != delivery_fps")
    problems.extend(_check_ranges(domain, name))
    film_2k = domain["delivery"].get("film_2k")
    if film_2k is not None:
        if film_2k["width"] * master["height"] != film_2k["height"] * master["width"]:
            problems.append(f"domain {name}: delivery.film_2k must keep the master aspect ratio")
        if film_2k["width"] >= master["width"] or film_2k["height"] >= master["height"]:
            problems.append(f"domain {name}: delivery.film_2k must be smaller than the master")
    forbidden = _lower(domain["forbidden_node_classes"])
    for required in REQUIRED_FORBIDDEN_CLASSES:  # exact spelling, never loosened
        if required not in domain["forbidden_node_classes"]:
            problems.append(f"domain {name}: forbidden_node_classes must contain {required}")
    clash = forbidden & _lower(domain["allowed_custom_nodes"])
    if clash:
        problems.append(f"domain {name}: node(s) both allowed and forbidden: {sorted(clash)}")
    return problems


def _check_ranges(domain: dict, name: str) -> list[str]:
    """The domain keeps ranges, not a film length: every min must not exceed its max."""
    delivery, problems = domain["delivery"], []
    length = delivery["length"]
    if length["main_frames_min"] > length["main_frames_max"]:
        problems.append(f"domain {name}: delivery.length main_frames_min > main_frames_max")
    card = delivery.get("end_card")
    if card is not None and card["frames_min"] > card["frames_max"]:
        problems.append(f"domain {name}: delivery.end_card frames_min > frames_max")
    for kind, block in (delivery.get("sections") or {}).items():
        if "min" in block and block["min"] > block["max"]:
            problems.append(f"domain {name}: delivery.sections.{kind} min > max")
    return problems


def check_recipe(recipe: dict) -> list[str]:
    problems: list[str] = []
    rid, geo, graph = recipe["recipe_id"], recipe["geometry"], recipe["graph_recipe"]
    if rid.split("/", 1)[0] != recipe["family"]:
        problems.append(f"recipe {rid}: id prefix does not match family {recipe['family']!r}")
    if geo["core_frames"] + 2 * geo["context_frames_each_side"] != geo["max_raw_segment_frames"]:
        problems.append(f"recipe {rid}: core + 2*context != max_raw_segment_frames")
    if geo["tile_overlap"] >= geo["tile_size"]:
        problems.append(f"recipe {rid}: tile_overlap must be smaller than tile_size")
    if geo["internal_sampler_max_pixel_frames"] > geo["max_raw_segment_frames"]:
        problems.append(f"recipe {rid}: internal sampler frames exceed the raw segment")
    if geo["final_width"] + geo["final_crop_left"] > geo["processing_width"] or (
        geo["final_height"] + geo["final_crop_top"] > geo["processing_height"]
    ):
        problems.append(f"recipe {rid}: final crop window does not fit inside the processing size")
    native = recipe["native"]
    if native["width"] * geo["processing_height"] != native["height"] * geo["processing_width"]:
        problems.append(f"recipe {rid}: processing size changes the native aspect ratio")
    try:
        if Fraction(geo["fps"]) <= 0:
            problems.append(f"recipe {rid}: fps must be positive")
    except (ZeroDivisionError, ValueError):
        problems.append(f"recipe {rid}: fps {geo['fps']!r} is not a fraction")
    if set(recipe["allowed_api_diff_paths"]) != ALLOWED_PORT_PATHS:
        problems.append(
            f"recipe {rid}: allowed_api_diff_paths must be exactly {sorted(ALLOWED_PORT_PATHS)}, "
            f"got {sorted(recipe['allowed_api_diff_paths'])}")
    for key in _GRAPH_GEOMETRY_KEYS:
        if key in graph and not same_value(graph[key], geo[key]):
            problems.append(f"recipe {rid}: graph_recipe.{key} {graph[key]!r} != geometry.{key}")
    for graph_key, model in (("model_file", "diffusion"), ("vae", "vae")):
        if graph.get(graph_key) != recipe["models"][model]["file"]:
            problems.append(f"recipe {rid}: graph_recipe.{graph_key} != models.{model}.file")
    return problems


def check_recipe_in_domain(recipe: dict, domain: dict) -> list[str]:
    """The domain owns the allow-list; a recipe is only ever valid in its own domain."""
    problems: list[str] = []
    rid, name = recipe["recipe_id"], domain["domain_id"]
    if recipe["domain"] != name:
        problems.append(f"recipe {rid} is qualified for domain {recipe['domain']!r}, not {name!r}")
    if rid not in domain["allowed_recipes"]:
        problems.append(
            f"recipe {rid} is not in domain {name!r} allowed_recipes {domain['allowed_recipes']!r}"
        )
    rates, master = domain["frame_rates"], domain["delivery"]["master"]
    try:
        if Fraction(recipe["geometry"]["fps"]) != rates["native_fps"]:
            problems.append(f"recipe {rid}: fps {recipe['geometry']['fps']} != domain native fps")
    except (ZeroDivisionError, ValueError):
        pass  # already reported by check_recipe
    geo = recipe["geometry"]
    if (geo["final_width"], geo["final_height"]) != (master["width"], master["height"]):
        problems.append(f"recipe {rid}: final size != domain master size")
    return problems


def _lookup(base: dict, dotted: str) -> tuple[bool, Any]:
    node: Any = base
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def check_overrides(overrides: dict, base: dict) -> list[str]:
    """An episode may restate a lower-layer value or tighten a list rule; nothing else.

    ``base`` is ``{"machine": ..., "domain": ..., "recipe": {family: recipe}}``.
    """
    problems: list[str] = []
    for key, wanted in overrides.items():
        found, current = _lookup(base, key)
        if not found:
            problems.append(f"override {key!r}: no such key in machine/domain/recipe")
        elif key in SUPERSET_ONLY | SUBSET_ONLY and not _string_list(wanted):
            problems.append(f"override {key!r}: must be a list of strings, got {wanted!r}")
        elif key in SUPERSET_ONLY:
            if not set(current) <= set(wanted):
                problems.append(
                    f"override {key!r}: may add entries but never drop one of {current!r} "
                    f"(exact spelling), got {wanted!r}")
        elif key in SUBSET_ONLY:
            if not set(wanted) <= set(current):
                problems.append(f"override {key!r}: may only narrow {current!r}, got {wanted!r}")
        elif not same_value(wanted, current):
            problems.append(
                f"override {key!r}: episode value {wanted!r} would loosen locked value {current!r}"
            )
    return problems


def apply_tightening(domain: dict, overrides: dict) -> dict:
    """Return a copy of ``domain`` with accepted list tightenings applied.

    Call only for overrides that passed :func:`check_overrides`.  Forbidden classes are the
    domain list plus new entries (a union, never a replacement); narrowing keeps domain order.
    """
    resolved = copy.deepcopy(domain)
    for key in SUPERSET_ONLY:
        if key in overrides:
            name = key.split(".", 1)[1]
            resolved[name] = [*domain[name], *(x for x in dict.fromkeys(overrides[key]) if x not in domain[name])]
    for key in SUBSET_ONLY:
        if key in overrides:
            name = key.split(".", 1)[1]
            resolved[name] = [x for x in domain[name] if x in overrides[key]]
    return resolved


def check_timeline(episode: dict, domain: dict) -> list[str]:
    """The timeline must land on whole frames inside the domain length range and agree with the contract.

    The domain no longer fixes a film length: it keeps ``delivery.length`` (min/max main film frames) and
    ``delivery.end_card`` (min/max end card frames).  An episode that carries a ``contract`` is checked
    against it by :func:`engine.config.contract.check_contract`; one without a contract is only held to the
    domain ranges.  An end card sits after the main film and can never grant itself a length the domain
    does not allow.
    """
    problems: list[str] = []
    line, delivery = episode["timeline"], domain["delivery"]
    fps = domain["frame_rates"]["delivery_fps"]
    exact = fps * (line["intro_s"] + line["dialogue_s"] + line["outro_s"])
    if not math.isfinite(exact):
        return [f"episode.timeline sums to {exact} frames, not a finite number"]
    if abs(exact - round(exact)) > 1e-4:
        problems.append(f"episode.timeline sums to {exact} frames, not a whole number of frames")
    length = delivery["length"]
    if not length["main_frames_min"] <= round(exact) <= length["main_frames_max"]:
        problems.append(f"episode.timeline main film {round(exact)} frames is outside the domain range "
                        f"{length['main_frames_min']}..{length['main_frames_max']}")
    seconds, frames = line.get("end_card_s"), line.get("end_card_frames")
    if (seconds is None) != (frames is None):
        problems.append("episode.timeline end_card_s and end_card_frames must be given together")
    elif frames is not None:
        expected = round(seconds * fps)
        if frames != expected:
            problems.append(f"episode.timeline end_card_frames {frames} != end_card_s*delivery_fps {expected}")
        allowance = delivery.get("end_card")
        if frames == 0:
            pass  # no end card; nothing to allow
        elif allowance is None:
            problems.append("episode.timeline declares an end card but the domain delivery has no end_card allowance")
        elif not allowance["frames_min"] <= frames <= allowance["frames_max"]:
            problems.append(
                f"episode.timeline end card {frames} frames is outside the domain end_card range "
                f"{allowance['frames_min']}..{allowance['frames_max']}")
    return problems


def timeline_frames(episode: dict, domain: dict) -> dict:
    """Frame totals of a valid episode: main film, end card and the whole master file.

    The contract is the single source when the episode has one; otherwise they come from the timeline.
    """
    fps, contract = domain["frame_rates"]["delivery_fps"], episode.get("contract")
    if contract is not None:
        return {"main_frames": contract["main_frames"], "end_card_frames": contract["end_card_frames"],
                "total_frames": contract["total_frames"], "total_s": contract["total_frames"] / fps}
    line = episode["timeline"]
    main = round(fps * (line["intro_s"] + line["dialogue_s"] + line["outro_s"]))
    card = line.get("end_card_frames") or 0
    return {"main_frames": main, "end_card_frames": card, "total_frames": main + card,
            "total_s": (main + card) / fps}


def check_shots(episode: dict, domain: dict, shots: list[dict], boxes: dict | None) -> list[str]:
    problems: list[str] = []
    ids = [shot["shot"] for shot in shots]
    if len(set(ids)) != len(ids):
        problems.append("shots.json: duplicate shot ids")
    index = {shot["shot"]: shot for shot in shots}
    for position, shot in enumerate(shots):
        problems.extend(_check_one_shot(shot, index, ids[:position]))
    native = domain["frame_rates"]["native_fps"]
    expected = round(episode["timeline"]["dialogue_s"] * native)
    total = sum(shot["clip"]["frames"] for shot in shots)
    if total != expected:
        problems.append(f"shots.json: clip frames sum {total} != timeline.dialogue_s*native_fps {expected}")
    if boxes is not None:   # mouth-boxes are optional (M8b-e2); when named they must agree with shots.json
        problems.extend(_check_boxes(shots, boxes))
    return problems


def _check_one_shot(shot: dict, index: dict, earlier: list[str]) -> list[str]:
    problems: list[str] = []
    name, entry = shot["shot"], shot["entry"]
    if not name.startswith(shot["logical_shot"]):
        problems.append(f"shot {name}: logical_shot {shot['logical_shot']!r} is not its prefix")
    if shot["speaker"] == shot["listener"]:
        problems.append(f"shot {name}: speaker and listener are the same character")
    if entry["kind"] == "carry":
        source = entry.get("from_shot")
        if source not in earlier:
            problems.append(f"shot {name}: carry from_shot {source!r} is not an earlier shot")
        elif "frame" not in entry or entry["frame"] >= index[source]["clip"]["frames"]:
            problems.append(f"shot {name}: carry frame missing or beyond {source} clip length")
    elif "from_shot" in entry or "frame" in entry:
        problems.append(f"shot {name}: a cut must not name from_shot/frame")
    return problems


def _check_boxes(shots: list[dict], boxes: dict) -> list[str]:
    problems: list[str] = []
    table = boxes["shots"]
    if set(table) != {shot["shot"] for shot in shots}:
        problems.append("mouth-boxes.json: shot set differs from shots.json")
    for shot in shots:
        tracks = table.get(shot["shot"], {})
        frames = shot["clip"]["frames"]
        for role in ("speaker", "listener"):
            who = shot[role]
            track = tracks.get(who)
            if track is None or track["role"] != role:
                problems.append(f"mouth-boxes {shot['shot']}: no {role} track for {who!r}")
                continue
            problems.extend(_check_track(shot["shot"], who, track, frames))
    return problems


def _check_track(shot: str, who: str, track: dict, frames: int) -> list[str]:
    problems: list[str] = []
    marks = [key[0] for key in track["keyframes"]]
    if marks != sorted(set(marks)) or marks[-1] >= frames:
        problems.append(f"mouth-boxes {shot}/{who}: key frames must be increasing and inside {frames} frames")
    active = track["active_frames"]
    if active is not None and not (0 <= active[0] <= active[1] < frames):
        problems.append(f"mouth-boxes {shot}/{who}: active_frames outside the clip")
    return problems
