"""``jjv audio music pick|adopt`` and the brand-voice flag through the exact CLI-PATCH lines on scratch copies (no GPU)."""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest
from audio_fixtures import audio_world, hand_built_review, write_tone
from test_audio_library_support import SCHEMA, bed_row, make_library, registry_bytes, standard_rows
from test_audio_mix_run import episode, make_args, run as mix_run  # noqa: F401  (episode is a fixture)

from engine.audio import library, library_brand, musicpick, musicpick_cli
from engine.core.errors import Refused
from engine.core.io import sha256_file

AUDIO = Path(__file__).resolve().parents[1] / "engine" / "audio"
PATCH_MD = (AUDIO / "CLI-PATCH-music-pick.md").read_text(encoding="utf-8")
CLI_EDITS = [
    ("from .recipe import optional_block, resolve_recipe\n", "from . import musicpick_cli  # noqa: E402\n", "after"),
    ('    sfx_p = families.add_parser("sfx", help="cues | submit | finalize")\n', "    musicpick_cli.register(msub)\n", "before"),
    ("    kind, action = args.verb, args.action\n",
     "    handled = musicpick_cli.run_music_action(args)\n    if handled is not None:\n        return handled\n", "before"),
]
MIX_EDITS = [
    ("from .recipe import optional_block, resolve_recipe\n", "from . import library_brand, musicpick_cli  # noqa: E402\n", "after"),
    ('    parser.add_argument("--brand-voice", default=None,',
     '    parser.add_argument("--library", default=None, help="library root (default: <episodes folder>/_library); brand voice registry pick")\n',
     "before"),
    ("    brand = None\n    if getattr(args, \"brand_voice\", None):\n",
     "    choice = library_brand.resolve(config, cli_wav=getattr(args, \"brand_voice\", None),\n"
     "                                   cli_sha256=getattr(args, \"brand_voice_sha256\", None),\n"
     "                                   library=musicpick_cli.library_dir(config, getattr(args, \"library\", None)))\n"
     "    args.brand_voice, args.brand_voice_sha256 = choice.path, choice.sha256\n", "before"),
    ('"brand": brand, "sections": rows,', '"brand": brand, "brand_choice": choice, "sections": rows,', "replace"),
    ('            "brand_voice": None if plan["brand"] is None else {',
     '            "brand_voice_mode": {"mode": plan["brand_choice"].mode, "source": plan["brand_choice"].source},\n', "before"),
]


def patched_module(tmp_path_factory, name: str, edits: list) -> object:
    text = (AUDIO / f"{name}.py").read_text(encoding="utf-8")
    for anchor, new, how in edits:
        if new in text:  # root applied the CLI-PATCH to the real module: nothing to patch
            continue
        assert text.count(anchor) == 1, (name, anchor)
        assert new.strip().splitlines()[0].strip() in PATCH_MD, new  # the patch note shows the same line
        text = (text.replace(anchor, anchor + new) if how == "after" else
                text.replace(anchor, new + anchor) if how == "before" else text.replace(anchor, new))
    path = tmp_path_factory.mktemp("patched") / f"_{name}_patched.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"engine.audio._{name}_patched", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def patched(tmp_path_factory):
    return patched_module(tmp_path_factory, "cli", CLI_EDITS), patched_module(tmp_path_factory, "mixcli", MIX_EDITS)


def parse(patched_cli, *argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    patched_cli.register_cli(parser.add_subparsers(dest="stage"))
    return parser.parse_args(["audio", *argv])


@pytest.fixture
def world(tmp_path):
    config, _ = audio_world(tmp_path)
    root = Path(config.episode_root)
    review = root / "review-config.json"
    review.write_text(json.dumps(hand_built_review(root)), encoding="utf-8")
    pack = root / "pack.json"
    pack.write_text(json.dumps({"shots": [{"shot_id": "S01_A", "visual_description": "Alice sets wooden tokens beside the farm cow."}]}),
                    encoding="utf-8")
    lib = make_library(tmp_path, standard_rows(tmp_path / "lib"))
    base = ["music", "pick", "--episode", str(root / "engine" / "episode.json"), "--review-config", str(review),
            "--shot-pack", str(pack), "--library", str(lib), "--bpm", "100", "--key", "C major", "--instruments",
            "ukulele, glockenspiel, soft piano, light hand percussion"]
    return config, lib, base, tmp_path


def call(patched, capsys, argv: list[str]) -> tuple[int, dict]:
    code = patched[0].run_audio(parse(patched[0], *argv))
    return code, json.loads(capsys.readouterr().out)


def test_the_patched_cli_registers_both_verbs_and_the_patch_note_matches(patched, capsys) -> None:
    args = parse(patched[0], "music", "adopt", "--episode", "E", "--out", "O", "--execute", "--take", "t")
    assert args.action == "adopt" and args.execute and args.take == "t" and args.verb == "music"
    assert parse(patched[0], "music", "pick", "--episode", "E", "--out", "O").dry_run is False
    assert parse(patched[0], "music", "plan", "--episode", "E", "--out", "O").action == "plan"  # the old verbs are untouched


def test_dry_run_decides_from_the_script_and_writes_nothing(patched, world, capsys) -> None:
    _, lib, base, tmp = world
    before = registry_bytes(lib)
    code, out = call(patched, capsys, [*base, "--out", str(tmp / "pick1"), "--dry-run"])
    assert code == 0 and out["dry_run"] and out["written"] is None and out["decision"] == "library" and out["bed_id"] == "B-PASTORAL"
    assert out["registry_would_add_used_in"] is True and out["bed_target_s"] == 23.0 and out["ranking"][0]["id"] == "B-PASTORAL"
    assert registry_bytes(lib) == before and not (tmp / "pick1").exists()
    assert not list(library.beds_dir(lib).glob("*.bak-*"))


def test_a_pick_appends_used_in_once_with_a_backup_and_writes_a_receipt_the_mix_reads(patched, world, capsys) -> None:
    config, lib, base, tmp = world
    before = registry_bytes(lib)
    code, out = call(patched, capsys, [*base, "--out", str(tmp / "pick1")])
    receipt = json.loads((tmp / "pick1" / "music-pick.json").read_text(encoding="utf-8"))
    assert code == 0 and out["bed_id"] == "B-PASTORAL" and out["used_in_added"] is True
    assert receipt["status"] == "LIBRARY_BED_PICKED" and receipt["reason"] == out["reason"] and "B-PASTORAL" in receipt["reason"]
    assert receipt["brief"]["bpm"] == 100.0 and receipt["bed_target_s"] == 23.0 and receipt["registry_write"]["revision"] == 1
    stem = receipt["stem"]
    assert Path(stem["path"]).is_absolute() and stem["sha256"] == sha256_file(Path(stem["path"])) and stem["vocal_gate"]["status"] == "PASS"
    document = json.loads(registry_bytes(lib))
    row = next(b for b in document["beds"] if b["id"] == "B-PASTORAL")
    assert row["used_in"][0]["film"] == config.episode["film_id"] and row["used_in"][0]["receipt"].endswith("music-pick.json")
    assert document["revision"] == 1 and Path(receipt["registry_write"]["backup"]).read_bytes() == before
    # the SAME episode again (new folder): stable bed, no duplicate used_in, no second registry write
    code, again = call(patched, capsys, [*base, "--out", str(tmp / "pick2")])
    assert again["bed_id"] == "B-PASTORAL" and again["used_in_added"] is False and again["registry_write"] is None
    assert json.loads(registry_bytes(lib))["revision"] == 1 and len(list(library.beds_dir(lib).glob("*.bak-*"))) == 1
    with pytest.raises(Refused, match="write-once"):
        call(patched, capsys, [*base, "--out", str(tmp / "pick2")])


def test_the_mix_accepts_the_library_receipt_as_a_passing_music_bed(episode, tmp_path) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    lib = make_library(tmp_path, [bed_row("B-X", "ukulele", 30.0, 262.0, tmp_path / "lib")])
    document, _ = library.load_registry(lib, SCHEMA)
    receipt = tmp_path / "music-pick.json"
    receipt.write_text(json.dumps({"stem": musicpick.library_stem(lib, document["beds"][0])}), encoding="utf-8")
    summary, code = mix_run(config, make_args(tmp_path, review, None, music_wav=None, music_receipt=str(receipt), dry_run=True))
    assert code == 0 and summary["music"]["vocal_gate"] == "PASS" and summary["music"]["source"] == "receipt"


def nothing_fits(tmp_path):
    return make_library(tmp_path, [bed_row("B-GUITAR", "nylon guitar and marimba, 108 BPM F major", 30.0, 330.0, tmp_path / "lib")])


def test_when_nothing_fits_a_generation_plan_is_written_and_the_registry_is_untouched(patched, world, capsys, monkeypatch) -> None:
    _, _, base, tmp = world
    lib = nothing_fits(tmp)
    argv = [*base[:base.index("--library")], "--library", str(lib), *base[base.index("--bpm"):]]
    monkeypatch.setattr(musicpick_cli, "_generator_models_present", lambda config, recipe: None)
    before = registry_bytes(lib)
    code, dry = call(patched, capsys, [*argv, "--out", str(tmp / "gen"), "--dry-run"])
    assert code == 0 and dry["decision"] == "generate" and dry["generator"] == "acestep" and dry["written"] is None
    assert dry["reason"].startswith("no bed fits: 1 eligible") and not (tmp / "gen").exists()
    assert dry["prompt"]["style"].startswith("instrumental, no vocals,") and dry["jobs"][0]["seconds"] == 23.0
    code, out = call(patched, capsys, [*argv, "--out", str(tmp / "gen")])
    pick = json.loads((tmp / "gen" / "music-pick.json").read_text(encoding="utf-8"))
    plan = json.loads((tmp / "gen" / "music-plan.json").read_text(encoding="utf-8"))
    graph = json.loads((tmp / "gen" / plan["jobs"][0]["graph_file"]).read_text(encoding="utf-8"))
    assert code == 0 and pick["status"] == "GENERATION_PLANNED" and pick["generator"] == "acestep" and plan["recipe"]["id"].endswith("#acestep")
    assert graph["4"]["inputs"]["bpm"] == 100 and graph["4"]["inputs"]["keyscale"] == "C major"
    assert out["next"].startswith("jjv audio music adopt --episode") and registry_bytes(lib) == before


def test_the_generator_falls_back_to_yue2_when_the_acestep_models_are_missing_and_refuses_when_both_are(patched, world, capsys,
                                                                                                         monkeypatch) -> None:
    _, _, base, tmp = world
    lib = nothing_fits(tmp)
    argv = [*base[:base.index("--library")], "--library", str(lib), *base[base.index("--bpm"):], "--out", str(tmp / "gen"), "--dry-run"]
    monkeypatch.setattr(musicpick_cli, "_generator_models_present",
                        lambda config, recipe: "model file missing: acestep" if "acestep" in recipe.recipe_id else None)
    code, out = call(patched, capsys, argv)
    assert out["generator"] == "yue2" and out["skipped"][0]["generator"] == "acestep"
    assert out["prompt"]["style"].startswith("English, long-form extended instrumental") and out["jobs"][0]["seed"] == 20261102
    monkeypatch.setattr(musicpick_cli, "_generator_models_present", lambda config, recipe: "missing")
    with pytest.raises(Refused, match="no generator can run"):
        call(patched, capsys, argv)
    with pytest.raises(Refused, match="exclude each other"):
        call(patched, capsys, [*argv, "--execute"])


def test_adopt_before_the_jobs_ran_reports_the_states_and_never_posts(patched, world, capsys, monkeypatch) -> None:
    _, _, base, tmp = world
    lib = nothing_fits(tmp)
    argv = [*base[:base.index("--library")], "--library", str(lib), *base[base.index("--bpm"):], "--out", str(tmp / "gen")]
    monkeypatch.setattr(musicpick_cli, "_generator_models_present", lambda config, recipe: None)
    call(patched, capsys, argv)
    monkeypatch.setattr(musicpick_cli, "_ffmpeg", lambda flag: "ffmpeg")
    adopt = ["music", "adopt", "--episode", argv[3], "--out", str(tmp / "gen"), "--library", str(lib),
             "--vocal-gate-command", json.dumps(["separate", "{input}", "{out_dir}"])]
    code, out = call(patched, capsys, adopt)
    assert code == 0 and out["adopted"] is False and out["job_states"] == {"music-c01-t01": "READY"}
    assert "--execute" in out["message"]


# ---- brand voice -----------------------------------------------------------------------------------------
def brand_library(tmp_path: Path) -> Path:
    folder = tmp_path / "blib" / library_brand.BRAND_DIR
    folder.mkdir(parents=True)
    sha = write_tone(folder / "VOICE-48k.wav", 2.0, 0.2, 500.0)
    (folder / "REGISTRY.json").write_text(json.dumps({"pick": "VOICE-A", "file": "VOICE-48k.wav", "sha256": sha}), encoding="utf-8")
    return tmp_path / "blib"


def with_mode(config, mode):
    audio = {} if mode is None else {"brand_voice": mode}
    return dataclasses.replace(config, episode={**config.episode, "audio": audio})


def test_brand_voice_modes(tmp_path) -> None:
    config, _ = audio_world(tmp_path)
    lib = brand_library(tmp_path)
    default = library_brand.resolve(config, cli_wav=None, cli_sha256=None, library=lib)
    assert default.mode == "intro" and default.path is None and "intro" in default.source
    assert library_brand.resolve(with_mode(config, "none"), cli_wav=None, cli_sha256=None, library=lib).path is None
    for mode in ("intro", "none"):
        with pytest.raises(Refused, match="--brand-voice given"):
            library_brand.resolve(with_mode(config, mode), cli_wav="x.wav", cli_sha256=None, library=lib)
    film = library_brand.resolve(with_mode(config, "film"), cli_wav=None, cli_sha256=None, library=lib)
    assert film.mode == "film" and film.path.endswith("VOICE-48k.wav") and film.sha256 == sha256_file(Path(film.path))
    assert "library registry pick VOICE-A" in film.source
    explicit = library_brand.resolve(with_mode(config, "film"), cli_wav="mine.wav", cli_sha256="ab", library=lib)
    assert (explicit.path, explicit.sha256, explicit.source) == ("mine.wav", "ab", "--brand-voice")
    with pytest.raises(Refused, match="must be one of"):
        library_brand.resolve(with_mode(config, "everywhere"), cli_wav=None, cli_sha256=None, library=lib)
    (lib / library_brand.BRAND_DIR / "VOICE-48k.wav").write_bytes(b"tampered")
    with pytest.raises(Refused, match="differs from the registered sha256"):
        library_brand.resolve(with_mode(config, "film"), cli_wav=None, cli_sha256=None, library=lib)
    with pytest.raises(Refused, match="no library"):
        library_brand.resolve(with_mode(config, "film"), cli_wav=None, cli_sha256=None, library=None)


def test_the_patched_mix_has_no_brand_voice_in_intro_mode_and_refuses_an_explicit_one(patched, episode, tmp_path) -> None:  # noqa: F811
    config, root, review, music_wav, _ = episode
    mixcli_patched = patched[1]
    args = make_args(tmp_path, review, music_wav, dry_run=True)
    args.episode = str(Path(config.episode_root) / "engine" / "episode.json")
    summary, code = mixcli_patched.run_mix(args)
    assert code == 0 and summary["brand_voice"] is None and summary["brand_voice_mode"]["mode"] == "intro"
    voice = root / "voice.wav"
    write_tone(voice, 1.0, 0.2, 400.0)
    refused = make_args(tmp_path, review, music_wav, dry_run=True, brand_voice=str(voice))
    refused.episode = args.episode
    with pytest.raises(Refused, match="episode.audio.brand_voice is 'intro'"):
        mixcli_patched.run_mix(refused)
