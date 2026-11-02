"""Reuse the audio converter with strict socket/semantic roundtrip checks."""
import copy

from ..audio.gui import api_to_gui
from ..core.errors import Refused
from .definitions import normalize_definitions


def convert_gui(api, object_info, *, title, extra):
    if any(not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key or int(key) < 1 for key in api):
        raise Refused("GUI_NODE_ID: API node IDs must be canonical positive decimal strings")
    prepared = copy.deepcopy(api)
    infos = {nid: normalize_definitions(prepared, object_info, instance_id=nid)[node["class_type"]]
             for nid, node in prepared.items()}
    for info in infos.values():
        if not info.get("output_name"):
            info["output_name"] = list(info.get("output") or [])
    try:
        gui = api_to_gui(prepared, object_info, title=title, extra=extra, node_infos=infos)
    except (KeyError, ValueError, IndexError, TypeError) as error:
        raise Refused(f"GUI_CONVERT: cannot preserve the prepared graph: {error}") from error
    links = {link[0]: link for link in gui["links"]}
    for node in gui["nodes"]:
        # A primitive widget without a converted wire is not an input socket.
        node["inputs"] = [entry for entry in node["inputs"] if not entry.get("widget") or entry.get("link") is not None]
        restored = dict(node["widgets_values_named"])
        for index, entry in enumerate(node["inputs"]):
            if entry.get("link") is None:
                continue
            link = links[entry["link"]]
            link[4] = index
            restored[entry["name"]] = [str(link[1]), link[2]]
        original = api[str(node["id"])]["inputs"]
        if any(key not in restored or restored[key] != value for key, value in original.items()):
            raise Refused(f"GUI_ROUNDTRIP: node {node['id']} lost a prepared input or wire")
    return gui
