"""Save the editable GUI workflow and the result-pinned review GUI for every finished audio job.

Best effort by design: a missing ComfyUI (``/object_info`` unreachable) or a read-only input folder is
recorded as ``error`` in the receipt, it never fails a finalize (the API graph + receipts are the evidence).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..comfy.gui_inputs import flat_input_name, stage_graph_inputs
from ..comfy.staging import stage_input
from ..core.io import read_json, write_json_once
from . import gui
from .jobs import WORKFLOWS_DIR


def write_guis(out: Path, plan: dict, produced: dict[str, dict], object_info: Callable[[str], dict] | None,
               input_dir: Path | None, *, label: str) -> dict:
    """``produced[job_id] = {path, sha256, prompt_id}``.  Returns ``{job_id: {gui, review_gui}}`` or an error."""
    if object_info is None or input_dir is None:
        return {"skipped": "no ComfyUI object_info / input folder given"}
    rows: dict[str, dict] = {}
    try:
        for job in plan["jobs"]:
            api = read_json(Path(out) / job["graph_file"])
            title = f"{label} {job['job_id']}"
            staged = stage_graph_inputs(api, input_dir, domain=plan["domain"], shot=job["job_id"])
            editable = gui.api_to_gui(staged, object_info, title=title, extra={"graph_sha256": job["graph_sha256"]})
            gui_path = Path(out) / WORKFLOWS_DIR / f"{job['job_id']}.gui.json"
            gui_sha = write_json_once(gui_path, editable, mode="ascii")
            made = produced[job["job_id"]]
            name = flat_input_name(plan["domain"], job["job_id"], made["sha256"], Path(made["path"]).name)
            stage_input(Path(made["path"]), Path(input_dir), name, made["sha256"])
            review = gui.attach_audio_result(editable, input_name=name, status="completed", prompt_id=made["prompt_id"],
                                             audio_sha256=made["sha256"])
            review_path = Path(out) / WORKFLOWS_DIR / f"{job['job_id']}.review.gui.json"
            rows[job["job_id"]] = {"gui": f"{WORKFLOWS_DIR}/{gui_path.name}", "gui_sha256": gui_sha,
                                   "review_gui": f"{WORKFLOWS_DIR}/{review_path.name}",
                                   "review_gui_sha256": write_json_once(review_path, review, mode="ascii"),
                                   "pinned_input": name}
    except Exception as error:  # noqa: BLE001 - see module docstring
        return {"error": repr(error), "written": rows}
    return rows
