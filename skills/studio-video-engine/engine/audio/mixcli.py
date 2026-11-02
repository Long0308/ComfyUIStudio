"""CLI glue of ``jjv audio mix`` (inputs -> render -> receipt -> optional mux).  Dry run renders nothing."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ..config.loader import ResolvedConfig, resolve_episode
from ..core.errors import Refused, Uncertain
from ..core.io import read_json
from ..seedvr2.seam_media import find_ffmpeg
from . import mix, remux, remux_multi, sections as sections_mod, timeline as timeline_mod, windows as windows_mod
from .dsp import merge_windows
from .recipe import optional_block, resolve_recipe
from . import library_brand, musicpick_cli  # noqa: E402


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="mix version directory (stems, final mix, receipt)")
    parser.add_argument("--review-config", required=True, help="review config: timeline, WAV bindings, sections")
    parser.add_argument("--recipe", default=None, help="audio-mix recipe id (default: the domain's only cinema one)")
    parser.add_argument("--total-frames", type=int, default=None, help="film length in frames (default: review config)")
    parser.add_argument("--music-receipt", default=None, help="music-finalize.json (stem path + sha)")
    parser.add_argument("--music-wav", default=None, help="a music WAV instead of a receipt")
    parser.add_argument("--music-sha256", default=None, help="expected sha256 of --music-wav")
    parser.add_argument("--extra-wav", action="append", default=[],
                        help="one more receipt WAV 'name|path|sha256|start_frame[|class]' (e.g. a late end line, class end_line): its own speech bus")
    parser.add_argument("--library", default=None, help="library root (default: <episodes folder>/_library); brand voice registry pick")
    parser.add_argument("--brand-voice", default=None, help="the channel's brand voice WAV: plays ALONE first, the music starts after it")
    parser.add_argument("--brand-voice-sha256", default=None, help="expected sha256 of --brand-voice")
    parser.add_argument("--brand-voice-start-s", type=float, default=0.15)
    parser.add_argument("--brand-voice-db", type=float, default=0.0, help="gain of the brand voice layer (default 0: the WAV as is)")
    parser.add_argument("--with-sfx", action="store_true",
                        help="opt in to SFX/ambience (OFF by default on this channel; or episode.audio.sfx.enabled)")
    parser.add_argument("--audio-override", default=None,
                        help="JSON ({'audio': {'sfx_enabled': bool}} - the video panel's settings JSON works): the choice wins over --with-sfx, "
                             "the episode and the recipe default")
    parser.add_argument("--allow-ungated-music", action="store_true",
                        help="use a music receipt whose vocal-free gate did not PASS (recorded in the receipt)")
    parser.add_argument("--sfx-receipt", default=None, help="sfx-finalize.json (clips + placements)")
    parser.add_argument("--sfx-stem", default=None, help="a pre-rendered SFX/ambience stem WAV instead of a receipt")
    parser.add_argument("--sfx-sha256", default=None, help="expected sha256 of --sfx-stem")
    parser.add_argument("--windows", default=None, help="explicit duck windows (JSON list) instead of the WAV speech")
    parser.add_argument("--sections", default=None, help="explicit sections (JSON list) instead of the derived ones")
    parser.add_argument("--allow-outside", action="append", default=[], help="extra root a WAV may live in")
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--dry-run", action="store_true", help="validate every input and print the plan; render nothing")
    parser.add_argument("--remux", default=None, help="silent picture (mp4): write picture video copy + the final mix")
    parser.add_argument("--remux-out", default=None, help="the muxed film (new file, never overwritten)")


def _music(args: argparse.Namespace, rate: int) -> mix.Source:
    if bool(args.music_receipt) == bool(args.music_wav):
        raise Refused("pass exactly one of --music-receipt and --music-wav")
    if args.music_receipt:
        path = Path(args.music_receipt)
        stem = (read_json(path).get("stem") or {})
        if not stem.get("path") or not stem.get("sha256"):
            raise Refused(f"{path}: no stem path/sha256 (is it a music-finalize.json?)")
        status = (stem.get("vocal_gate") or {}).get("status", "NOT_RUN")
        if status != "PASS" and not getattr(args, "allow_ungated_music", False):
            raise Refused(f"{path}: the music bed's vocal-free gate is {status}, not PASS (a bed with a vocal under the "
                          "dialogue is refused); fix the separator command or pass --allow-ungated-music")
        source = mix.load_source(path.parent / stem["path"], stem["sha256"], rate, "music stem")
        return mix.Source(source.path, source.sha256, source.audio), {"source": "receipt", "vocal_gate": status}
    source = mix.load_source(Path(args.music_wav), args.music_sha256, rate, "music WAV")
    return source, {"source": "explicit WAV", "vocal_gate": "not applicable (explicit WAV)"}


def load_audio_override(path: str | None) -> dict:
    """The video panel's per-episode choice. Only ``sfx_enabled`` is honoured; a mute of the voice/music stem would
    break the loudness gate, so ``mute_stems`` is refused rather than silently ignored."""
    if not path:
        return {}
    block = read_json(Path(path)).get("audio") or {}
    if block.get("mute_stems"):
        raise Refused(f"{path}: audio.mute_stems {block['mute_stems']!r} is not supported by the mix (it would break the "
                      "loudness/pumping gate); the voice and music stems are written separately - drop them at remux")
    if "sfx_enabled" in block and not isinstance(block["sfx_enabled"], bool):
        raise Refused(f"{path}: audio.sfx_enabled must be true or false, got {block['sfx_enabled']!r}")
    return {"sfx_enabled": block["sfx_enabled"]} if "sfx_enabled" in block else {}


def sfx_enabled(config: ResolvedConfig, recipe: dict, flag: bool, override: dict | None = None) -> bool:
    """SFX follow ``--audio-override`` first, then ``--with-sfx``, ``episode.audio.sfx.enabled`` or the recipe default
    (true only when the domain grants ``audio.sfx_default_on``; enforced when the recipe loads)."""
    if override and "sfx_enabled" in override:
        return bool(override["sfx_enabled"])
    declared = optional_block(optional_block(config.episode, "audio"), "sfx").get("enabled")
    return bool(flag or declared is True or recipe["sfx"]["default_enabled"])


def _sfx(args: argparse.Namespace, rate: int, enabled: bool, forced_off: bool = False) -> dict:
    if not enabled:
        if (args.sfx_receipt or args.sfx_stem) and not forced_off:
            raise Refused("SFX/ambience are OFF by default on this channel (only the voice and the music bed); "
                          "pass --with-sfx or set episode.audio.sfx.enabled to use --sfx-receipt/--sfx-stem")
        return {"source": "none", "enabled": False}
    if args.sfx_receipt and args.sfx_stem:
        raise Refused("pass at most one of --sfx-receipt and --sfx-stem")
    if args.sfx_stem:
        return {"stem": mix.load_source(Path(args.sfx_stem), args.sfx_sha256, rate, "SFX stem"), "source": "stem",
                "enabled": True}
    if not args.sfx_receipt:
        return {"source": "none", "enabled": True}
    path = Path(args.sfx_receipt)
    receipt = read_json(path)
    clips = {c["clip_id"]: mix.load_source(path.parent / c["path"], c["sha256"], rate, f"SFX clip {c['clip_id']}").audio
             for c in receipt.get("clips", [])}
    missing = sorted({p["clip_id"] for p in receipt.get("placements", [])} - set(clips))
    if missing:
        raise Refused(f"{path}: placements name clips that are not in the receipt: {missing}")
    return {"clips": clips, "placements": receipt["placements"], "source": "receipt", "enabled": True,
            "receipt": {"path": path.name, "sha256": mix.sha256_file(path)}}


def _ffprobe(ffmpeg: str) -> str:
    sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    found = str(sibling) if sibling.is_file() else shutil.which("ffprobe")
    if not found:
        raise Uncertain("ffprobe not found next to ffmpeg or on PATH")
    return found


def _plan_rows(config: ResolvedConfig, args: argparse.Namespace) -> dict:
    recipe, origin = resolve_recipe(config, "audio-mix", args.recipe)
    rate = recipe.data["sample_rate"]
    review = timeline_mod.load_review_config(args.review_config)
    line = timeline_mod.resolve(config, review, rate, getattr(args, "total_frames", None))
    allow = tuple(Path(p) for p in args.allow_outside)
    placed = windows_mod.load_placed(review, Path(config.episode_root), line, allow)
    placed = sorted(placed + [windows_mod.load_extra(spec, Path(config.episode_root), line, allow) for spec in getattr(args, "extra_wav", [])],
                    key=lambda w: (w.start_sample, w.name))
    speech = recipe.data["speech"]
    wins = (windows_mod.load_windows(args.windows, rate) if args.windows
            else windows_mod.windows_from_bindings(placed, speech["threshold_dbfs"], speech["window_ms"]))
    choice = library_brand.resolve(config, cli_wav=getattr(args, "brand_voice", None),
                                   cli_sha256=getattr(args, "brand_voice_sha256", None),
                                   library=musicpick_cli.library_dir(config, getattr(args, "library", None)))
    args.brand_voice, args.brand_voice_sha256 = choice.path, choice.sha256
    brand = None
    if getattr(args, "brand_voice", None):
        if not wins:
            raise Refused("a brand voice needs speech windows to end before")
        brand = windows_mod.load_brand_voice(args.brand_voice, getattr(args, "brand_voice_sha256", None), line,
                                             getattr(args, "brand_voice_start_s", 0.15),
                                             min(w["start_sample"] for w in wins))
    end_frame = -(-brand.end_sample * line["fps"] // rate) if brand else None  # ceil
    rows = timeline_mod.checked_sections(config, sections_mod.load_sections(args.sections, line) if args.sections
                                         else sections_mod.derive_sections(review, line, end_frame))
    music, music_info = _music(args, rate)
    override = load_audio_override(getattr(args, "audio_override", None))
    return {"recipe": recipe, "origin": origin, "review": review, "timeline": line, "placed": placed, "windows": wins,
            "brand": brand, "brand_choice": choice, "sections": rows, "music": music, "music_info": music_info, "rate": rate,
            "audio_override": override,
            "sfx": _sfx(args, rate, sfx_enabled(config, recipe.data, getattr(args, "with_sfx", False), override),
                        forced_off=override.get("sfx_enabled") is False)}


def _describe(plan: dict) -> dict:
    duck, rate = plan["recipe"].data["duck"], plan["rate"]
    merged = merge_windows([{**w, "start_sample": max(0, w["start_sample"])} for w in plan["windows"]],
                           int(round(duck["merge_gap_s"] * rate))) if duck["merge_gap_s"] > 0 else plan["windows"]
    return {"recipe": {"id": plan["recipe"].recipe_id, "sha256": plan["recipe"].sha256, "profile": plan["recipe"].data["profile"],
                       "origin": plan["origin"]}, "timeline": plan["timeline"],
            "dialogue_wavs": [{"name": w.name, "sha256": w.sha256, "start_frame": w.start_frame, "samples": w.data.frames}
                              for w in plan["placed"]],
            "duck": {**duck, "speech_windows": len(plan["windows"]), "duck_windows_after_merge": len(merged)},
            "sections": [{k: s[k] for k in ("name", "start_frame", "end_frame_exclusive")} for s in plan["sections"]],
            "music": {"path": plan["music"].path.name, "sha256": plan["music"].sha256, **plan["music_info"]},
            "brand_voice_mode": {"mode": plan["brand_choice"].mode, "source": plan["brand_choice"].source},
            "brand_voice": None if plan["brand"] is None else {
                "sha256": plan["brand"].sha256, "start_s": plan["brand"].start_sample / plan["rate"],
                "end_s": plan["brand"].end_sample / plan["rate"], "samples": plan["brand"].data.frames},
            "sfx": {"source": plan["sfx"]["source"], "enabled": plan["sfx"]["enabled"],
                    "placements": len(plan["sfx"].get("placements", []))}}


def run_mix(args: argparse.Namespace) -> tuple[dict, int]:
    config = resolve_episode(args.episode)
    plan = _plan_rows(config, args)
    if args.remux and not args.remux_out:
        raise Refused("--remux needs --remux-out (a new file; the picture is never overwritten)")
    if args.dry_run:
        return {"ok": True, "dry_run": True, **_describe(plan)}, 0
    out, ffmpeg = Path(args.out), find_ffmpeg(args.ffmpeg)
    body = mix.render(plan["recipe"], timeline=plan["timeline"], placed=plan["placed"], windows=plan["windows"],
                      sections=plan["sections"], music_src=plan["music"], sfx_parts=plan["sfx"], out=out, ffmpeg=ffmpeg,
                      emit=lambda m: print(m, file=sys.stderr), brand=plan["brand"],
                      brand_gain_db=getattr(args, "brand_voice_db", 0.0))
    receipt = {"schema": mix.RECEIPT_SCHEMA, "episode_id": config.episode["episode_id"], "config_sha256": config.config_sha256,
               **{k: v for k, v in _describe(plan).items() if k != "duck"}, "duck": {**plan["recipe"].data["duck"]},
               "inputs": {"review_config_sha256": mix.sha256_file(Path(args.review_config)), "audio_override": plan["audio_override"],
                          "sfx": {k: v for k, v in plan["sfx"].items() if k in ("source", "receipt", "enabled")}},
               **body}
    if plan["brand"] is not None:
        section = next((r for r in body["loudness"]["sections"] if r["name"] == "brand_voice"), None)
        receipt["brand_voice"].update(gain_db=getattr(args, "brand_voice_db", 0.0), file_name=Path(plan["brand"].path).name,
                                      section_lufs=section["integrated_lufs"] if section else None,
                                      stem_sha256=body["stems"]["brand_voice"]["sha256"])
    ok = body["verdict"] in ("PASS", "UNGATED")
    if args.remux:
        if not ok:
            receipt["mux"] = {"skipped": "the mix gate failed: a failing mix is never muxed into a film"}
        else:
            remux_cfg = plan["recipe"].data["remux"]
            if remux_cfg.get("tracks"):
                receipt["mux"] = remux_multi.mux_multitrack(
                    ffmpeg, _ffprobe(ffmpeg), Path(args.remux), {k: out / v for k, v in mix.STEMS.items()},
                    Path(args.remux_out), remux_cfg, plan["timeline"]["fps"])
            else:
                receipt["mux"] = remux.mux(ffmpeg, _ffprobe(ffmpeg), Path(args.remux), out / mix.STEMS["final"],
                                           Path(args.remux_out), remux_cfg, plan["timeline"]["fps"])
            receipt["mux"]["mix_sha256"] = body["stems"]["final"]["sha256"]
            receipt["mux"]["stem_sha256"] = {k: v["sha256"] for k, v in body["stems"].items()}
    mix.write_receipt(out, receipt)
    return {"ok": ok, "dry_run": False, "verdict": body["verdict"], "failures": body["failures"],
            "unmeasured_sections": body["unmeasured"], "receipt": str(out / mix.RECEIPT_FILE),
            "whole": body["loudness"]["whole"], "stems": {k: v["sha256"] for k, v in body["stems"].items()},
            "mux": receipt.get("mux")}, (0 if ok else 1)
