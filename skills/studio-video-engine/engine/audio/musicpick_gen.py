"""The generation fall-through of ``jjv audio music pick``: used ONLY when no library bed fits.

Two generators, one pipeline (``music.build_plan`` -> guarded ``jobs.run_all`` -> ``music.finalize``):

* ``acestep`` (preferred: its raw bed passed the vocal-free gate in the first lane): the saved API graph of the
  pick recipe, with the brief's bpm and key set in the graph before the plan is built, and
  ``duration = min(duration_cap_s, bed target)``;
* ``yue2`` (fallback): the existing two-stage ``audio/music-yue2-int8-v001`` recipe, untouched.

Both are turned into an :class:`AudioRecipe` that the existing music code accepts; its sha256 is derived from
(pick recipe sha256, generator, brief, bed target) so a later ``adopt`` rebuilds the identical object.  Nothing here POSTs
by hand: execution is ``jobs.run_all`` (GPU lock, idle queue, intent, one POST, history wait).
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from ..comfy.client import ComfyClient, ComfyError
from ..comfy.guards import ClassPolicy
from ..comfy.settings import ComfySettings, settings_from_machine
from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.io import canonical_sha256
from . import jobs, music
from .recipe import AudioRecipe

GENERATORS = ("acestep", "yue2")


def generator_order(data: dict, forced: str | None) -> list[str]:
    if forced:
        if forced not in GENERATORS:
            raise Refused(f"--generator must be one of {GENERATORS}, got {forced!r}")
        return [forced]
    gen = data["generation"]
    return [gen["preferred"], gen["fallback"]]


def derived_recipe(pick: AudioRecipe, base: AudioRecipe, generator: str, brief: dict, bed_target_s: float) -> AudioRecipe:
    """The recipe object the music code runs for ``generator`` (``base`` = the YuE2 recipe: its derivation tables, loop
    and gate settings are shared)."""
    if generator == "yue2":
        return base
    if generator != "acestep":
        raise Refused(f"unknown generator {generator!r}")
    spec = pick.data["generation"]["acestep"]
    data = copy.deepcopy(base.data)
    graph = copy.deepcopy(spec["graph"])
    for binding, value in ((spec["bpm_binding"], float(brief["bpm"])), (spec["keyscale_binding"], str(brief["key"]))):
        graph[binding[0]]["inputs"][binding[1]] = int(value) if isinstance(value, float) and value.is_integer() else value
    data.update(recipe_id=f"{pick.recipe_id}#acestep", engine="acestep", models=copy.deepcopy(spec["models"]),
                licences=copy.deepcopy(spec["licences"]), graph=graph, slots=copy.deepcopy(spec["slots"]),
                output=copy.deepcopy(spec["output"]), seed_base=spec["seed_base"], style_template=spec["style_template"],
                lyrics=spec["lyrics"], max_duration_s=float(min(spec["duration_cap_s"], math.ceil(bed_target_s))))
    data["note"] = spec["note"]
    sha = canonical_sha256({"pick": pick.sha256, "generator": generator, "brief": brief, "target": bed_target_s}, mode="ascii")
    return AudioRecipe(data["recipe_id"], "audio-music", pick.path, sha, data)


def rebuild(pick: AudioRecipe, base: AudioRecipe, plan: dict) -> AudioRecipe:
    """The recipe a saved plan was built from (``adopt`` after a restart)."""
    recipe_id = plan["recipe"]["id"]
    generator = recipe_id.rsplit("#", 1)[1] if "#" in recipe_id else "yue2"
    return derived_recipe(pick, base, generator, plan["brief"], float(plan["bed_target_s"]))


def build_generation_plan(config: ResolvedConfig, pick: AudioRecipe, base: AudioRecipe, generator: str, *, out: Path,
                          timeline: dict, brief: dict, brief_sources: dict, evidence: dict | None, takes: int,
                          seed: int | None, write: bool) -> tuple[dict, AudioRecipe]:
    """One candidate, ``takes`` seeds.  ``write=False`` builds the plan and the graphs in memory only (dry run)."""
    target = float(math.ceil(timeline["duration_s"]) + base.data["loop_extend"]["target_extra_s"])
    recipe = derived_recipe(pick, base, generator, brief, target)
    plan = music.build_plan(config, recipe, f"pick:{generator}", out=out, timeline=timeline, brief=brief,
                            brief_sources=brief_sources, evidence=evidence, takes=takes, seed=seed, write=write, candidates=1)
    return plan, recipe


def object_info_fetcher(settings: ComfySettings):
    client = ComfyClient(settings.base_url, timeout_seconds=15.0)

    def fetch(name: str) -> dict:
        data = client.get(f"/object_info/{name}")
        if not isinstance(data, dict) or name not in data:
            raise ComfyError(f"/object_info/{name} unknown")
        return data[name]
    return fetch


def execute(config: ResolvedConfig, out: Path, plan: dict, recipe: AudioRecipe, *, timeout_seconds: float,
            emit=lambda message: None) -> dict:
    """GPU: every job of the plan, serially, through the guarded engine path (a COMPLETED job is reused, a pending one
    resumed, none re-POSTed).  The caller has checked ``--execute``."""
    settings = settings_from_machine(config.machine)
    client = ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
    ctx = jobs.RunContext(client=client, settings=settings, policy=ClassPolicy.from_domain(config.domain), out=Path(out),
                          timeout_seconds=timeout_seconds, emit=emit)
    return jobs.run_all(ctx, plan, recipe.data, Path(config.machine["comfy"]["root"]))


def finalize_generation(config: ResolvedConfig, out: Path, plan: dict, recipe: AudioRecipe, *, ffmpeg: str, gate: Any,
                        vocal_runner, with_gui: bool = True) -> dict:
    """CPU: decode each take, loop-extend, gate every bed (``music.finalize``); the receipt names the stem."""
    settings = settings_from_machine(config.machine)
    extra: dict = {}
    if with_gui:
        extra = {"object_info": object_info_fetcher(settings), "input_dir": settings.input_dir}
    return music.finalize(Path(out), plan, recipe, output_root=settings.output_dir, ffmpeg=ffmpeg,
                          rate=recipe.data["sample_rate"], vocal_gate=gate, vocal_runner=vocal_runner, **extra)
