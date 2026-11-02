"""Regression for ComfyUI installations whose loader combos list root files only."""
import copy
import json
from pathlib import Path

import pytest

from engine.comfy.gui_inputs import LOADERS, flat_input_name, stage_graph_inputs
from engine.comfy.staging import input_target, stage_input
from engine.core.errors import Refused, exit_code_for
from engine.core.io import sha256_file
from engine.gui_export.export import export_gui
from test_gui_export import JJ, NTC, POLICY, _gui, _refresh_graph, case, object_info  # noqa: F401


@pytest.mark.parametrize("domain", [NTC, JJ])
@pytest.mark.parametrize("kind", ["video", "image"])
@pytest.mark.parametrize("separator", ["/", "\\"])
def test_export_all_loader_types_are_flat_hash_verified_and_domain_scoped(case, domain, kind, separator):
    case.ctx.domain_id = domain
    graph = case.prepared["graph"]
    for binding in case.prepared["bindings"]:
        name = separator.join(["nested", "shot", Path(binding["path"]).name])
        binding["input_name"] = name
        nid, key = binding["ports"][0]
        graph[nid]["inputs"][key] = name
    graph["5"] = {"class_type": "LoadImageMask", "inputs": {"image": graph["1"]["inputs"]["image"], "channel": "red"}}
    case.prepared["bindings"][0]["ports"].append(("5", "image"))
    _refresh_graph(case)
    original = copy.deepcopy(graph)

    def info(name):
        if name == "LoadImageMask":
            return {"input": {"required": {"image": [["placeholder.png"], {}], "channel": [["red", "alpha"], {}]}},
                    "output": ["MASK"], "output_name": ["MASK"]}
        return object_info(name)

    result = export_gui(case.ctx, case.prepared, kind=kind, out=case.out, object_info=info, policy=POLICY)
    rows = {row["node_id"]: row for row in result["inputs"]}
    for node in _gui(result)["nodes"]:
        if node["type"] not in LOADERS:
            continue
        name = node["widgets_values_named"][LOADERS[node["type"]]]
        assert name == node["widgets_values"][0]
        assert "/" not in name and "\\" not in name
        assert name.startswith(domain + "__S02_A__")
        target = case.comfy / "input" / name
        assert target.parent == case.comfy / "input"
        assert sha256_file(target) == rows[str(node["id"])]["sha256"]
    assert graph == original


def test_flat_name_deterministic_across_slash_styles_and_domains():
    digest = "a" * 64
    assert flat_input_name(NTC, "S02_A", digest, "a/b/image.png") == f"{NTC}__S02_A__aaaaaaaaaaaa__image.png"
    assert flat_input_name(NTC, "S02_A", digest, "a\\b\\image.png") == flat_input_name(NTC, "S02_A", digest, "image.png")
    assert flat_input_name(JJ, "S02_A", digest, "image.png") != flat_input_name(NTC, "S02_A", digest, "image.png")


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_legacy_graph_stages_each_loader_and_preserves_source(tmp_path, separator):
    root = tmp_path / "input"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    graph = {}
    for i, (loader, key) in enumerate(LOADERS.items(), 1):
        source = nested / ("audio.wav" if key == "audio" else f"image{i}.png")
        source.write_bytes(loader.encode())
        graph[str(i)] = {"class_type": loader, "inputs": {key: separator.join(["a", "b", source.name])}}
    original = copy.deepcopy(graph)
    staged = stage_graph_inputs(graph, root, domain=NTC, shot="S02_A")
    for node in staged.values():
        name = node["inputs"][LOADERS[node["class_type"]]]
        assert "/" not in name and "\\" not in name
        assert (root / name).read_bytes() == node["class_type"].encode()
    assert graph == original
    assert stage_graph_inputs(graph, root, domain=NTC, shot="S02_A") == staged


def test_staging_collision_refuses_nonzero_with_clear_message_and_no_overwrite(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"approved")
    digest = sha256_file(source)
    root = tmp_path / "input"
    name = flat_input_name(NTC, "S02_A", digest, source.name)
    staged = stage_input(source, root, name, digest)
    assert sha256_file(staged) == digest
    staged.write_bytes(b"different")
    with pytest.raises(Refused, match="existing ComfyUI input hash mismatch") as caught:
        stage_input(source, root, name, digest)
    assert exit_code_for(caught.value) == 1
    assert staged.read_bytes() == b"different"


def test_staging_checks_source_hash_and_temporary_copy(tmp_path, monkeypatch):
    from engine.comfy import staging

    source = tmp_path / "source.png"
    source.write_bytes(b"approved")
    digest = sha256_file(source)
    root = tmp_path / "input"
    with pytest.raises(Refused, match="source for staging hash mismatch"):
        stage_input(source, root, "flat.png", "b" * 64)
    monkeypatch.setattr(staging.shutil, "copy2", lambda src, dst: Path(dst).write_bytes(b"corrupted copy"))
    with pytest.raises(Refused, match="temporary ComfyUI input hash mismatch"):
        stage_input(source, root, "flat.png", digest)
    assert not (root / "flat.png").exists()


def test_legacy_graph_rejects_drift_from_preparation_hash_before_staging(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"approved")
    digest = sha256_file(source)
    source.write_bytes(b"changed after preparation")
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": source.name}}}
    with pytest.raises(Refused, match="GUI prepared input hash mismatch"):
        stage_graph_inputs(graph, tmp_path, domain=NTC, shot="S02_A", expected_hashes={source.name: digest})
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("name", ["a/b.png", "a\\b.png", "../x.png", "C:stream.png"])
def test_staging_rejects_nonflat_names_on_every_platform(tmp_path, name):
    with pytest.raises(Refused, match="unsafe ComfyUI input name"):
        input_target(tmp_path, name)


@pytest.mark.parametrize("name", ["../outside.png", "..\\outside.png", "/outside.png", "C:\\outside.png", "missing.png"])
def test_legacy_export_refuses_missing_or_escaped_input(tmp_path, name):
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": name}}}
    with pytest.raises(Refused, match="GUI_(PATH|INPUT)"):
        stage_graph_inputs(graph, tmp_path, domain=NTC, shot="S02_A")


def test_image_gui_writer_flattens_before_serializing(tmp_path):
    from engine.images.gui import write_guis

    root = tmp_path / "input"
    source = root / "nested" / "image.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"anchor")
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "nested/image.png"}}}
    folder = tmp_path / "export"
    result = write_guis(folder, graph, object_info, root, title="test", graph_sha256="a" * 64,
                        produced=None, domain=NTC, shot="S02_A")
    assert "error" not in result
    gui = json.loads((folder / "graph.gui.json").read_text("utf-8"))
    name = gui["nodes"][0]["widgets_values"][0]
    assert name == flat_input_name(NTC, "S02_A", sha256_file(source), source.name)
    assert sha256_file(root / name) == sha256_file(source)


def test_video_export_cli_collision_returns_one_and_explains_refusal(case, monkeypatch):
    import contextlib
    import io
    import runpy
    from test_gui_export import SKILL

    name = flat_input_name(NTC, "S02_A", sha256_file(case.wav), case.wav.name)
    target = case.comfy / "input" / name
    target.write_bytes(b"collision")
    main = runpy.run_path(str(SKILL / "bin/jjv.py"))["main"]
    # Exercise the real parser/error-to-exit boundary, injecting only context
    # discovery to avoid an HTTP/config dependency in this filesystem test.
    monkeypatch.setitem(main.__globals__, "_dispatch", lambda args: export_gui(
        case.ctx, case.prepared, kind="video", out=case.out, object_info=object_info, policy=POLICY))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(["video", "export-gui", "--episode", str(case.ctx.root), "--out", str(case.out),
                     "--prepared", str(case.ctx.root), "--shot", "S02_A"])
    assert code == 1
    assert "GUI_COLLISION" in json.loads(output.getvalue())["error"]
    assert target.read_bytes() == b"collision"
    assert not list(case.workflows.rglob("*.json"))


def test_audio_gui_writer_flattens_before_serializing(tmp_path):
    from engine.audio.guiwrite import write_guis

    root = tmp_path / "input"
    source = root / "nested" / "sound.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"sound")
    graph = {"1": {"class_type": "LoadAudio", "inputs": {"audio": "nested/sound.wav"}}}
    out = tmp_path / "export"
    out.mkdir()
    (out / "graph.api.json").write_text(json.dumps(graph), "utf-8")
    plan = {"domain": JJ, "jobs": [{"job_id": "music-c01-t01", "graph_file": "graph.api.json", "graph_sha256": "a" * 64}]}
    result = write_guis(out, plan, {"music-c01-t01": {"path": str(source), "sha256": sha256_file(source), "prompt_id": "test"}},
                        object_info, root, label="test")
    assert "error" not in result
    row = result["music-c01-t01"]
    for key in ("gui", "review_gui"):
        gui = json.loads((out / row[key]).read_text("utf-8"))
        for node in gui["nodes"]:
            name = node["widgets_values"][0]
            assert "/" not in name and "\\" not in name
            assert name.startswith(JJ + "__music-c01-t01__")
            assert sha256_file(root / name) == sha256_file(source)


def test_h3_gui_writer_flattens_before_serializing(tmp_path):
    from engine.h3.adopt import _gui

    source = tmp_path / "nested" / "image.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"image")
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "nested/image.png"}}}

    class Client:
        def get(self, path):
            name = path.rsplit("/", 1)[-1]
            return {name: object_info(name)}

    gui, error = _gui(Client(), graph, "S02_A", "a" * 64, input_dir=tmp_path, domain=NTC)
    assert error is None
    name = gui["nodes"][0]["widgets_values"][0]
    assert name == flat_input_name(NTC, "S02_A", sha256_file(source), source.name)
    assert sha256_file(tmp_path / name) == sha256_file(source)
