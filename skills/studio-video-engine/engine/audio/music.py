"""``jjv audio music``: plan (script -> brief -> two-stage YuE2 graph), submit (guarded), finalize (loop-extended bed).

The method of the take the user liked on the first episode, as data + code:

* style text = the recipe's fixed structural/safety wording + the episode's ``bpm``, ``key``, ``instruments``;
  lyrics = the recipe's empty section skeleton (no words, so no vocals);
* the brief is derived from the script (``engine.audio.brief``) and may be overridden by
  ``episode.audio.music.brief``, ``--brief`` and flags;
* one job per take: ``YuE2GenerateABC`` -> ``YuE2GenerateMusic`` -> KSampler -> ``VAEDecodeAudioTiled`` ->
  ``SaveAudio`` (graph = the recipe template with named slots only);
* YuE2 ends when its planned song ends (cap ``max_duration_s``), so finalize loop-extends the song at a bar
  boundary to the film length + ``target_extra_s`` keeping its natural ending (``engine.audio.loopext``);
* receipts bind every model file (path, bytes, sha256) and the licence text relied on.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, write_once
from ..voice.wavio import metrics, read_wav, wav_bytes
from . import dsp, graphs, guiwrite, jobs, loopext, vocalgate
from .recipe import AudioRecipe, optional_block

PLAN_FILE = "music-plan.json"
FINALIZE_FILE = "music-finalize.json"
PLAN_SCHEMA = "jjv/audio-music-plan/v1"
FINALIZE_SCHEMA = "jjv/audio-music-finalize/v1"
BEDS_DIR = "beds"
BRIEF_KEYS = ("bpm", "key", "instruments")


def resolve_brief(config: ResolvedConfig, recipe: dict, *, derived: dict | None, brief_file: dict | None,
                  overrides: dict[str, Any]) -> tuple[dict, dict]:
    """(brief, sources): lowest layer first; one source name per key."""
    layers = [("recipe.default_brief", recipe["default_brief"]), ("derived from the script", derived or {}),
              ("episode.audio.music.brief", optional_block(optional_block(optional_block(
                  config.episode, "audio"), "music"), "brief")),
              ("--brief", brief_file or {}), ("cli", {k: v for k, v in overrides.items() if v is not None})]
    brief: dict = {}
    sources: dict = {}
    for name, layer in layers:
        for key, value in layer.items():
            brief[key], sources[key] = value, name
    missing = [key for key in BRIEF_KEYS if key not in brief]
    if missing:
        raise Refused(f"music brief lacks {missing}")
    bpm = brief["bpm"]
    if isinstance(bpm, bool) or not isinstance(bpm, (int, float)) or not 40 <= bpm <= 240:
        raise Refused(f"brief bpm must be a number in [40, 240], got {bpm!r}")
    if "major" not in str(brief["key"]).lower():
        raise Refused(f"brief key {brief['key']!r}: the method keeps a major key (the fixed wording says so)")
    return brief, sources


def style_text(recipe: dict, brief: dict) -> str:
    try:
        return recipe["style_template"].format(**{key: brief[key] for key in BRIEF_KEYS})
    except (KeyError, ValueError) as error:
        raise Refused(f"style_template does not fit the brief: {error}") from error


def candidate_briefs(recipe: dict, brief: dict, count: int) -> list[dict]:
    """The chosen brief first, then ``count - 1`` that differ in instrument set, key and tempo (a real choice for the
    user, not three seeds of one idea): the next palettes, keys and tempi of the recipe, in order."""
    spec = recipe["derivation"]
    palettes = [p["instruments"] for p in spec["instrument_palettes"]]
    keys = spec["keys"]
    tempi = sorted(set(spec["tempo"]["by_energy"].values()))
    p0 = palettes.index(brief["instruments"]) if brief["instruments"] in palettes else -1
    k0 = keys.index(brief["key"]) if brief["key"] in keys else 0
    t0 = tempi.index(int(brief["bpm"])) if int(brief["bpm"]) in tempi else 0
    out = [dict(brief)]
    for step in range(1, count):
        out.append({"bpm": tempi[(t0 + step) % len(tempi)], "key": keys[(k0 + step) % len(keys)],
                    "instruments": palettes[(p0 + step) % len(palettes)]})
    return out


def build_plan(config: ResolvedConfig, recipe: AudioRecipe, origin: str, *, out: Path, timeline: dict, brief: dict,
               brief_sources: dict, evidence: dict | None, takes: int, seed: int | None, write: bool,
               candidates: int = 1) -> dict:
    data = recipe.data
    if takes < 1 or candidates < 1:
        raise Refused("--takes and --candidates must be at least 1")
    base_seed = data["seed_base"] if seed is None else seed
    episode_id, run_name = config.episode["episode_id"], Path(out).name
    extra = data["loop_extend"]["target_extra_s"]
    rows = []
    for number, cand in enumerate(candidate_briefs(data, brief, candidates)):
        style = style_text(data, cand)
        for take in range(takes):
            job_id = f"music-c{number + 1:02d}-t{take + 1:02d}"
            job_seed = base_seed + number * 100 + take
            values = {"style": style, "lyrics": data["lyrics"], "seed": job_seed, "seconds": data["max_duration_s"],
                      "filename_prefix": jobs.filename_prefix(episode_id, run_name, job_id)}
            graph = graphs.fill_slots(data, values)
            saved = (jobs.write_workflow(out, job_id, graph) if write else
                     {"graph_file": f"{jobs.WORKFLOWS_DIR}/{job_id}.api.json", "graph_file_sha256": None,
                      "graph_sha256": graphs.graph_sha256(graph)})
            rows.append({"job_id": job_id, "index": len(rows), "candidate": number + 1, "take": take + 1,
                         "brief": cand, "style": style, "seconds": data["max_duration_s"], "seed": job_seed,
                         "filename_prefix": values["filename_prefix"], "receipt_dir": f"{jobs.JOBS_DIR}/{job_id}", **saved})
    return {"schema": PLAN_SCHEMA, "episode_id": episode_id, "domain": config.domain["domain_id"],
            "config_sha256": config.config_sha256,
            "recipe": {"id": recipe.recipe_id, "sha256": recipe.sha256, "origin": origin},
            "brief": brief, "brief_sources": brief_sources, "brief_evidence": evidence,
            "prompt": {"style": rows[0]["style"], "lyrics": data["lyrics"]}, "timeline": timeline,
            "bed_target_s": float(math.ceil(timeline["duration_s"]) + extra), "models": jobs.model_rows(data),
            "licences": jobs.licence_rows(data), "jobs": rows}


def load_plan(out: Path) -> dict:
    plan = read_json(Path(out) / PLAN_FILE)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise Refused(f"{Path(out) / PLAN_FILE}: not a {PLAN_SCHEMA} document")
    return plan


def finalize(out: Path, plan: dict, recipe: AudioRecipe, *, output_root: Path, ffmpeg: str, rate: int,
             pick: str | None = None, run_decode=jobs.decode_to_wav, object_info=None,
             input_dir: Path | None = None, vocal_gate: vocalgate.VocalGate | None = None,
             vocal_runner=subprocess.run) -> dict:
    """Decode every take, loop-extend it to the bed target, write beds write-once, run the vocal-free gate on each
    bed (``vocal_gate``; none configured = NOT_RUN, which the mix refuses), write the receipt.  The stem is ``pick``,
    else the first take whose gate PASSes, else the first take (the receipt then says so)."""
    if recipe.sha256 != plan["recipe"]["sha256"]:
        raise Refused("the music recipe changed since the plan was written; re-plan")
    data, spec = recipe.data, recipe.data["loop_extend"]
    ids = [job["job_id"] for job in plan["jobs"]]
    if pick is not None and pick not in ids:
        raise Refused(f"--pick {pick!r} is not one of {ids}")
    rows, produced_by_job = [], {}
    for job in plan["jobs"]:
        produced = jobs.job_output(out, job, data, output_root)
        produced_by_job[job["job_id"]] = produced
        native = Path(out) / "native" / f"{job['job_id']}.wav"
        native_sha = write_once(native, run_decode(ffmpeg, produced["path"], Path(out) / "native", rate=rate))
        wav = read_wav(native)
        song = dsp.to_stereo_float(np.frombuffer(wav.pcm, dtype="<i2").reshape(-1, wav.channels))
        bed, loop = loopext.extend(song, float(job["brief"]["bpm"]), plan["bed_target_s"], rate,
                                   crossfade_s=spec["crossfade_s"], beats_per_bar=spec["beats_per_bar"],
                                   intro_bars=spec["intro_bars"], window_bars=spec["window_bars"])
        pcm = dsp.to_pcm16(bed)
        path = Path(out) / BEDS_DIR / f"{job['job_id']}-bed-{rate // 1000}k.wav"
        bed_sha = write_once(path, wav_bytes(rate, 2, 2, pcm.tobytes()))
        limit = data["vocal_gate"]["limit_db"]
        gate_row = (vocalgate.run(vocal_gate, path, Path(out) / "vocal-gate" / job["job_id"], vocal_runner, ffmpeg) if vocal_gate
                    else vocalgate.not_run("no separator command: set machine.audio.vocal_gate.command or pass "
                                           "--vocal-gate-command", limit))
        rows.append({"job_id": job["job_id"], "seed": job["seed"], "brief": job["brief"], "prompt_id": produced["prompt_id"],
                     "graph_sha256": produced["graph_sha256"], "comfy_output_sha256": produced["sha256"],
                     "song_wav": f"native/{job['job_id']}.wav", "song_wav_sha256": native_sha,
                     "song_duration_s": wav.duration_s, "loop_extend": loop, "vocal_gate": gate_row,
                     "bed": {"path": f"{BEDS_DIR}/{path.name}", "sha256": bed_sha, "duration_s": pcm.shape[0] / rate,
                             "long_enough": pcm.shape[0] / rate >= plan["bed_target_s"] - 1e-6,
                             "metrics": metrics(read_wav(path))}})
    passing = [r for r in rows if r["vocal_gate"]["status"] == "PASS"]
    chosen = next(r for r in rows if r["job_id"] == (pick or (passing[0] if passing else rows[0])["job_id"]))
    status = {"PASS": "CANDIDATE_PENDING_LISTENING", "NOT_RUN": "VOCAL_GATE_NOT_RUN"}.get(chosen["vocal_gate"]["status"],
                                                                                       "VOCAL_GATE_FAIL")
    receipt = {"schema": FINALIZE_SCHEMA, "episode_id": plan["episode_id"],
               "plan_sha256": canonical_sha256(plan, mode="ascii"), "recipe": plan["recipe"], "models": plan["models"],
               "licences": plan["licences"], "prompt": plan["prompt"], "brief": plan["brief"], "takes": rows,
               "timeline": plan["timeline"], "bed_target_s": plan["bed_target_s"],
               "stem": {"take": chosen["job_id"], **{k: chosen["bed"][k] for k in ("path", "sha256", "duration_s")},
                        "picked_by": "--pick" if pick else ("first take that passed the vocal gate" if passing else "first take"),
                        "vocal_gate": chosen["vocal_gate"]},
               "workflows": guiwrite.write_guis(out, plan, produced_by_job, object_info, input_dir, label="music"),
               "status": status}
    jobs.write_receipt_once(Path(out) / FINALIZE_FILE, receipt)
    return receipt
