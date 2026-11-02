"""``jjv voice finalize``: native take -> editorial format -> speaker transform -> ONE trim -> split.

The only module that imports :mod:`engine.voice.trim` (rule E_TRIM_ONCE).  Every WAV is
write-once; the receipt ``voice-finalize.json`` is write-once and binds every output sha.  A
second finalize over the same ``--out`` with other trim parameters, another recipe or
another source is Refused as ``E_TRIM_ONCE``.  Receipt WAVs are used at offset 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.io import read_json, sha256_bytes, sha256_file, write_json_once
from . import approval, handoff, receipts, voice_bindings
from .recipe import VoiceSettings
from .split import SplitPart, apply_split, concat_proof, parse_split_plan
from .trim import TrimParams, has_speech, trim_bounds, trim_pcm
from .wavio import (WavData, convert_to_editorial, ffmpeg_version, metrics, pitch_factor, pitch_shift,
                    read_wav, write_wav_once)

FINALIZE_SCHEMA_ID = "jjv/voice-finalize/v1"


@dataclass(frozen=True)
class FinalizeContext:
    settings: VoiceSettings
    config: ResolvedConfig
    out: Path
    plan: dict
    ffmpeg: str
    category: str = "dialogue"  # dialogue | vocabulary | all
    resample_lineage: bool = False  # explicit format conversion; never changes passthrough

    @property
    def episode_root(self) -> Path:
        return Path(self.config.episode_root)

    def describe(self, path: Path) -> str:
        return receipts.describe_path(path, episode_root=self.episode_root, out=self.out)


def _once(action: str, call, *args, **kwargs):
    """Run a write-once step; a conflicting existing file is the E_TRIM_ONCE refusal."""
    try:
        return call(*args, **kwargs)
    except Refused as error:
        raise Refused(f"E_TRIM_ONCE: {action}: {error}") from error


def _check_existing_receipt(context: FinalizeContext, params: TrimParams | None) -> None:
    path = context.out / receipts.FINALIZE_FILE
    if not path.is_file():
        return
    existing = read_json(path)
    if not isinstance(existing, dict) or existing.get("schema") != FINALIZE_SCHEMA_ID:
        raise Refused(f"E_TRIM_ONCE: {path} exists and is not a {FINALIZE_SCHEMA_ID} receipt")
    if (existing.get("mode") == "resample_lineage") != context.resample_lineage:
        raise Refused(f"E_RESAMPLE_OPTIONS: {path} already binds a different resample-lineage option")
    if existing.get("trim") != (params.as_dict() if params else None)             or (existing.get("recipe") or {}).get("sha256") != context.settings.recipe.sha256:
        raise Refused(f"E_TRIM_ONCE: {path} already binds a finalize with other trim parameters or recipe; "
                      "a different trim needs a new version directory")


def _editorial(context: FinalizeContext, job: dict, native: Path) -> tuple[Path, WavData, Path, WavData]:
    recipe = context.settings.recipe.data
    fmt = recipe["editorial"]
    rate, channels = int(fmt["sample_rate"]), int(fmt["channels"])
    tag = f"{rate // 1000}k"
    folder = context.out / "finalize"
    safe = receipts.safe_id(job["request_id"])
    base = folder / f"{safe}-base-{tag}.wav"
    _once("editorial conversion", convert_to_editorial, context.ffmpeg, native, base, rate=rate, channels=channels)
    base_wav = read_wav(base)
    if base_wav.rate != rate or base_wav.channels != channels or base_wav.frames <= 0:
        raise Refused(f"{job['request_id']}: editorial WAV is {base_wav.rate} Hz x{base_wav.channels}, "
                      f"expected {rate} Hz x{channels} with samples")
    semitones = float(job["transform"]["pitch_semitones"])
    if semitones == 0:
        return base, base_wav, base, base_wav
    final = folder / f"{safe}-editorial-{tag}.wav"
    _once("pitch transform", pitch_shift, context.ffmpeg, base, final, semitones=semitones,
          sample_count=base_wav.frames, rate=rate, channels=channels, transform=recipe["transform"])
    final_wav = read_wav(final)
    if final_wav.frames != base_wav.frames:
        raise Refused(f"{job['request_id']}: pitch transform changed the sample count "
                      f"{base_wav.frames} -> {final_wav.frames}")
    return base, base_wav, final, final_wav


def _transform_record(job: dict, recipe: dict) -> dict:
    semitones = float(job["transform"]["pitch_semitones"])
    if semitones == 0:
        return {"pitch_semitones": 0, "tempo": 1, "formants": "unchanged", "sample_count": "unchanged"}
    return {"pitch_semitones": semitones, "pitch_factor": pitch_factor(semitones), "tempo": 1,
            "method": recipe["transform"]["method"], "formants": recipe["transform"]["formant"],
            "sample_count": "identical_to_base"}


def _split(context: FinalizeContext, job: dict, final_wav: WavData, start_sample: int, params: TrimParams,
           tag: str) -> dict:
    plan = parse_split_plan(job["split"], job["request_id"])
    frame_bytes = final_wav.frame_bytes
    source_pcm = final_wav.pcm[start_sample * frame_bytes:]
    parts = apply_split(source_pcm, frame_bytes, plan)
    proof = concat_proof(parts, source_pcm, frame_bytes, plan)
    safe = receipts.safe_id(job["request_id"])
    rows = []
    for part in parts:
        _check_declared_silence(job, part, final_wav, params)
        path = context.out / "finalize" / f"{safe}-{part.segment.label}-{tag}.wav"
        digest = _once(f"segment {part.segment.label}", write_wav_once, path, final_wav.rate, final_wav.channels,
                       final_wav.sample_width, part.pcm)
        rows.append({"label": part.segment.label, "path": context.describe(path), "sha256": digest,
                     "samples": part.segment.samples, "duration_s": part.segment.samples / final_wav.rate,
                     "real_samples": part.real_samples, "padded_samples": part.padded_samples,
                     "start_sample_in_editorial": start_sample + part.start_sample,
                     "speech_conditioning": part.segment.speech_conditioning,
                     "receipt_wav": part.segment.speech_conditioning, "offset_s": 0.0})
    joined = b"".join(part.pcm for part in parts)
    full_path = context.out / "finalize" / f"{safe}-full-{tag}.wav"  # the line as ONE WAV: what timing/mix/subtitles bind
    full_digest = _once("full line WAV", write_wav_once, full_path, final_wav.rate, final_wav.channels,
                        final_wav.sample_width, joined)
    return {"source": "editorial WAV from trim start_sample", "start_sample": start_sample,
            "pad_tail_silence": plan.pad_tail_silence, "segments": rows, "proof": proof,
            "concatenated_pcm_sha256": sha256_bytes(joined),
            "full": {"path": context.describe(full_path), "sha256": full_digest,
                     "samples": sum(p.segment.samples for p in parts),
                     "duration_s": sum(p.segment.samples for p in parts) / final_wav.rate}}


def _check_declared_silence(job: dict, part: SplitPart, final_wav: WavData, params: TrimParams) -> None:
    if part.segment.speech_conditioning or part.real_samples == 0:
        return
    real = WavData(final_wav.rate, final_wav.channels, final_wav.sample_width, part.real_samples,
                   part.pcm[:part.real_samples * final_wav.frame_bytes])
    if has_speech(real, params):
        raise Refused(f"{job['request_id']}: segment {part.segment.label!r} is declared silent "
                      "(speech_conditioning false) but contains speech windows")


def finalize_job(context: FinalizeContext, job: dict, params: TrimParams | None) -> dict:
    if context.resample_lineage:
        return _resample_lineage_job(context, job)
    if params is None:
        return _passthrough_job(context, job)
    recipe = context.settings.recipe.data
    take, native = receipts.read_take(context.out, job, episode_root=context.episode_root)
    base, base_wav, final, final_wav = _editorial(context, job, native)
    final_metrics = metrics(final_wav)
    if final_metrics["clipped_samples"] > int(recipe["clipped_samples_max"]):
        raise Refused(f"{job['request_id']}: {final_metrics['clipped_samples']} clipped samples "
                      f"(max {recipe['clipped_samples_max']})")
    bounds = trim_bounds(final_wav, params)
    tag = f"{final_wav.rate // 1000}k"
    receipt_path = context.out / "finalize" / f"{receipts.safe_id(job['request_id'])}-receipt-{tag}.wav"
    digest = _once("receipt WAV", write_wav_once, receipt_path, final_wav.rate, final_wav.channels,
                   final_wav.sample_width, trim_pcm(final_wav, bounds))
    receipt_wav = read_wav(receipt_path)
    duration = receipt_wav.duration_s
    limit = job.get("max_duration_s")
    if limit is not None and duration > float(limit):
        raise Refused(f"{job['request_id']}: receipt WAV lasts {duration:.3f} s, over the budget {limit} s")
    entry = {
        "request_id": job["request_id"], "category": job["category"], "shot": job["source_id"],
        "speaker": job["speaker"], "request_sha256": job["request_sha256"],
        "native": {"path": take["native"]["path"], "sha256": take["native"]["sha256"], "audio_id": take["audio_id"]},
        "base": {"path": context.describe(base), "sha256": sha256_file(base), "samples": base_wav.frames},
        "transform": _transform_record(job, recipe),
        "editorial": {"path": context.describe(final), "sha256": sha256_file(final), "samples": final_wav.frames,
                      "metrics": final_metrics},
        "trim": bounds.as_dict(),
        "receipt_wav": {"path": context.describe(receipt_path), "sha256": digest, "samples": receipt_wav.frames,
                        "duration_s": duration, "metrics": metrics(receipt_wav), "offset_s": 0.0,
                        "source_sha256": sha256_file(final)},
        "speech_conditioning": True,
        "budget": {"max_duration_s": limit, "checked": limit is not None},
        "split": None,
        "class": job["category"],
        "listen_approval": _approval_record(context, job, take),
    }
    if job.get("split"):
        entry["split"] = _split(context, job, final_wav, bounds.start_sample, params, tag)
    entry["mix"] = handoff.entry_handoff(entry, job, context.out, context.episode_root)
    return entry


def _passthrough_job(context: FinalizeContext, job: dict) -> dict:
    """Recipe mode ``passthrough``: the bound take IS the receipt WAV (no conversion, transform, trim or split).

    The take must already be in the editorial format and the speaker transform must be 0; any other case is
    Refused, never converted, so receipt_wav.sha256 == native.sha256 (the sha the listener approved)."""
    recipe = context.settings.recipe.data
    take, native = receipts.read_take(context.out, job, episode_root=context.episode_root)
    wav = read_wav(native)
    fmt = recipe["editorial"]
    if (wav.rate, wav.channels, wav.sample_width) != (int(fmt["sample_rate"]), int(fmt["channels"]),
                                                       int(fmt["sample_width_bytes"])) or wav.frames <= 0:
        raise Refused(f"E_PASSTHROUGH_FORMAT: {job['request_id']}: take is {wav.rate} Hz x{wav.channels} "
                      f"x{wav.sample_width * 8} bit, the passthrough recipe needs {fmt['sample_rate']} Hz "
                      f"x{fmt['channels']} x{int(fmt['sample_width_bytes']) * 8} bit; it is never converted")
    if float(job["transform"]["pitch_semitones"]) != 0 or job.get("split"):
        raise Refused(f"E_PASSTHROUGH_EDIT: {job['request_id']}: a passthrough recipe cannot apply a pitch transform or a split")
    measured = metrics(wav)
    if measured["clipped_samples"] > int(recipe["clipped_samples_max"]):
        raise Refused(f"{job['request_id']}: {measured['clipped_samples']} clipped samples (max {recipe['clipped_samples_max']})")
    limit = job.get("max_duration_s")
    if limit is not None and wav.duration_s > float(limit):
        raise Refused(f"{job['request_id']}: receipt WAV lasts {wav.duration_s:.3f} s, over the budget {limit} s")
    sha, described = take["native"]["sha256"], take["native"]["path"]
    entry = {
        "request_id": job["request_id"], "category": job["category"], "shot": job["source_id"],
        "speaker": job["speaker"], "request_sha256": job["request_sha256"],
        "native": {"path": described, "sha256": sha, "audio_id": take["audio_id"]},
        "base": {"path": described, "sha256": sha, "samples": wav.frames},
        "transform": {"mode": "passthrough", "pitch_semitones": 0, "tempo": 1, "formants": "unchanged",
                      "sample_count": "unchanged"},
        "editorial": {"path": described, "sha256": sha, "samples": wav.frames, "metrics": measured},
        "trim": None,
        "receipt_wav": {"path": described, "sha256": sha, "samples": wav.frames, "duration_s": wav.duration_s,
                        "metrics": measured, "offset_s": 0.0, "source_sha256": sha},
        "speech_conditioning": True,
        "budget": {"max_duration_s": limit, "checked": limit is not None},
        "split": None,
        "class": job["category"],
        "listen_approval": _approval_record(context, job, take),
    }
    entry["mix"] = handoff.entry_handoff(entry, job, context.out, context.episode_root)
    return entry



def _resample_inputs(context: FinalizeContext, job: dict) -> tuple[dict, Path, dict]:
    """Preflight only: explicit conversion requires an approved 24k mono PCM16 source."""
    if not context.settings.recipe.passthrough:
        raise Refused("E_RESAMPLE_RECIPE: --resample-lineage requires a passthrough recipe")
    fmt = context.settings.recipe.data["editorial"]
    if (int(fmt["sample_rate"]), int(fmt["channels"]), int(fmt["sample_width_bytes"])) != (48000, 2, 2):
        raise Refused("E_RESAMPLE_FORMAT: --resample-lineage requires a 48000 Hz stereo PCM16 target")
    if float(job["transform"]["pitch_semitones"]) != 0 or job.get("split"):
        raise Refused("E_RESAMPLE_EDIT: --resample-lineage cannot apply pitch, split or trim")
    take, native = receipts.read_take(context.out, job, episode_root=context.episode_root)
    binding = approval.approval_binding(context.out, job, take["native"]["sha256"])
    if binding is None:
        raise Refused(f"E_RESAMPLE_APPROVAL: {job['request_id']}: source take has no matching listen approval")
    try:
        wav = read_wav(native)
    except Refused as error:
        raise Refused(f"E_RESAMPLE_FORMAT: {error}") from error
    if (wav.rate, wav.channels, wav.sample_width) != (24000, 1, 2) or wav.frames <= 0:
        raise Refused("E_RESAMPLE_FORMAT: --resample-lineage requires a nonempty 24000 Hz mono PCM16 source")
    return take, native, binding


def _resample_lineage_job(context: FinalizeContext, job: dict) -> dict:
    """Approved source -> explicit SOXR conversion, recorded separately from passthrough."""
    from . import resample_lineage

    take, native, binding = _resample_inputs(context, job)
    path = context.out / "finalize" / f"{receipts.safe_id(job['request_id'])}-resample-lineage-48k.wav"
    lineage = resample_lineage.convert(context.ffmpeg, native, path)
    if lineage["source_sha256"] != binding["subject_sha256"]:
        raise Refused("E_RESAMPLE_SOURCE_CHANGED: converter source differs from the approved take")
    lineage["approval_record_sha256"] = binding["record_sha256"]
    wav = read_wav(path)
    measured = metrics(wav)
    recipe = context.settings.recipe.data
    if measured["clipped_samples"] > int(recipe["clipped_samples_max"]):
        raise Refused(f"E_RESAMPLE_CLIPPING: {measured['clipped_samples']} clipped samples "
                      f"(max {recipe['clipped_samples_max']})")
    limit = job.get("max_duration_s")
    if limit is not None and wav.duration_s > float(limit):
        raise Refused(f"E_RESAMPLE_BUDGET: receipt WAV lasts {wav.duration_s:.3f} s, over the budget {limit} s")
    sha, described = lineage["derived_sha256"], context.describe(path)
    entry = {
        "request_id": job["request_id"], "category": job["category"], "shot": job["source_id"],
        "speaker": job["speaker"], "request_sha256": job["request_sha256"],
        "native": {"path": take["native"]["path"], "sha256": take["native"]["sha256"], "audio_id": take["audio_id"]},
        "base": {"path": described, "sha256": sha, "samples": wav.frames},
        "transform": {"mode": "resample_lineage", "pitch_semitones": 0, "tempo": 1, "formants": "unchanged",
                      "sample_count": "rate_conversion_only"},
        "editorial": {"path": described, "sha256": sha, "samples": wav.frames, "metrics": measured},
        "trim": None,
        "receipt_wav": {"path": described, "sha256": sha, "samples": wav.frames, "duration_s": wav.duration_s,
                        "metrics": measured, "offset_s": 0.0, "source_sha256": take["native"]["sha256"]},
        "speech_conditioning": True,
        "budget": {"max_duration_s": limit, "checked": limit is not None},
        "split": None,
        "class": job["category"],
        "listen_approval": {"required": True, **binding},
        "lineage": lineage,
    }
    entry["mix"] = handoff.entry_handoff(entry, job, context.out, context.episode_root)
    return entry


def _approval_record(context: FinalizeContext, job: dict, take: dict) -> dict:
    """Bound approval when the domain requires one; ``{"required": False}`` otherwise (keeps the receipt stable)."""
    if not context.settings.require_listen_approval:
        return {"required": False}
    binding = approval.approval_binding(context.out, job, take["native"]["sha256"])
    return {"required": True, **(binding or {})}


def selected_jobs(plan: dict, category: str) -> list[dict]:
    return [job for job in plan["jobs"] if category == "all" or job["category"] == category]


def _params(context: FinalizeContext) -> TrimParams | None:
    """The single trim of a synth recipe; None for a passthrough recipe (nothing is trimmed)."""
    if context.resample_lineage and not context.settings.recipe.passthrough:
        raise Refused("E_RESAMPLE_RECIPE: --resample-lineage requires a passthrough recipe")
    return None if context.settings.recipe.passthrough else TrimParams.from_recipe(context.settings.recipe.data)


def run_finalize(context: FinalizeContext) -> dict:
    params = _params(context)
    _check_existing_receipt(context, params)
    jobs = selected_jobs(context.plan, context.category)
    if not jobs:
        raise Refused(f"no planned jobs of category {context.category!r}")
    missing = [job["request_id"] for job in jobs if receipts.job_state(context.out, job["request_id"]) != "COMPLETED"]
    if missing:
        raise Refused(f"finalize needs a bound take for every job; missing: {missing}")
    if context.resample_lineage:
        for job in jobs:
            _resample_inputs(context, job)  # all jobs approved/compatible before any WAV is written
    elif context.settings.require_listen_approval:
        approval.require_approved(context.out, jobs, context.episode_root)  # before any WAV is written
    version = ffmpeg_version(context.ffmpeg)
    entries = [finalize_job(context, job, params) for job in jobs]
    receipt = {
        "schema": FINALIZE_SCHEMA_ID,
        "episode_id": context.config.episode["episode_id"],
        "domain": context.config.domain["domain_id"],
        "config_sha256": context.config.config_sha256,
        "canonical_mode": "ascii",
        "recipe": {"id": context.settings.recipe.recipe_id, "sha256": context.settings.recipe.sha256},
        "plan_sha256": sha256_file(context.out / receipts.PLAN_FILE),
        "category": context.category,
        "editorial_format": dict(context.settings.recipe.data["editorial"]),
        "trim": params.as_dict() if params else None,
        **({"mode": "resample_lineage" if context.resample_lineage else "passthrough"} if params is None else {}),  # a synth receipt stays byte-stable
        "tool": {"ffmpeg_version": version},
        "offset_rule": "receipt WAVs are used at offset 0 for H3 conditioning and editorial",
        "listen_approval": {"required": context.settings.require_listen_approval or context.resample_lineage},
        "mix_handoff": handoff.receipt_handoff(entries),
        "entries": entries,
    }
    _once("finalize receipt",
          lambda: write_json_once(context.out / receipts.FINALIZE_FILE, receipt, mode="ascii", stamp=True))
    _once("voice bindings", voice_bindings.write_bindings, context.out, context.plan, receipt)
    return receipt


def dry_run(context: FinalizeContext) -> dict:
    params = _params(context)
    _check_existing_receipt(context, params)
    rows = []
    for job in selected_jobs(context.plan, context.category):
        state = receipts.job_state(context.out, job["request_id"])
        row = {"request_id": job["request_id"], "class": job["category"], "state": state,
               "transform": job["transform"], "split": bool(job.get("split"))}
        if state == "COMPLETED":
            take, _ = receipts.read_take(context.out, job, episode_root=context.episode_root)
            row["native_sha256"] = take["native"]["sha256"]
            row["approved"] = approval.approval_binding(context.out, job, take["native"]["sha256"]) is not None
        rows.append(row)
    required = context.settings.require_listen_approval or context.resample_lineage
    blocked = [r["request_id"] for r in rows if required and not r.get("approved")]
    return {**({"mode": "resample_lineage", "requested_conversion": {"source": "24000 Hz mono PCM16",
                     "derived": "48000 Hz stereo PCM16", "resampler": "soxr", "precision": 28,
                     "channel_operation": "duplicate mono to both channels", "trim": None}}
               if context.resample_lineage else {}),
            "trim": params.as_dict() if params else None, "ffmpeg_version": ffmpeg_version(context.ffmpeg), "jobs": rows,
            "listen_approval": {"required": required, "blocked": blocked}}
