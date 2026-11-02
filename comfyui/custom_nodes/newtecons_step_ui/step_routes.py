"""ComfyUI container routes: enqueue NEWTECONS jobs to the host-mounted input folder.

No jjv import, subprocess, GPU call, or shell execution occurs inside ComfyUI.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from aiohttp import web

from .step_job_contract import RequestError, validate_request

JOB_ROOT = Path("/opt/ComfyUI/input/newtecons-step-jobs")
ID_RE = re.compile(r"^[a-f0-9]{32}$")


def register_routes(routes) -> None:
    @routes.post("/newtecons/step/run")
    async def step_run(request):
        try:
            body = await request.json()
            clean = validate_request(body)
        except (web.HTTPException, json.JSONDecodeError, RequestError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        JOB_ROOT.mkdir(parents=True, exist_ok=True)
        job_id = __import__("secrets").token_hex(16)
        record = {"schema": "newtecons/step-job/v1", "job_id": job_id,
                  "request": clean, "created_at": int(time.time())}
        tmp = JOB_ROOT / f".{job_id}.request.tmp"
        final = JOB_ROOT / f"{job_id}.request.json"
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(final)
        return web.json_response({"ok": True, "job_id": job_id, "status": "QUEUED",
                                  "status_url": f"/newtecons/step/run/{job_id}"}, status=202)

    @routes.get("/newtecons/step/run/{job_id}")
    async def step_status(request):
        job_id = request.match_info["job_id"]
        if not ID_RE.fullmatch(job_id):
            return web.json_response({"ok": False, "error": "invalid job id"}, status=400)
        path = JOB_ROOT / f"{job_id}.result.json"
        if not path.is_file():
            return web.json_response({"ok": True, "job_id": job_id, "status": "QUEUED"})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return web.json_response({"ok": False, "job_id": job_id, "status": "UNCERTAIN",
                                      "error": "host result is unreadable"}, status=503)
        return web.json_response(data)

    @routes.get("/newtecons/step/artifact/{job_id}/{index}")
    async def step_artifact(request):
        job_id, index = request.match_info["job_id"], request.match_info["index"]
        if not ID_RE.fullmatch(job_id) or index != "0":
            return web.json_response({"ok": False, "error": "invalid artifact key"}, status=400)
        path = JOB_ROOT / f"{job_id}.preview.mp4"
        if not path.is_file():
            return web.json_response({"ok": False, "error": "video preview unavailable"}, status=404)
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})
