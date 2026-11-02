"""EDL -> picture -> stems -> multitrack mux -> receipt (CPU only, no GPU, no network).

The port of the staged episode assembler, with every number moved into ``AssemblePolicy``
(built from ``domain.delivery.assemble``): master size + fps, review size, kinds, transitions,
fonts, card look, audio ref level / sample rate / remux track list and the AAC copies.

Pipeline: normalise each EDL segment (trim/setpts/fps/crop/scale/setsar) -> ``settb`` -> ``concat``
for a cut or ``xfade`` for a dissolve -> burn the karaoke ``.ass`` (``engine.captions.ass``) ->
H.264 master picture -> 4 stems (dialogue/music/sfx/mix, ``apad`` to the exact film length) ->
``engine.audio.remux_multi.mux_multitrack`` (video copy, sample-exact FLAC tracks) -> AAC mix copy
+ review copy -> hashed receipt.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..audio.remux_multi import mux_multitrack
from ..core.io import read_json, sha256_bytes, sha256_file
from . import receipt as receipt_mod
from .edl import EDL_SCHEMA, guard_outputs, refuse, validate_edl
from .karaoke import build_caption_ass, estimate_word_times  # noqa: F401  (re-exported)
from .proc import Runner, probe_media, run_cmd, volume_mean_db  # noqa: F401  (re-exported)
from .stems import build_stems
from ..policy import final_gate
from . import cutkind

POLICY_INVALID = "ASSEMBLE_POLICY"

@dataclass(frozen=True)
class AssemblePolicy:
    """Everything the renderer may not invent: it comes from ``domain.delivery.assemble``."""

    domain_id: str
    edl_schema: str
    fps: int
    master: tuple[int, int]
    review: tuple[int, int]
    kinds: tuple[str, ...]
    transitions: tuple[str, ...]
    fonts: Mapping[str, str]
    dialogue_ref_dbfs: float
    sample_rate: int
    tracks: tuple[Mapping[str, Any], ...]
    easy: Mapping[str, Any]
    review_encode: Mapping[str, Any]
    card: Mapping[str, Any]
    final_gate: Mapping[str, Any] | None = None  # domain final_gate block when enabled (preview/final cuts)

    def remux(self) -> dict:
        return {"tracks": [dict(track) for track in self.tracks]}

    def stem_names(self) -> tuple[str, ...]:
        return tuple(str(track["stem"]) for track in self.tracks)

    def audio_format(self) -> str:
        return f"aresample={self.sample_rate},aformat=sample_fmts=s16:channel_layouts=stereo"

    @classmethod
    def from_domain(cls, domain: Mapping[str, Any]) -> "AssemblePolicy":
        """Build the policy from the domain JSON; a missing or malformed block is a refusal."""
        name = domain.get("domain_id") if isinstance(domain, Mapping) else None
        delivery = domain.get("delivery") if isinstance(domain, Mapping) else None
        block = delivery.get("assemble") if isinstance(delivery, Mapping) else None
        if not isinstance(block, Mapping):
            refuse("ASSEMBLE_NOT_ENABLED", f"domain {name!r} declares no delivery.assemble; the assemble verb is disabled")
        if block.get("enabled") is not True:
            refuse("ASSEMBLE_NOT_ENABLED", f"domain {name!r} has delivery.assemble.enabled != true")

        def integer(source: Mapping[str, Any], key: str, minimum: int = 1) -> int:
            value = source.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                refuse(POLICY_INVALID, f"assemble.{key} must be an integer >= {minimum}, got {value!r}")
            return value

        def text(source: Mapping[str, Any], key: str, label: str) -> str:
            value = source.get(key)
            if not isinstance(value, str) or not value:
                refuse(POLICY_INVALID, f"assemble.{label}.{key} must be a non-empty string")
            return value

        def size(source: Any, label: str) -> tuple[int, int]:
            if not isinstance(source, Mapping):
                refuse(POLICY_INVALID, f"assemble.{label} must be an object with width/height")
            return integer(source, "width", 16), integer(source, "height", 16)

        schema = block.get("edl_schema")
        if not isinstance(schema, str) or not schema:
            refuse(POLICY_INVALID, "assemble.edl_schema must be a non-empty string")
        master_block = block.get("master")
        master = size(master_block, "master")
        fps = integer(master_block, "fps") if isinstance(master_block, Mapping) else 0
        if not fps:
            refuse(POLICY_INVALID, "assemble.master.fps must be an integer >= 1")
        review = size(block.get("review"), "review")
        kinds = block.get("kinds")
        if not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) and k for k in kinds):
            refuse(POLICY_INVALID, "assemble.kinds must be a non-empty list of strings")
        if "clip" not in kinds:
            refuse(POLICY_INVALID, "assemble.kinds must include 'clip'")
        transitions = block.get("transitions")
        if not isinstance(transitions, list) or "cut" not in transitions:
            refuse(POLICY_INVALID, "assemble.transitions must be a list that contains 'cut'")
        fonts = block.get("fonts")
        if not isinstance(fonts, Mapping) or not isinstance(fonts.get("regular"), str) or not fonts["regular"] \
                or not all(isinstance(name, str) and name and isinstance(path, str) and path
                           for name, path in fonts.items()):
            refuse(POLICY_INVALID, "assemble.fonts.regular must be a font file path")
        audio = block.get("audio")
        if not isinstance(audio, Mapping):
            refuse(POLICY_INVALID, "assemble.audio must be an object")
        tracks = audio.get("tracks")
        if not isinstance(tracks, list) or len(tracks) != 4:
            refuse(POLICY_INVALID, "assemble.audio.tracks must contain exactly four tracks")
        for track in tracks:
            if not isinstance(track, Mapping) or not all(
                    isinstance(track.get(key), str) and track.get(key) for key in ("stem", "title", "codec")):
                refuse(POLICY_INVALID, "each assemble.audio.tracks row needs stem, title and codec")
            if "default" in track and not isinstance(track["default"], bool):
                refuse(POLICY_INVALID, "assemble.audio.tracks.default must be boolean")
            if "verify_exact" in track and not isinstance(track["verify_exact"], bool):
                refuse(POLICY_INVALID, "assemble.audio.tracks.verify_exact must be boolean")
            if "language" in track and (not isinstance(track["language"], str) or not track["language"]):
                refuse(POLICY_INVALID, "assemble.audio.tracks.language must be a non-empty string")
        if sum(1 for track in tracks if track.get("default") is True) != 1:
            refuse(POLICY_INVALID, "assemble.audio.tracks must mark exactly one track default")
        stems = {str(track["stem"]) for track in tracks}
        if stems != {"final", "dialogue", "music", "sfx"}:
            refuse(POLICY_INVALID, "assemble.audio.tracks must contain final, dialogue, music and sfx exactly once")
        rate_check = audio.get("sample_rate", 48000)
        if isinstance(rate_check, int) and not isinstance(rate_check, bool) and fps and rate_check % fps:
            refuse(POLICY_INVALID, "assemble.audio.sample_rate must be a whole multiple of master.fps "
                   "(the dialogue stem is copied sample-exact per frame)")
        ref = audio.get("dialogue_ref_dbfs", -16.5)
        if not isinstance(ref, (int, float)) or isinstance(ref, bool):
            refuse(POLICY_INVALID, "assemble.audio.dialogue_ref_dbfs must be a number")
        rate = audio.get("sample_rate", 48000)
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 8000:
            refuse(POLICY_INVALID, "assemble.audio.sample_rate must be an integer >= 8000")
        easy = block.get("easy") or {"codec": "aac", "bitrate": "256k"}
        if not isinstance(easy, Mapping):
            refuse(POLICY_INVALID, "assemble.easy must be an object")
        text(easy, "codec", "easy")
        text(easy, "bitrate", "easy")
        review_encode = block.get("review_encode") or {"crf": 18, "audio_bitrate": "192k"}
        if not isinstance(review_encode, Mapping):
            refuse(POLICY_INVALID, "assemble.review_encode must be an object")
        crf = integer(review_encode, "crf", 0)
        if crf > 51:
            refuse(POLICY_INVALID, "assemble.review_encode.crf must be <= 51")
        text(review_encode, "audio_bitrate", "review_encode")
        card = block.get("card") or {"background": "white", "logo_height_frac": 0.42, "logo_fade_frames": 14}
        if not isinstance(card, Mapping):
            refuse(POLICY_INVALID, "assemble.card must be an object")
        text(card, "background", "card")
        logo_fraction = card.get("logo_height_frac", 0.42)
        if not isinstance(logo_fraction, (int, float)) or isinstance(logo_fraction, bool) \
                or not 0 < logo_fraction <= 1:
            refuse(POLICY_INVALID, "assemble.card.logo_height_frac must be in (0, 1]")
        fade = card.get("logo_fade_frames", 14)
        if not isinstance(fade, int) or isinstance(fade, bool) or not 1 <= fade <= 240:
            refuse(POLICY_INVALID, "assemble.card.logo_fade_frames must be an integer in 1..240")
        return cls(
            domain_id=str(name), edl_schema=schema, fps=fps, master=master, review=review,
            kinds=tuple(kinds), transitions=tuple(transitions),
            fonts={str(key): str(value) for key, value in fonts.items()},
            dialogue_ref_dbfs=float(ref), sample_rate=int(rate),
            tracks=tuple(dict(track) for track in tracks), easy=dict(easy),
            review_encode=dict(review_encode), card=dict(card), final_gate=final_gate.block(domain))

def _loudness(stem: Path, ffmpeg: str, runner: Runner) -> float | None:
    stderr = run_cmd([ffmpeg, "-hide_banner", "-nostdin", "-i", stem, "-af", "ebur128=peak=true", "-f", "null", "-"],
                     runner).stderr
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", stderr)
    return float(found[-1]) if found else None

# ---------------------------------------------------------------- picture
def normal_chain(row: Mapping[str, Any], label_file: str | None, policy: AssemblePolicy) -> str:
    """One segment's normalisation (trim -> constant fps -> aspect crop -> master scale)."""
    width, height = policy.master
    parts = [
        f"trim=start_frame={row['in_frame']}:end_frame={row['out_frame']}",
        "setpts=PTS-STARTPTS",
        f"fps={policy.fps}",
        f"crop=w=trunc(min(iw\\,ih*{width}/{height})/2)*2:h=trunc(min(ih\\,iw*{height}/{width})/2)*2",
        f"scale={width}:{height}:flags=lanczos",
        "setsar=1",
        "format=yuv420p",
    ]
    if label_file:
        parts.append(f"drawtext=fontfile=fonts/{Path(policy.fonts['regular']).name}:textfile={label_file}:fontsize=44:"
                     "fontcolor=white:box=1:boxcolor=0xD00000@0.75:boxborderw=10:x=40:y=40")
    if row.get("fade_in_frames"):
        parts.append(f"fade=t=in:st=0:n={int(row['fade_in_frames'])}")
    if row.get("fade_out_frames"):
        frames = int(row["fade_out_frames"])
        parts.append(f"fade=t=out:st={(row['dur_f'] - frames) / policy.fps:.4f}:n={frames}")
    return ",".join(parts)

def build_filter_graph(segments: Sequence[Mapping[str, Any]], label_files: Mapping[str, str],
                       policy: AssemblePolicy, ass_name: str = "captions.ass") -> str:
    """concat (cut) / xfade (dissolve) graph on a ``settb``-pinned timeline, then burn the captions."""
    fps = policy.fps
    lines = [f"[{index}:v]{normal_chain(row, label_files.get(row['id']), policy)},settb=1/{fps}[s{index}]"
             for index, row in enumerate(segments)]
    accumulator, duration = "[s0]", segments[0]["dur_f"]
    for index in range(1, len(segments)):
        kind, frames = segments[index]["trans"]
        following = f"[m{index}]"
        if kind == "dissolve":
            lines.append(f"{accumulator}[s{index}]xfade=transition=fade:duration={frames / fps:.4f}:"
                         f"offset={(duration - frames) / fps:.4f}{following}")
        else:
            lines.append(f"{accumulator}[s{index}]concat=n=2:v=1:a=0,settb=1/{fps},fps={fps}{following}")
        accumulator, duration = following, duration + segments[index]["dur_f"] - frames
    lines.append(f"{accumulator}subtitles={ass_name}:fontsdir=fonts,fps={fps},format=yuv420p[vout]")
    return ";\n".join(lines)

def _canvas(policy: AssemblePolicy) -> str:
    background = str(policy.card.get("background", "white"))
    colour = "white" if background.lower() == "white" else background
    width, height = policy.master
    return f"color=c={colour}:s={width}x{height}:r={policy.fps}"

def make_card(row: Mapping[str, Any], work: Path, policy: AssemblePolicy, ffmpeg: str,
              runner: Runner = subprocess.run) -> Path:
    """Logo card: flat ground, the logo fading in (no template from another film)."""
    out = work / f"card_{row['id']}.mp4"
    width, height = policy.master
    seconds = row["dur_f"] / policy.fps
    logo_height = int(height * float(policy.card.get("logo_height_frac", 0.42)))
    fade = int(policy.card.get("logo_fade_frames", 14))
    graph = (f"[1:v]scale=-1:{logo_height}:flags=lanczos,format=rgba,fade=t=in:st=0:n={fade}:alpha=1[l];"
             "[0:v][l]overlay=x=(W-w)/2:y=(H-h)/2-70:shortest=1,format=yuv420p")
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"{_canvas(policy)}:d={seconds}",
          "-loop", "1", "-framerate", str(policy.fps), "-i", row["logo_path"], "-filter_complex", graph,
          "-frames:v", str(row["dur_f"]), "-c:v", "libx264", "-crf", "12", "-preset", "fast",
          "-pix_fmt", "yuv420p", out], runner)
    return out

def make_slate(row: Mapping[str, Any], work: Path, policy: AssemblePolicy, ffmpeg: str,
               runner: Runner = subprocess.run) -> Path:
    """Placeholder slate: flat ground + the segment id, so a missing shot is never silent."""
    out = work / f"slate_{row['id']}.mp4"
    width, height = policy.master
    text = work / f"slate_{row['id']}.txt"
    text.write_text(f"{row['id']}\nPLACEHOLDER SLATE", encoding="utf-8")
    font = Path(policy.fonts["regular"]).name
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
          f"{_canvas(policy)}:d={row['dur_f'] / policy.fps}", "-vf",
          f"drawtext=fontfile=fonts/{font}:textfile={text.name}:fontsize=120:fontcolor=white:"
          "x=(w-text_w)/2:y=(h-text_h)/2",
          "-frames:v", str(row["dur_f"]), "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", out.name],
         runner, cwd=work)
    return out

# ---------------------------------------------------------------- main
def safe_token(value: str, label: str) -> str:
    """A single filename component; never permits a separator or traversal."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-")
    if not token:
        refuse(POLICY_INVALID, f"{label} must contain at least one safe filename character")
    return token

def output_paths(out_dir: Path, film_id: str, tag: str, policy: AssemblePolicy) -> dict[str, Path]:
    safe_film = safe_token(film_id, "film_id")
    safe_tag = safe_token(tag, "tag")
    width, height = policy.master
    review_width, review_height = policy.review
    easy_codec = str(policy.easy.get("codec", "aac"))
    return {
        "master": out_dir / f"{safe_film}-{safe_tag}-{width}x{height}-{len(policy.tracks)}track.mp4",
        "review": out_dir / f"{safe_film}-{safe_tag}-{review_width}x{review_height}-review-{easy_codec}.mp4",
        "aac_mix": out_dir / f"{safe_film}-{safe_tag}-{width}x{height}-{easy_codec}-mix.mp4",
    }

def assemble(edl_path: Path, out_dir: Path, tag: str, policy: AssemblePolicy, *,
             base: Path | None = None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
             runner: Runner = subprocess.run, cut_kind: str = "final",
             approval_roots: Sequence[Any] = ()) -> dict:
    """Run one master (write-once) and return the receipt dict.

    Where the domain declares ``final_gate``: ``cut_kind="final"`` (default) is refused unless every clip is
    approved (``approval_roots``); ``"preview"`` is allowed and labelled.  Other domains ignore both arguments."""
    edl_path = Path(edl_path).resolve()
    edl = read_json(edl_path)
    base = Path(base) if base else edl_path.parent
    out_dir = Path(out_dir).resolve()
    film_id = str(edl.get("film_id") or "")
    if not film_id:
        refuse(EDL_SCHEMA, "film_id (a non-empty string) is required: it names the outputs")
    if not tag:
        refuse(POLICY_INVALID, "tag must be a non-empty write-once label")
    tag = cutkind.effective_tag(policy.final_gate, cut_kind, tag)
    safe_tag = safe_token(tag, "tag")
    outputs = output_paths(out_dir, film_id, tag, policy)
    work = out_dir / f"work-{safe_tag}"
    guard_outputs([*outputs.values(), work, out_dir / f"receipt-{safe_tag}.json"])

    validation = validate_edl(edl, base, schema=policy.edl_schema, fps=policy.fps, kinds=policy.kinds,
                              transitions=policy.transitions, probe=lambda path: probe_media(path, ffprobe, runner))
    segments = validation["segments"]
    cut = cutkind.gate_cut(policy.final_gate, validation, cut_kind, approval_roots)  # refuses BEFORE any render

    (work / "fonts").mkdir(parents=True, exist_ok=True)
    for name, source in policy.fonts.items():
        path = Path(source)
        if not path.is_file():
            refuse(POLICY_INVALID, f"assemble.fonts.{name} not found: {path}")
        shutil.copy(path, work / "fonts" / path.name)

    inputs, labels = [], {}
    for row in segments:
        if row["kind"] == "card":
            path = make_card(row, work, policy, ffmpeg, runner)
        elif row["kind"] == "slate":
            path = make_slate(row, work, policy, ffmpeg, runner)
        else:
            path = Path(row["src_path"])
        inputs += ["-i", path]
        if row.get("placeholder") and not edl.get("no_labels"):
            name = f"label_{row['id']}.txt"
            (work / name).write_text(f"PLACEHOLDER {row['id']}", encoding="utf-8")
            labels[row["id"]] = name

    stems, audio_report = build_stems(edl, validation, work, policy, base, ffmpeg, runner)
    ass_text, caption_notes = build_caption_ass(edl, segments, work, policy, base)
    (work / "graph.txt").write_text(build_filter_graph(segments, labels, policy), encoding="utf-8")

    width, height = policy.master
    picture = work / f"picture-{width}x{height}.mp4"
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-/filter_complex", "graph.txt",
          "-map", "[vout]", "-an", "-frames:v", str(validation["total_frames"]), "-c:v", "libx264",
          "-preset", "medium", "-crf", "16", "-profile:v", "high", "-pix_fmt", "yuv420p",
          "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
          "-movflags", "+faststart", picture], runner, cwd=work)

    mux = mux_multitrack(ffmpeg, ffprobe, picture, stems, outputs["master"], policy.remux(), policy.fps, runner)
    easy_codec = str(policy.easy.get("codec", "aac"))
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-i", outputs["master"], "-map", "0:v:0",
          "-map", "0:a:0", "-c:v", "copy", "-c:a", easy_codec, "-b:a", str(policy.easy.get("bitrate", "256k")),
          "-movflags", "+faststart", outputs["aac_mix"]], runner)
    review_width, review_height = policy.review
    run_cmd([ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-i", outputs["master"], "-map", "0:v:0",
          "-map", "0:a:0", "-vf", f"scale={review_width}:{review_height}:flags=lanczos", "-c:v", "libx264",
          "-preset", "medium", "-crf", str(policy.review_encode.get("crf", 18)), "-pix_fmt", "yuv420p",
          "-c:a", easy_codec, "-b:a", str(policy.review_encode.get("audio_bitrate", "192k")),
          "-movflags", "+faststart", outputs["review"]], runner)

    probes = {name: json.loads(run_cmd([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
                                     runner).stdout)
              for name, path in (("master", outputs["master"]), ("review", outputs["review"]),
                                 ("aac_mix", outputs["aac_mix"]))}
    film = {"total_frames": validation["total_frames"],
            "duration_s": round(validation["total_frames"] / policy.fps, 4),
            "fps": policy.fps, "size": [width, height]}
    document = receipt_mod.build_receipt(
        domain_id=policy.domain_id, tag=tag, edl_path=edl_path, edl_sha256=sha256_file(edl_path), film=film,
        segments=segments, shas=validation["shas"], audio=audio_report,
        captions={"ass_sha256": sha256_bytes(ass_text.encode("utf-8")), "entries": caption_notes},
        mix_integrated_lufs=_loudness(stems["final"], ffmpeg, runner), outputs=outputs, stems=stems,
        picture=picture, mux=mux, probes=probes)
    if cut is not None:
        document.update(cut_kind=cut["cut_kind"], approvals=cut["approvals"])
    receipt_mod.write_receipt(out_dir, safe_tag, document)
    return document
