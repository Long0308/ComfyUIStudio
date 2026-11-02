"""``jjv audio sfx``: cue sheet + plan (``cues``), guarded generation (``submit``), clip WAVs (``finalize``).

One clip is generated per cue CLASS in use and placed at every frame that class has; a placement row is
``frame, duration, gain, pan, source sha, the action it describes``.  Finalize decodes each FLAC to 48 kHz
stereo, trims leading/trailing silence, peak-normalises, fades the ends and writes the clip WAV write-once.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, write_once
from ..voice.wavio import metrics, read_wav, wav_bytes
from . import cuesheet, dsp, graphs, guiwrite, jobs
from .recipe import AudioRecipe

PLAN_FILE = "sfx-plan.json"
FINALIZE_FILE = "sfx-finalize.json"
PLAN_SCHEMA = "jjv/audio-sfx-plan/v1"
FINALIZE_SCHEMA = "jjv/audio-sfx-finalize/v1"
CLIPS_DIR = "clips"


def load_shot_texts(path: Path | None, fields: list[str], *, required: bool = True) -> dict[str, str]:
    """``{shot: text}`` from a shot pack (``shots[]`` rows with ``shot_id``/``shot``) or a plain mapping."""
    if path is None:
        if required:
            raise Refused("no shot pack: pass --shot-pack (the action text of every shot is the input of the cue sheet)")
        return {}
    document = read_json(Path(path))
    rows = document.get("shots") if isinstance(document, dict) else document
    texts: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            ident = row.get("shot_id") or row.get("shot") if isinstance(row, dict) else None
            if ident:
                texts[str(ident)] = " ".join(str(row[f]) for f in fields if isinstance(row.get(f), str))
    elif isinstance(document, dict) and all(isinstance(v, str) for v in document.values()):
        texts = dict(document)
    if not any(texts.values()):
        raise Refused(f"no shot action text found in {path} (fields {fields}); pass --text-field or a {{shot: text}} map")
    return texts


def build_plan(config: ResolvedConfig, recipe: AudioRecipe, origin: str, *, out: Path, timeline: dict, sheet: dict,
               write: bool, review_config_sha256: str | None) -> dict:
    data, episode_id, run_name = recipe.data, config.episode["episode_id"], Path(out).name
    rows = []
    for index, clip in enumerate(sheet["clips"]):
        values = {"prompt": clip["prompt"], "negative": data["negative_prompt"], "seed": clip["seed"],
                  "seconds": clip["seconds"], "filename_prefix": jobs.filename_prefix(episode_id, run_name, clip["clip_id"])}
        graph = graphs.fill_slots(data, values)
        saved = (jobs.write_workflow(out, clip["clip_id"], graph) if write else
                 {"graph_file": f"{jobs.WORKFLOWS_DIR}/{clip['clip_id']}.api.json", "graph_file_sha256": None,
                  "graph_sha256": graphs.graph_sha256(graph)})
        rows.append({"job_id": clip["clip_id"], "index": index, "seconds": clip["seconds"], "seed": clip["seed"],
                     "class": clip["class"], "prompt": clip["prompt"], "loop": clip["loop"],
                     "filename_prefix": values["filename_prefix"], "receipt_dir": f"{jobs.JOBS_DIR}/{clip['clip_id']}", **saved})
    return {"schema": PLAN_SCHEMA, "episode_id": episode_id, "domain": config.domain["domain_id"],
            "config_sha256": config.config_sha256, "review_config_sha256": review_config_sha256,
            "recipe": {"id": recipe.recipe_id, "sha256": recipe.sha256, "origin": origin}, "timeline": timeline,
            "models": jobs.model_rows(data), "licences": jobs.licence_rows(data), "jobs": rows,
            "placements": sheet["placements"], "skipped": sheet["skipped"],
            "uncovered_shots": sheet["uncovered_shots"]}


def load_plan(out: Path) -> dict:
    plan = read_json(Path(out) / PLAN_FILE)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise Refused(f"{Path(out) / PLAN_FILE}: not a {PLAN_SCHEMA} document")
    return plan


def trim_silence(audio: np.ndarray, threshold_dbfs: float, rate: int, window_ms: int = 10) -> np.ndarray:
    """Cut leading/trailing windows whose RMS is below ``threshold_dbfs``; an all-silent clip is Refused."""
    size = max(1, rate * window_ms // 1000)
    count = audio.shape[0] // size
    if count == 0:
        raise Refused("generated clip is shorter than one analysis window")
    energy = np.sqrt(np.mean(np.square(audio[:count * size].reshape(count, size, -1).astype(np.float64)), axis=(1, 2)))
    loud = np.nonzero(energy >= 10 ** (threshold_dbfs / 20.0))[0]
    if loud.size == 0:
        raise Refused(f"generated clip is silent (every {window_ms} ms window below {threshold_dbfs} dBFS)")
    return audio[loud[0] * size:min(audio.shape[0], (loud[-1] + 1) * size)]


def finalize(out: Path, plan: dict, recipe: AudioRecipe, *, output_root: Path, ffmpeg: str, rate: int,
             run_decode=jobs.decode_to_wav, object_info=None, input_dir: Path | None = None) -> dict:
    if recipe.sha256 != plan["recipe"]["sha256"]:
        raise Refused("the sfx recipe changed since the plan was written; re-plan")
    post, clips, produced_by_job = recipe.data["postprocess"], {}, {}
    for job in plan["jobs"]:
        made = jobs.job_output(out, job, recipe.data, output_root)
        produced_by_job[job["job_id"]] = made
        native = run_decode(ffmpeg, made["path"], Path(out) / "native", rate=rate, soxr=True)
        write_once(Path(out) / "native" / f"{job['job_id']}.wav", native)
        wav = read_wav(Path(out) / "native" / f"{job['job_id']}.wav")
        audio = dsp.to_stereo_float(np.frombuffer(wav.pcm, dtype="<i2").reshape(-1, wav.channels))
        audio = trim_silence(audio, post["trim_threshold_dbfs"], rate).copy()
        peak = float(np.max(np.abs(audio)))
        audio *= dsp.db_to_gain(post["peak_dbfs"]) / peak
        audio *= dsp.smooth_fades(audio.shape[0], post["fade_in_s"], post["fade_out_s"], rate)
        pcm = dsp.to_pcm16(audio)
        path = Path(out) / CLIPS_DIR / f"{job['job_id']}-{rate // 1000}k.wav"
        digest = write_once(path, wav_bytes(rate, 2, 2, pcm.tobytes()))
        clips[job["job_id"]] = {"clip_id": job["job_id"], "class": job["class"], "path": f"{CLIPS_DIR}/{path.name}",
                                "sha256": digest, "duration_s": pcm.shape[0] / rate, "seed": job["seed"],
                                "prompt_id": made["prompt_id"], "graph_sha256": made["graph_sha256"],
                                "comfy_output_sha256": made["sha256"], "metrics": metrics(read_wav(path))}
    placed = []
    for row in plan["placements"]:
        clip = clips[row["clip_id"]]
        placed.append({**row, "source_sha256": clip["sha256"], "clip_duration_s": clip["duration_s"],
                       "duration_s": row["duration_s"] if row["loop"] else min(row["duration_s"], clip["duration_s"])})
    receipt = {"schema": FINALIZE_SCHEMA, "episode_id": plan["episode_id"],
               "plan_sha256": canonical_sha256(plan, mode="ascii"), "recipe": plan["recipe"], "models": plan["models"],
               "licences": plan["licences"], "timeline": plan["timeline"], "clips": list(clips.values()),
               "placements": placed, "skipped": plan["skipped"],
               "workflows": guiwrite.write_guis(out, plan, produced_by_job, object_info, input_dir, label="sfx"),
               "status": "CANDIDATE_PENDING_LISTENING"}
    jobs.write_receipt_once(Path(out) / FINALIZE_FILE, receipt)
    return receipt
