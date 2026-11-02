"""Behavior tests for parsers, reciprocal domain confinement, and render selection."""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

SPEC = importlib.util.spec_from_file_location("panel_core", Path(__file__).parents[1] / "core.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def write_csv(path, rows, guide=False):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["scene", "shot", "duration", "prompt", "refs"] + (["guide"] if guide else []))
        writer.writerows(rows)
    return path


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "JennieJoyKids-Story"
    nt = root / "Newtecons-test"
    jj = root / "04-milk-and-mom"
    for episode, domain in [(nt, core.DOMAINS[0]), (jj, core.DOMAINS[1])]:
        (episode / "assets").mkdir(parents=True)
        (episode / "engine").mkdir()
        (episode / "engine/episode.json").write_text(json.dumps({"domain": domain}), encoding="utf8")
        (episode / "script.txt").write_text("Script", encoding="utf8")
    input_dir, output_dir = tmp_path / "input", tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    return root, nt, jj, input_dir, output_dir


def settings(project, rows=None):
    root, nt, _, input_dir, output_dir = project
    shotlist = write_csv(nt / "shots.csv", rows or [
        ["S02", "S02_A", "4.4", "An adult engineer at work", ""],
        ["S03", "S03_A", "5", "An adult manager speaking", ""],
    ])
    return dict(root=root, input_dir=input_dir, output_dir=output_dir,
                domain=core.DOMAINS[0], script_path=str(nt / "script.txt"),
                shotlist_path=str(shotlist), asset_folder=str(nt / "assets"),
                run_mode="One shot", scene="S02", shot="S02_A", aspect="16:9",
                generation_size="704p", output_resolution="1440p", style=core.STYLES[0],
                no_image_mode="T2V", min_duration=4.0)


def test_csv_bom_unicode_and_refs(tmp_path):
    path = write_csv(tmp_path / "shots.csv", [["S02", "S02_A", 4.4, "Kỹ sư, công trường", '["face 1.png", "áo.png"]']])
    row = core.parse_shotlist(path)[0]
    assert row["prompt"] == "Kỹ sư, công trường"
    assert row["refs"] == ["face 1.png", "áo.png"]
    assert row["duration"] == 4.4


def test_xlsx_active_sheet_and_semicolon_refs(tmp_path):
    from openpyxl import Workbook
    book = Workbook()
    book.active.append(["scene", "shot", "duration", "prompt", "refs"])
    book.active.append(["S02", "S02_A", 5, "Engineer", "face.png; shirt.png"])
    path = tmp_path / "shots.xlsx"
    book.save(path)
    book.close()
    assert core.parse_shotlist(path)[0]["refs"] == ["face.png", "shirt.png"]


@pytest.mark.parametrize("duration", ["nan", "inf", "-1", "0", "151", "bad"])
def test_bad_durations_refused(tmp_path, duration):
    path = write_csv(tmp_path / "shots.csv", [["S02", "S02_A", duration, "Engineer", ""]])
    with pytest.raises(ValueError, match="duration"):
        core.parse_shotlist(path)


def test_duplicate_ids_across_scenes_refused(tmp_path):
    path = write_csv(tmp_path / "shots.csv", [["S02", "A", 5, "x", ""], ["S03", "A", 5, "y", ""]])
    with pytest.raises(ValueError, match="duplicate"):
        core.parse_shotlist(path)


@pytest.mark.parametrize("headers", ["scene,shot,duration,prompt", "scene,shot,duration,prompt,refs,refs"])
def test_invalid_headers_refused(tmp_path, headers):
    path = tmp_path / "shots.csv"
    path.write_text(headers + "\n", encoding="utf8")
    with pytest.raises(ValueError, match="headers"):
        core.parse_shotlist(path)


def test_formula_is_not_evaluated(tmp_path):
    path = write_csv(tmp_path / "shots.csv", [["S02", "S02_A", 4, "=HYPERLINK(\"file://secret\")", ""]])
    with pytest.raises(ValueError, match="formulas"):
        core.parse_shotlist(path)


def test_empty_prompt_and_unsafe_shot_refused(tmp_path):
    for shot, prompt in [("../escape", "Engineer"), ("S02_A", "")]:
        path = write_csv(tmp_path / "shots.csv", [["S02", shot, 4, prompt, ""]])
        with pytest.raises(ValueError):
            core.parse_shotlist(path)


def test_shared_jenniejoy_parent_does_not_misclassify_newtecons(project):
    root, nt, _, _, _ = project
    assert core.episode_domain(nt / "script.txt", root) == "newtecons_live_action"
    core.guard_domain(core.DOMAINS[0], [nt / "assets"], root, core.STYLES[0])


@pytest.mark.parametrize("domain,index", [(core.DOMAINS[0], 2), (core.DOMAINS[1], 1)])
def test_reciprocal_cross_domain_refused(project, domain, index):
    root = project[0]
    with pytest.raises(ValueError, match="Cross-domain"):
        core.guard_domain(domain, [project[index] / "script.txt"], root)


@pytest.mark.parametrize("domain,style", [(core.DOMAINS[0], core.STYLES[1]), (core.DOMAINS[1], core.STYLES[0])])
def test_cross_domain_style_refused(project, domain, style):
    with pytest.raises(ValueError, match="requires style"):
        core.guard_domain(domain, [], project[0], style)


def test_missing_and_conflicting_domain_markers_fail_closed(project):
    root, nt, _, _, _ = project
    (nt / "project-panel.json").write_text('{"domain":"jenniejoy_cartoon_3d"}', encoding="utf8")
    with pytest.raises(ValueError, match="consistent"):
        core.episode_domain(nt / "assets", root)
    unknown = root / "unknown"
    unknown.mkdir()
    with pytest.raises(ValueError, match="consistent"):
        core.episode_domain(unknown, root)


def test_browser_rejects_escape_and_filters_files(project, tmp_path):
    root, nt, _, _, _ = project
    (nt / "private.env").write_text("not a selectable script", encoding="utf8")
    entries = core.browse(nt, root, "script")["entries"]
    assert "script.txt" in [x["name"] for x in entries]
    assert "private.env" not in [x["name"] for x in entries]
    for outside in [str(tmp_path), "../../", "https://example.com/secret"]:
        with pytest.raises(ValueError):
            core.browse(outside, root, "script")
    assert core.browse(root, root, "folder")["parent"] is None


def test_symlink_escape_is_not_listed(project, tmp_path):
    root, nt, _, _, _ = project
    external = tmp_path / "outside"
    external.mkdir()
    alias = nt / "escape"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Windows requires developer mode or symlink privilege")
    assert "escape" not in [x["name"] for x in core.browse(nt, root, "folder")["entries"]]
    with pytest.raises(ValueError, match="outside"):
        core.confined(alias, root)


def test_selected_shot_dimensions_and_frame_alignment(project):
    result = core.prepare(**settings(project))
    assert (result["width"], result["height"]) == (1280, 704)
    assert (result["output_width"], result["output_height"]) == (2560, 1440)
    assert result["frames"] % 17 == 5
    assert result["actual_duration"] >= result["duration"] >= 4.4
    assert result["fps"] == 24 and not result["approved"]
    assert result["refs"] == [] and result["image_mode"] == "T2V"


def test_native_768_and_portrait_output():
    assert core.dimensions("16:9", "Native 768p", "1080p") == (1344, 768, 1920, 1080)
    assert core.dimensions("9:16", "704p", "1440p") == (704, 1280, 1440, 2560)


def test_i2v_without_image_refused(project):
    values = settings(project)
    values["no_image_mode"] = "I2V"
    with pytest.raises(ValueError, match="requires an image"):
        core.prepare(**values)


def test_unknown_selection_refused(project):
    values = settings(project)
    values["shot"] = "NO_SUCH_SHOT"
    with pytest.raises(ValueError, match="absent"):
        core.prepare(**values)


def test_flat_image_staging_and_hash_collision(project):
    from PIL import Image
    root, nt, _, input_dir, _ = project
    source = nt / "assets" / "face.png"
    Image.new("RGB", (16, 16), "red").save(source)
    values = settings(project, [["S02", "S02_A", 4, "Engineer", "face.png"]])
    result = core.prepare(**values)
    item = result["refs"][0]
    assert item["filename"] == f"newtecons_live_action__S02_A__{core.sha256(source)[:12]}__face.png"
    target = input_dir / item["filename"]
    assert target.parent == input_dir and core.sha256(target) == core.sha256(source)
    assert core.prepare(**values)["refs"] == result["refs"]
    target.write_bytes(b"preserve this collision")
    with pytest.raises(ValueError, match="collision"):
        core.prepare(**values)
    assert target.read_bytes() == b"preserve this collision"


def test_cross_domain_reference_even_under_same_shared_root(project):
    _, _, jj, _, _ = project
    source = jj / "assets/cartoon.png"
    source.write_bytes(b"not read before domain validation")
    values = settings(project, [["S02", "S02_A", 4, "Engineer", str(source)]])
    with pytest.raises(ValueError, match="Cross-domain"):
        core.prepare(**values)


def test_auto_skips_only_hash_verified_render_and_revisits_changed_input(project):
    values = settings(project)
    values.update(run_mode="Auto: missing shots", scene="ALL")
    first = core.prepare(**values)
    assert first["shot"] == "S02_A"
    directory = values["output_dir"] / "newtecons-panel"
    directory.mkdir()
    output = directory / "test.mp4"
    output.write_bytes(b"test payload, no GPU")
    marker = directory / f"{first['render_key']}.json"
    marker.write_text(json.dumps({"render_key": first["render_key"], "output": str(output),
                                  "sha256": core.sha256(output)}), encoding="utf8")
    assert core.prepare(**values)["shot"] == "S03_A"
    output.unlink()
    assert core.prepare(**values)["shot"] == "S02_A"
    output.write_bytes(b"changed render")
    assert core.prepare(**values)["shot"] == "S02_A"
    output.write_bytes(b"test payload, no GPU")
    Path(values["script_path"]).write_text("Revised script", encoding="utf8")
    assert core.prepare(**values)["shot"] == "S02_A"


def test_reference_escape_cannot_stage(project, tmp_path):
    source = tmp_path / "secret.png"
    source.write_bytes(b"must not be read")
    values = settings(project, [["S02", "S02_A", 4, "Engineer", str(source)]])
    with pytest.raises(ValueError, match="outside"):
        core.prepare(**values)
    assert not list(values["input_dir"].iterdir())


def test_context_hash_survives_comfy_float_validation():
    before = {"100": {"class_type": "NewteconsProjectPanel", "inputs": {"min_duration": 4, "shot": "S02_A"}},
              "20": {"class_type": "LoraLoaderModelOnly", "inputs": {"strength_model": 1}}}
    after = json.loads(json.dumps(before))
    after["100"]["inputs"]["min_duration"] = 4.0
    after["20"]["inputs"]["strength_model"] = 1.0
    assert core.context_hash(before) == core.context_hash(after)
    after["20"]["inputs"]["strength_model"] = 0.8
    assert core.context_hash(before) != core.context_hash(after)


def test_browser_python_context_hash_parity():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    # Execute the actual frontend hash function with a fake app; never import or queue ComfyUI.
    source = (Path(__file__).parents[1] / "web/project_panel.js").read_text(encoding="utf8")
    function = source[source.index("async function hashPrompt("):source.index("\nfunction element(")]
    script = "const crypto = require('node:crypto').webcrypto;\n" + function + "\n" + r'''
let text = ''; process.stdin.on('data', (chunk) => text += chunk);
process.stdin.on('end', async () => process.stdout.write(await hashPrompt(JSON.parse(text))));
'''
    graph = {"100": {"class_type": "NewteconsProjectPanel", "_meta": {"title": "Kỹ sư"},
                     "inputs": {"min_duration": 4, "scene": "ALL", "shot": "S02_A", "run_mode": "One shot"}},
             "1": {"class_type": "NumericEdgeCases", "inputs": {"integer": 12.0, "tiny": 1e-7,
                     "negative_zero": -0.0, "large": 1e21, "flag": True, "null": None, "text": "Áo lưới"}}}
    result = subprocess.run(["node", "-e", script], input=json.dumps(graph), text=True,
                            capture_output=True, check=True, timeout=15)
    assert result.stdout == core.context_hash(graph)


def test_optional_guide_is_staged_flat_and_guarded(project):
    from PIL import Image
    values = settings(project)
    guide = Path(values["asset_folder"]) / "guide.png"
    Image.new("RGB", (8, 8), "blue").save(guide)
    write_csv(Path(values["shotlist_path"]), [["S02", "S02_A", 4, "Engineer", "", "guide.png"]], guide=True)
    result = core.prepare(**values)
    assert result["refs"] == []
    assert result["image_mode"] == "I2V"
    staged = result["guide"][0]
    assert staged["filename"].startswith("newtecons_live_action__S02_A__")
    assert core.sha256(values["input_dir"] / staged["filename"]) == core.sha256(guide)


def test_terminal_receipt_only_after_successful_save(project, monkeypatch):
    package = types.ModuleType("panel_test_pkg")
    package.__path__ = [str(Path(__file__).parents[1])]
    monkeypatch.setitem(sys.modules, "panel_test_pkg", package)
    monkeypatch.setitem(sys.modules, "panel_test_pkg.core", core)
    spec = importlib.util.spec_from_file_location("panel_test_pkg.nodes", Path(__file__).parents[1] / "nodes.py")
    nodes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nodes)
    values = settings(project)
    receipt = core.prepare(**values)
    monkeypatch.setitem(sys.modules, "folder_paths", types.SimpleNamespace(get_output_directory=lambda: str(values["output_dir"])))
    monkeypatch.setitem(sys.modules, "comfy_api", types.ModuleType("comfy_api"))
    monkeypatch.setitem(sys.modules, "comfy_api.latest", types.SimpleNamespace(
        Types=types.SimpleNamespace(VideoContainer=lambda x: x, VideoCodec=lambda x: x)))
    class Video:
        def __init__(self, fail):
            self.fail = fail
        def save_to(self, path, **kwargs):
            if self.fail:
                raise RuntimeError("simulated encoder failure")
            Path(path).write_bytes(b"simulated successful MP4 write")
        def get_dimensions(self):
            return 1280, 704
    saver = nodes.NewteconsPanelSaveVideo()
    marker = values["output_dir"] / "newtecons-panel" / f"{receipt['render_key']}.json"
    with pytest.raises(RuntimeError, match="encoder failure"):
        saver.save(Video(True), json.dumps(receipt))
    assert not marker.exists()
    saved = saver.save(Video(False), json.dumps(receipt))
    assert saved["ui"]["animated"] == (True,)
    assert core.rendered(values["output_dir"], receipt["render_key"])
    result = json.loads(saved["result"][0])
    assert result["saved_dimensions"] == [1280, 704] and not result["approved"]
    historical = Path(result["receipt_path"])
    original_receipt = historical.read_bytes()
    saver.save(Video(False), json.dumps(receipt))
    assert historical.read_bytes() == original_receipt
    assert len(list(marker.parent.glob("*.mp4.receipt.json"))) == 2
