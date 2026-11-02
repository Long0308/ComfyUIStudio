"""Build the stage-node graph of ONE version of the inputs (T-E45 spec 1.2 / 1.3, the part the inputs let us see).

Nodes (``kind[instance]``): ``timing.words`` and ``editorial.build`` (CPU; the config already carries their output),
``motion.h3[shot]`` (GPU), ``composite.segment[seg]`` (+ ``mux``, ``qa.av``) for the review film, and for the master
``upscale.chunks[shot]`` (GPU), ``master.verify[shot]``, ``composite.master[seg]``, ``mux.master``, ``film.downscale.2k``;
``audio.mix`` (CPU).  There is no edge from any editorial / audio node back to a GPU node (spec 1.1, rule U6).
"""

from __future__ import annotations

from typing import Any, Mapping

from ..core.io import sha256_file
from ..core.paths import is_absolute_path_text, resolve_data_path
from . import shape, slices
from .load import PlanInputs
from .model import Node, node_key, sha

TARGETS = ("review", "master", "all")


class FileBinder:
    """Content identity for a file reference that carries no sha (``model.strip`` hands it the key and text): the
    sha256 of the file where it lives now (``resolve_data_path``).  A reference that cannot be read is recorded in
    ``unresolved`` and the node holding it is UNCERTAIN; a relative reference has no root here and is compared as
    written.  One binder per node, so the reason lands on the right row."""

    def __init__(self) -> None:
        self.unresolved: list[str] = []

    def __call__(self, key: str, text: str) -> Any:
        if not is_absolute_path_text(text):
            return text
        path = resolve_data_path(text)
        if path.is_file():
            return {"content_sha256": sha256_file(path)}
        self.unresolved.append(f"{key} {text} is not on disk (and no sha is recorded for it)")
        return text


def _h3_parts(inputs: PlanInputs, shot: Mapping[str, Any]) -> dict[str, Any]:
    declared = (inputs.gpu_cores.get(shot["id"]) or {}) if isinstance(inputs.gpu_cores, dict) else {}
    parts: dict[str, Any] = {"core.clips": shot["clips"], "core.native_frames": shot["native_frames"],
                             "input.wav": [shot["wav_sha256"], shot["wav_offset_frames"]]}
    for k, v in sorted(declared.items()):
        if k != "core_receipt" and not k.startswith("upscale_"):
            parts[f"input.{k}"] = v
    return parts


def _upscale_parts(inputs: PlanInputs, shot: Mapping[str, Any]) -> dict[str, Any]:
    declared = inputs.gpu_cores.get(shot["id"]) or {}
    parts: dict[str, Any] = {"core.clips": shot["clips"], "core.native_frames": shot["native_frames"]}
    parts.update({f"input.{k}": v for k, v in sorted(declared.items()) if k.startswith("upscale_")})
    return parts


def _segment_shots(config: dict, parts: Mapping[str, Any]) -> list[str]:
    return [name.split(":", 1)[1] for name in parts if name.startswith("shot:")]


def _core(inputs: PlanInputs) -> dict[str, Any]:
    """The config core hash as a slice part of the join nodes: a contract / domain / machine change shows up in
    ``plan explain`` (mux + qa re-run, CPU only) without re-compositing a segment or touching a GPU node."""
    return {"global.config_core_sha256": inputs.config_core_sha256} if inputs.config_core_sha256 else {}


def build_graph(inputs: PlanInputs, policy: Mapping[str, Any], pins: Mapping[str, Any],
                target: str = "review") -> dict[str, Node]:
    """Ordered ``id -> Node`` (topological: inputs before dependants)."""
    c = inputs.config
    nodes: dict[str, Node] = {}

    def add(node: Node) -> None:
        nodes[node.id] = node

    tparts = slices.timing_parts(c)
    add(Node("timing.words", "timing.words", "cpu", tparts, node_key("timing.words", tparts, {}),
             output=slices.words_output(c), materialised=True))
    binder = FileBinder()
    eparts = slices.editorial_parts(c, policy, binder)
    add(Node("editorial.build", "editorial.build", "cpu", eparts, node_key("editorial.build", eparts, {}),
             output=sha(eparts), deps=("timing.words",), materialised=True, meta={"unresolved": binder.unresolved}))
    shots = shape.shots(c)
    for shot in shots:
        parts = _h3_parts(inputs, shot)
        add(Node(f"motion.h3[{shot['id']}]", "motion.h3", "gpu", parts, node_key("motion.h3", parts, {}),
                 output=sha(shot["clips"]), meta={"shot": shot["id"], "native_frames": shot["native_frames"]}))
    binder = FileBinder()
    aparts = slices.audio_parts(inputs, policy, binder)
    add(Node("audio.mix", "audio.mix", "cpu", aparts, node_key("audio.mix", aparts, {}), output=inputs.mix_wav_sha256,
             meta={"unresolved": [*inputs.unresolved, *binder.unresolved]}))   # a named file not on disk: not comparable
    cuts = shape.cut_list(inputs)
    if target in ("review", "all"):
        _review(inputs, policy, pins, cuts, nodes, add)
    if target in ("master", "all"):
        _master(inputs, policy, pins, cuts, shots, nodes, add)
    return nodes


def _segment_meta(config: dict, seg: Mapping[str, Any]) -> dict[str, Any]:
    drawn = [s["id"] for s in shape.shots(config) if shape.overlap(*shape.shot_window(config, s), seg["start"], seg["end_exclusive"])]
    return {"seg_kind": seg["kind"], "start": seg["start"], "end_exclusive": seg["end_exclusive"],
            "frames": seg["end_exclusive"] - seg["start"], "shot_drawn": bool(drawn), "shots": drawn}


def _review(inputs, policy, pins, cuts, nodes, add) -> None:
    ids = []
    for seg in cuts:
        binder = FileBinder()
        parts = slices.video_parts(inputs.config, seg, policy, binder)
        node_id = f"composite.segment[{seg['id']}]"
        deps = tuple(f"motion.h3[{s}]" for s in _segment_shots(inputs.config, parts))
        add(Node(node_id, "composite.segment", "cpu", parts, node_key("composite.segment", parts, pins), deps=deps,
                 meta={**_segment_meta(inputs.config, seg), "unresolved": binder.unresolved}))
        ids.append(node_id)
    mux_parts = {"segments": [[i, nodes[i].key] for i in ids], "audio.mix": nodes["audio.mix"].key, **_core(inputs)}
    add(Node("mux", "mux", "cpu", mux_parts, node_key("mux", mux_parts, {}), deps=(*ids, "audio.mix"),
             meta={"segments": ids}))
    qparts = {"mux": nodes["mux"].key}
    add(Node("qa.av", "qa.av", "cpu", qparts, node_key("qa.av", qparts, {}), deps=("mux",)))


def _master(inputs, policy, pins, cuts, shots, nodes, add) -> None:
    scale = policy["master"]["scale"]
    verify_ids = []
    for shot in shots:
        up = _upscale_parts(inputs, shot)
        up_id = f"upscale.chunks[{shot['id']}]"
        add(Node(up_id, "upscale.chunks", "gpu", up, node_key("upscale.chunks", up, {}),
                 deps=(f"motion.h3[{shot['id']}]",), meta={"shot": shot["id"], "native_frames": shot["native_frames"]}))
        ver_id = f"master.verify[{shot['id']}]"
        add(Node(ver_id, "master.verify", "cpu", up, node_key("master.verify", up, {}), deps=(up_id,),
                 meta={"shot": shot["id"]}))
        verify_ids.append(ver_id)
    ids = []
    for seg in cuts:
        binder = FileBinder()
        parts = {**slices.video_parts(inputs.config, seg, policy, binder), "global.scale": scale}
        node_id = f"composite.master[{seg['id']}]"
        deps = tuple(f"master.verify[{s}]" for s in _segment_shots(inputs.config, parts))
        add(Node(node_id, "composite.master", "cpu", parts, node_key("composite.master", parts, pins), deps=deps,
                 meta={**_segment_meta(inputs.config, seg), "unresolved": binder.unresolved}))
        ids.append(node_id)
    mux_parts = {"segments": [[i, nodes[i].key] for i in ids], "audio.mix": nodes["audio.mix"].key, **_core(inputs)}
    add(Node("mux.master", "mux.master", "cpu", mux_parts, node_key("mux.master", mux_parts, {}),
             deps=(*ids, "audio.mix"), meta={"segments": ids}))
    dparts = {"mux.master": nodes["mux.master"].key}
    add(Node("film.downscale.2k", "film.downscale.2k", "cpu", dparts, node_key("film.downscale.2k", dparts, {}),
             deps=("mux.master",)))
