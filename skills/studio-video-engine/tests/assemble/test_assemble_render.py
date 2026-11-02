"""Policy gate, ffmpeg graph and parser tests: no ffmpeg, no GPU, no network."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import pytest

from engine.assemble import cli, render
from engine.assemble.edl import Refused, code_of

def assemble_block(**overrides) -> dict:
    block = {
        "enabled": True,
        "edl_schema": "demo/film-edl/v1",
        "master": {"width": 2560, "height": 1440, "fps": 24},
        "review": {"width": 1920, "height": 1080},
        "kinds": ["clip", "card", "slate"],
        "transitions": ["cut", "dissolve"],
        "fonts": {"regular": "C:/Windows/Fonts/arial.ttf", "bold": "C:/Windows/Fonts/arialbd.ttf"},
        "audio": {
            "sample_rate": 48000,
            "dialogue_ref_dbfs": -16.5,
            "tracks": [
                {"stem": "final", "title": "Mix", "codec": "flac", "default": True, "language": "vie",
                 "verify_exact": True},
                {"stem": "dialogue", "title": "Dialogue", "codec": "flac", "language": "vie", "verify_exact": True},
                {"stem": "music", "title": "Music", "codec": "flac", "language": "zxx", "verify_exact": True},
                {"stem": "sfx", "title": "SFX", "codec": "flac", "language": "zxx", "verify_exact": True},
            ],
        },
    }
    block.update(overrides)
    return block

def domain(block=None, domain_id: str = "demo_domain") -> dict:
    document = {"domain_id": domain_id, "delivery": {}}
    if block is not None:
        document["delivery"]["assemble"] = block
    return document

def policy(document=None) -> render.AssemblePolicy:
    return render.AssemblePolicy.from_domain(document or domain(assemble_block()))

def test_policy_reads_every_number_from_the_domain():
    built = policy()
    assert built.edl_schema == "demo/film-edl/v1"
    assert built.fps == 24 and built.master == (2560, 1440) and built.review == (1920, 1080)
    assert built.stem_names() == ("final", "dialogue", "music", "sfx")
    assert [track["title"] for track in built.remux()["tracks"]] == ["Mix", "Dialogue", "Music", "SFX"]
    assert built.audio_format() == "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo"

@pytest.mark.parametrize("document", [domain(None), domain(assemble_block(enabled=False))])
def test_domain_without_the_gate_refuses(document):
    with pytest.raises(Refused) as caught:
        render.AssemblePolicy.from_domain(document)
    assert code_of(caught.value) == "ASSEMBLE_NOT_ENABLED"

@pytest.mark.parametrize("block", [
    assemble_block(audio={"sample_rate": 44100, "tracks": assemble_block()["audio"]["tracks"]}),
    assemble_block(master={"width": 0, "height": 1440, "fps": 24}),
    assemble_block(master={"width": 2560, "height": 1440, "fps": 0}),
    assemble_block(kinds=["card"]),
    assemble_block(transitions=["dissolve"]),
    assemble_block(fonts={}),
    assemble_block(audio={"tracks": []}),
    assemble_block(audio={"tracks": assemble_block()["audio"]["tracks"][:3]}),
])
def test_malformed_policy_refuses(block):
    with pytest.raises(Refused) as caught:
        render.AssemblePolicy.from_domain(domain(block))
    assert code_of(caught.value) == "ASSEMBLE_POLICY"

def test_track_list_needs_exactly_one_default():
    block = assemble_block()
    block["audio"] = copy.deepcopy(block["audio"])
    block["audio"]["tracks"][1]["default"] = True
    with pytest.raises(Refused) as caught:
        render.AssemblePolicy.from_domain(domain(block))
    assert code_of(caught.value) == "ASSEMBLE_POLICY"

def test_track_stems_are_unique_and_complete():
    block = assemble_block()
    block["audio"] = copy.deepcopy(block["audio"])
    block["audio"]["tracks"][1]["stem"] = "final"
    with pytest.raises(Refused) as caught:
        render.AssemblePolicy.from_domain(domain(block))
    assert code_of(caught.value) == "ASSEMBLE_POLICY"

def row(sid, start, duration, transition=("cut", 0)):
    return {"id": sid, "kind": "clip", "in_frame": 0, "out_frame": duration, "dur_f": duration,
            "start_f": start, "trans": transition}

def test_filter_graph_pins_timebase_and_uses_xfade():
    segments = [row("A", 0, 96), row("B", 90, 96, ("dissolve", 6)), row("C", 180, 96)]
    graph = render.build_filter_graph(segments, {}, policy())
    assert graph.count("settb=1/24") >= 4
    assert "xfade=transition=fade:duration=0.2500:offset=3.7500" in graph
    assert "concat=n=2:v=1:a=0" in graph
    assert "subtitles=captions.ass:fontsdir=fonts,fps=24,format=yuv420p[vout]" in graph

def test_normal_chain_scales_to_the_domain_master():
    chain = render.normal_chain(row("A", 0, 48), None, policy())
    assert "trim=start_frame=0:end_frame=48" in chain
    assert "crop=w=trunc(min(iw\\,ih*2560/1440)/2)*2" in chain
    assert "scale=2560:1440:flags=lanczos" in chain

def test_captions_are_karaoke_ass(tmp_path):
    document = {"film_id": "demo-film", "dialogue": [
        {"id": "D1", "segment": "A", "at_s": 0.0, "text": "hai ba bon", "speech_window_s": [0.2, 2.0]}]}
    segments = [row("A", 0, 96)]
    work = tmp_path / "work"
    work.mkdir()
    text, notes = render.build_caption_ass(document, segments, work, policy(), tmp_path)
    assert "{\\k" in text and "[Events]" in text and "hai" in text
    assert notes[0]["id"] == "D1" and notes[0]["timing"] == "ESTIMATED(placeholder)"
    assert (work / "captions.ass").read_text(encoding="utf-8") == text

def test_output_names_follow_the_film_and_tag():
    paths = render.output_paths(Path("out"), "demo-film", "final-v001", policy())
    assert paths["master"].name == "demo-film-final-v001-2560x1440-4track.mp4"
    assert paths["review"].name == "demo-film-final-v001-1920x1080-review-aac.mp4"
    assert paths["aac_mix"].name == "demo-film-final-v001-2560x1440-aac-mix.mp4"

def test_parser_registers_edit_assemble():
    parser = argparse.ArgumentParser(prog="jjv")
    stages = parser.add_subparsers(dest="stage", required=True)
    edit = stages.add_parser("edit")
    verbs = edit.add_subparsers(dest="verb", required=True)
    cli.register_edit_verb(verbs)
    parsed = parser.parse_args(["edit", "assemble", "--domain", "demo_domain", "--edl", "x.json",
                                "--validate-only"])
    assert (parsed.stage, parsed.verb, parsed.validate_only) == ("edit", "assemble", True)
    parsed = parser.parse_args(["edit", "assemble", "--episode", "ep", "--edl", "x.json",
                                "--out-dir", "out", "--tag", "t"])
    assert (parsed.stage, parsed.verb, parsed.tag) == ("edit", "assemble", "t")

def test_base_resolution_prefers_the_explicit_folder(tmp_path):
    edl = tmp_path / "a" / "b" / "edl.json"
    edl.parent.mkdir(parents=True)
    edl.write_text("{}", encoding="utf-8")
    assert cli.resolve_base(edl, str(tmp_path)) == tmp_path
    assert cli.resolve_base(edl, None) == edl.parent

def test_live_domain_file_builds_a_valid_policy_and_the_other_domain_stays_off():
    import json
    from engine.config.loader import SKILL_ROOT
    live = json.loads((SKILL_ROOT / "domains" / "newtecons_live_action.json").read_text("utf-8"))
    built = render.AssemblePolicy.from_domain(live)
    assert built.master == (2560, 1440) and built.fps == 24
    assert [t["title"] for t in built.remux()["tracks"]] == ["Mix", "Dialogue", "Music", "SFX"]
    cartoon = json.loads((SKILL_ROOT / "domains" / "jenniejoy_cartoon_3d.json").read_text("utf-8"))
    with pytest.raises(Refused) as caught:
        render.AssemblePolicy.from_domain(cartoon)
    assert code_of(caught.value) == "ASSEMBLE_NOT_ENABLED"
