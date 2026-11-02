"""CPU ASS burn; preserve an approved mux's audio packets, or explicitly encode a silent candidate."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Callable

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from ..seedvr2.seam_media import ffmpeg_flags
from .gate import object_field, require_timing

Runner = Callable[[list[str]], "tuple[int, str]"]
RECEIPT_SCHEMA = "jjv/captions-burn-receipt/v1"


def _domain_requires_h3_binding(config: object) -> bool:
    """Return the domain captions policy, defaulting to optional for old configs."""
    domain = getattr(config, "domain", None)
    if not isinstance(domain, dict):
        return False
    captions = domain.get("captions")
    return isinstance(captions, dict) and captions.get("require_h3_binding") is True


def _h3_wav_binding(path: Path) -> tuple[str, str]:
    """Read the conditioning WAV sha from an H3 preparation receipt."""
    if not path.is_file():
        raise Refused(f"H3_PREPARATION_MISSING: {path}")
    try:
        document = read_json(path)
    except (OSError, ValueError, TypeError) as error:
        raise Refused(f"H3_PREPARATION_INVALID: cannot read {path}: {error}") from error
    if not isinstance(document, dict):
        raise Refused(f"H3_PREPARATION_INVALID: {path} must contain an object")
    wav = document.get("wav")
    receipt_sha = wav.get("sha256") if isinstance(wav, dict) else None
    if (not isinstance(receipt_sha, str) or len(receipt_sha) != 64
            or any(ch not in "0123456789abcdefABCDEF" for ch in receipt_sha)):
        raise Refused(f"H3_PREPARATION_INVALID: {path} wav.sha256 must be a sha256 hex digest")
    return receipt_sha.lower(), sha256_file(path)


def filter_path(path: Path) -> str:
    """Quote an ffmpeg filter path, including Windows drive and apostrophe."""
    text = str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"'{text}'"


def default_runner(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, creationflags=ffmpeg_flags(), timeout=1800)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run {argv[0]}: {error}") from error
    return done.returncode, done.stderr.decode("utf-8", errors="replace")


def _capture(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              creationflags=ffmpeg_flags(), timeout=1800)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot inspect media: {error}") from error
    if done.returncode:
        raise Uncertain(f"media inspection failed: {done.stderr[-600:]}")
    return done.stdout


def media_facts(ffprobe: str, path: Path) -> dict:
    try:
        data = json.loads(_capture([ffprobe, "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)]))
        streams = data["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        return {"frames": int(video["nb_read_frames"]), "duration_s": float(video["duration"]),
                "audio_streams": sum(s["codec_type"] == "audio" for s in streams)}
    except (ValueError, KeyError, TypeError, StopIteration) as error:
        raise Uncertain(f"cannot measure frame count/duration: {path}") from error


def audio_packets(ffmpeg: str, path: Path) -> list[dict]:
    """SHA256 of ordered per-packet SHA256 payloads, independently for EVERY audio stream.

    Container timestamps/timebases are deliberately excluded; this proves payload preservation.
    """
    output = _capture([ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a",
                       "-c:a", "copy", "-f", "framehash", "-hash", "sha256", "-"])
    streams: dict[int, tuple] = {}
    for line in output.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(",")]
        try:
            index, payload = int(fields[0]), bytes.fromhex(fields[5])
            # FFmpeg may append side-data hashes (e.g. AAC skip-samples).
            # Column 5 remains the encoded packet payload SHA256.
            if len(fields) < 6 or len(payload) != 32:
                raise ValueError("invalid packet hash")
        except (ValueError, IndexError) as error:
            raise Uncertain("unexpected ffmpeg audio framehash row") from error
        digest, count = streams.get(index, (hashlib.sha256(), 0))
        digest.update(payload)
        streams[index] = digest, count + 1
    if not streams:
        raise Refused(f"no audio packets in {path}")
    return [{"stream": i, "packets": n, "sha256": digest.hexdigest()}
            for i, (digest, n) in sorted(streams.items())]


def build_argv(ffmpeg: str, video: Path, wav: Path, ass: Path, fontsdir: Path, fps: int,
               target: Path, *, copy_audio: bool = True) -> list[str]:
    vf = ("scale=1920:-2:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
          f"ass={filter_path(ass)}:fontsdir={filter_path(fontsdir)}")
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-n", "-i", str(video)]
    if not copy_audio:
        argv += ["-i", str(wav)]
    argv += ["-map", "0:v:0", "-map", "0:a" if copy_audio else "1:a:0", "-vf", vf,
             "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p"]
    if copy_audio:
        argv += ["-c:a", "copy"]
    else:
        argv += ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-af", "apad", "-shortest"]
    return argv + ["-movflags", "+faststart", str(target)]


def burn(*, video: Path, ass: Path, wav: Path, out: Path, fontsdir: Path, ffmpeg: str, fps: int,
         episode: str | None = None, timing: Path | None = None, timing_receipt: Path | None = None,
         subtitles: Path | None = None, font: Path | None = None, audio_receipt: Path | None = None,
         allow_aac_from_wav: bool = False, h3_preparation: Path | None = None,
         ffprobe: str | None = None, runner: Runner = default_runner) -> dict:
    """Never bypass timing policy through the Python API. Outputs remain review candidates."""
    video, ass, wav, out, fontsdir = (Path(p) for p in (video, ass, wav, out, fontsdir))
    if type(fps) is not int or fps <= 0:
        raise Refused("fps must be positive")
    receipt_path = out.with_name(out.stem + ".burn-receipt.json")
    if out.exists() or receipt_path.exists():
        raise Refused(f"refusing to overwrite: output or receipt exists: {out}")
    for label, path in (("video", video), ("ass", ass), ("wav", wav)):
        if not path.is_file():
            raise Refused(f"{label} input not found: {path}")
    if not fontsdir.is_dir():
        raise Refused(f"fontsdir not found: {fontsdir}")
    if not episode or timing is None or subtitles is None or font is None:
        raise Refused("burn requires episode, timing, subtitles build receipt and font")
    config, _, timing_binding = require_timing(episode, Path(timing), timing_receipt)
    inputs = {label: {"path": str(path), "sha256": sha256_file(path)} for label, path in
              (("video", video), ("ass", ass), ("wav", wav), ("subtitles", Path(subtitles)), ("font", Path(font)))}
    h3_binding = None
    binding_required = _domain_requires_h3_binding(config)
    if h3_preparation is None:
        if binding_required:
            raise Refused("H3_PREPARATION_REQUIRED: domain captions policy requires --h3-preparation")
    else:
        preparation = Path(h3_preparation)
        receipt_wav_sha, preparation_sha = _h3_wav_binding(preparation)
        if inputs["wav"]["sha256"] != receipt_wav_sha:
            raise Refused(
                f"H3_WAV_MISMATCH: --wav sha256 {inputs['wav']['sha256']} "
                f"does not match {preparation} wav.sha256 {receipt_wav_sha}")
        inputs["h3_preparation"] = {"path": str(preparation), "sha256": preparation_sha}
        h3_binding = {
            "path": str(preparation),
            "sha256": preparation_sha,
            "receipt_wav_sha256": receipt_wav_sha,
            "wav_sha256": inputs["wav"]["sha256"],
            "required_by_domain": binding_required,
        }
    selected = read_json(Path(subtitles))
    if not isinstance(selected, dict):
        raise Refused("selected subtitle receipt must be an object")
    if (selected.get("schema") != "jjv/captions-build-receipt/v1"
            or object_field(object_field(selected, "outputs"), "ass").get("sha256") != inputs["ass"]["sha256"]
            or object_field(selected, "inputs").get("timing") != timing_binding):
        raise Refused("selected subtitle receipt does not bind this ASS and qualified timing")
    font = Path(font).resolve()
    if not font.is_relative_to(fontsdir.resolve()) or font.suffix.lower() not in (".ttf", ".otf", ".ttc"):
        raise Refused("font must be a font file inside fontsdir")
    fonts = [{"path": str(p), "sha256": sha256_file(p)} for p in sorted(fontsdir.rglob("*")) if p.is_file()]
    ffprobe = ffprobe or str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    before_facts = media_facts(ffprobe, video)
    copy_audio = before_facts["audio_streams"] > 0
    if copy_audio:
        if audio_receipt is None:
            raise Refused("existing audio needs a PASS audio mix receipt proving the WAV-derived mux")
        mix = read_json(Path(audio_receipt))
        if not isinstance(mix, dict):
            raise Refused("audio mix receipt must be an object")
        mux = object_field(mix, "mux")
        if (mix.get("schema") != "jjv/audio-mix/v1" or mix.get("verdict") != "PASS"
                or mix.get("episode_id") != config.episode["episode_id"]
                or object_field(mux, "output").get("sha256") != inputs["video"]["sha256"]
                or mux.get("mix_sha256") != inputs["wav"]["sha256"]
                or object_field(object_field(mix, "stems"), "final").get("sha256") != inputs["wav"]["sha256"]):
            raise Refused("audio mix receipt does not bind this video and approved final WAV")
        inputs["audio_receipt"] = {"path": str(audio_receipt), "sha256": sha256_file(Path(audio_receipt))}
        reason = "copy all streams from the PASS WAV-derived audio mux"
        source = video
    else:
        if not allow_aac_from_wav:
            raise Refused("silent picture requires explicit --allow-aac-from-wav; no copyable audio stream")
        source_receipt = read_json(Path(timing_binding["receipt_path"]))
        wavs = object_field(source_receipt, "inputs").get("wavs", [])
        if not isinstance(wavs, list) or not all(isinstance(row, dict) for row in wavs):
            raise Refused("timing receipt WAVs must be a list of objects")
        if not any(row.get("sha256") == inputs["wav"]["sha256"] for row in wavs):
            raise Refused("candidate WAV is not bound by the qualified timing receipt")
        reason = "explicit silent-picture candidate: encode timing-bound PCM WAV as AAC for MP4; apad to picture length"
        source = wav
    before = audio_packets(ffmpeg, source)
    if copy_audio and len(before) != before_facts["audio_streams"]:
        raise Refused("audio packet stream count differs from probe")
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.partial{out.suffix}")
    argv = build_argv(ffmpeg, video, wav, ass, fontsdir, fps, partial, copy_audio=copy_audio)
    try:
        code, stderr = runner(argv)
        if code != 0 or not partial.is_file():
            raise Uncertain(f"ffmpeg exited {code}: {stderr.strip()[-600:]}")
        after = audio_packets(ffmpeg, partial)
        after_facts = media_facts(ffprobe, partial)
        if copy_audio and before != after:
            raise Refused("audio packet hashes changed during stream copy")
        if (after_facts["frames"] != before_facts["frames"]
                or abs(after_facts["duration_s"] - before_facts["duration_s"]) > 1 / fps
                or after_facts["audio_streams"] != len(before)):
            raise Refused("burn changed picture frames/duration or audio stream count")
        # Detect file drift before publishing output or a receipt.
        for row in inputs.values():
            if sha256_file(Path(row["path"])) != row["sha256"]:
                raise Refused("burn input changed during render")
        if any(sha256_file(Path(row["path"])) != row["sha256"] for row in fonts):
            raise Refused("font changed during render")
        if require_timing(episode, Path(timing), timing_receipt)[2] != timing_binding:
            raise Refused("qualified timing changed during render")
        try:
            os.link(partial, out)
        except FileExistsError:
            raise Refused(f"refusing to overwrite: {out}") from None
    finally:
        partial.unlink(missing_ok=True)
    receipt = {"schema": RECEIPT_SCHEMA, "inputs": {**inputs, "timing": timing_binding}, "argv": argv, "fps": fps,
               "fontsdir": str(fontsdir), "fonts": fonts, "font_sha256": inputs["font"]["sha256"],
               "subtitle_sha256": inputs["subtitles"]["sha256"], "ass_sha256": inputs["ass"]["sha256"],
               "word_timing_sha256": timing_binding["sha256"],
               "h3_preparation": h3_binding,
               "audio_packet_hash_pre": before, "audio_packet_hash_post": after,
               "audio_packet_hash_method": "sha256 of ordered binary SHA256 packet payload digests per stream; no timestamps",
               "audio": {"mode": "copy" if copy_audio else "aac", "reason": reason, "source": str(source),
                         "packets_equal": before == after}, "video_before": before_facts, "video_after": after_facts,
               "safe_area_status": "UNKNOWN", "word_count_equality": "NOT_CHECKED",
               "onset_tolerance_result": "NOT_CHECKED", "final_ready": False,
               "outputs": {"video": {"path": str(out), "sha256": sha256_file(out)}}}
    write_json_once(receipt_path, receipt, mode="utf8")
    return receipt
