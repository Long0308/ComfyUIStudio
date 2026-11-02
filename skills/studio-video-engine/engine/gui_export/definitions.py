"""Expand measured ComfyUI V3 autogrow input definitions for API->GUI export.

``audio.gui.api_to_gui`` consumes ordinary required/optional definitions.
ComfyUI's live ``COMFY_AUTOGROW_V3`` metadata instead declares a group such as
``ref_images`` while API graphs bind ``ref_images.ref_image_0``.  Flatten only
the concrete ports present in the approved API graph, using the server's
template type; never guess IMAGE/AUDIO from an input name.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

from ..core.errors import Refused


def normalize_definitions(api: dict[str, Any], object_info: Callable[[str], dict], *, instance_id: str | None = None) -> dict[str, dict]:
    """Return class->definition for ``api_to_gui(api, result.__getitem__, ...)``.

    Repeated instances of one class share the union of their concrete optional
    sockets. Unbound optional sockets do not add values to a submitted graph.
    Unknown API fields and unrecognised autogrow shapes are refused because
    silently dropping one could detach an approved reference from inference.
    """
    infos = {node["class_type"]: copy.deepcopy(object_info(node["class_type"])) for node in api.values()}
    for class_type, info in infos.items():
        if not isinstance(info, dict):
            raise Refused(f"GUI_OBJECT_INFO: missing definition for {class_type}")
        sections = info.get("input") or {}
        originals = {name: spec for section in ("required", "optional", "hidden")
                     for name, spec in (sections.get(section) or {}).items()}
        instances = [node for nid, node in api.items() if node["class_type"] == class_type
                     and (instance_id is None or nid == instance_id)]
        names = {name for node in instances for name in node.get("inputs", {})}
        known = set(originals)
        for section in ("required", "optional"):
            specs = sections.get(section) or {}
            order = (info.setdefault("input_order", {}).get(section) or list(specs))
            flattened: dict[str, Any] = {}
            new_order = []
            for name in order:
                spec = specs[name]
                kind = spec[0] if isinstance(spec, (list, tuple)) and spec else None
                if len(spec) > 1 and isinstance(spec[1], dict) and spec[1].get("hidden"):
                    if name in names:
                        raise Refused(f"GUI_OBJECT_INFO: hidden API input {class_type}.{name} cannot be represented")
                    continue
                if kind == "COMFY_DYNAMICCOMBO_V3":
                    if len(instances) > 1:
                        raise Refused(f"GUI_DYNAMICCOMBO: normalize per instance for {class_type}.{name}")
                    if not instances:
                        continue
                    def expand(path, child_spec):
                        if not isinstance(child_spec, (list, tuple)) or not child_spec:
                            raise Refused(f"GUI_DYNAMICCOMBO: invalid schema for {class_type}.{path}")
                        if child_spec[0] != "COMFY_DYNAMICCOMBO_V3":
                            if child_spec[0] not in ("STRING", "INT", "FLOAT", "BOOLEAN", "COMBO") and not isinstance(child_spec[0], list):
                                raise Refused(f"GUI_DYNAMICCOMBO: unsupported child for {class_type}.{path}")
                            flattened[path] = copy.deepcopy(child_spec)
                            new_order.append(path)
                            known.add(path)
                            return
                        opts = child_spec[1].get("options") if len(child_spec) == 2 and isinstance(child_spec[1], dict) else None
                        if not isinstance(opts, list) or not opts or any(not isinstance(o, dict) or not isinstance(o.get("key"), str) for o in opts):
                            raise Refused(f"GUI_DYNAMICCOMBO: invalid options for {class_type}.{path}")
                        values = [o["key"] for o in opts]
                        if len(values) != len(set(values)):
                            raise Refused(f"GUI_DYNAMICCOMBO: duplicate options for {class_type}.{path}")
                        inputs = instances[0].setdefault("inputs", {})
                        value = inputs.setdefault(path, values[0])
                        if value not in values:
                            raise Refused(f"GUI_DYNAMICCOMBO: invalid selection for {class_type}.{path}")
                        flattened[path] = [values, {}]
                        new_order.append(path)
                        known.add(path)
                        branch = opts[values.index(value)].get("inputs") or {}
                        for subsection in ("required", "optional"):
                            for key, sub in (branch.get(subsection) or {}).items():
                                subpath = path + "." + key
                                if subpath not in inputs and sub[0] != "COMFY_DYNAMICCOMBO_V3":
                                    config = sub[1] if len(sub) > 1 and isinstance(sub[1], dict) else {}
                                    if "default" not in config:
                                        raise Refused(f"GUI_DYNAMICCOMBO: missing default for {class_type}.{subpath}")
                                    inputs[subpath] = config["default"]
                                expand(subpath, sub)
                    expand(name, spec)
                    continue
                if not isinstance(kind, str) or not kind.startswith("COMFY_AUTOGROW"):
                    flattened[name] = spec
                    new_order.append(name)
                    continue
                if kind != "COMFY_AUTOGROW_V3" or len(spec) != 2 or not isinstance(spec[1], dict):
                    raise Refused(f"GUI_AUTOGROW: unsupported definition for {class_type}.{name}")
                options = spec[1]
                descriptor = options.get("template") or {}
                template = descriptor.get("input") or {}
                required = template.get("required") or {}
                prefix, limit = descriptor.get("prefix"), descriptor.get("max")
                if (len(required) != 1 or template.get("optional") or template.get("hidden")
                        or not isinstance(prefix, str) or not prefix
                        or type(limit) is not int or limit < 1):
                    raise Refused(f"GUI_AUTOGROW: unsupported template for {class_type}.{name}")
                child = next(iter(required.values()))
                if not isinstance(child, (list, tuple)) or not child or not isinstance(child[0], str):
                    raise Refused(f"GUI_AUTOGROW: invalid socket type for {class_type}.{name}")
                pattern = re.compile(re.escape(f"{name}.{prefix}") + r"(0|[1-9][0-9]*)")
                leaves = []
                for concrete in names:
                    match = pattern.fullmatch(concrete)
                    if match:
                        index = int(match[1])
                        if index >= limit:
                            raise Refused(f"GUI_AUTOGROW: {class_type}.{concrete} exceeds max {limit}")
                        leaves.append((index, concrete))
                for _, concrete in sorted(leaves):
                    flattened[concrete] = copy.deepcopy(child)
                    new_order.append(concrete)
                    known.add(concrete)
                    for node in instances:
                        if concrete not in node.get("inputs", {}):
                            continue
                        value = node["inputs"][concrete]
                        if (not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str)
                                or value[0] not in api or type(value[1]) is not int or value[1] < 0):
                            raise Refused(f"GUI_AUTOGROW: {class_type}.{concrete} needs an actual linked socket")
                        source = infos[api[value[0]]["class_type"]]
                        outputs = source.get("output") or []
                        if value[1] >= len(outputs) or outputs[value[1]] != child[0]:
                            raise Refused(f"GUI_AUTOGROW: source type mismatch at {class_type}.{concrete}")
                known.discard(name)
            sections[section] = flattened
            info["input_order"][section] = new_order
        unknown = names - known
        if unknown:
            raise Refused(f"GUI_OBJECT_INFO: undeclared API inputs for {class_type}: {sorted(unknown)}")
    return infos


__all__ = ["normalize_definitions"]
