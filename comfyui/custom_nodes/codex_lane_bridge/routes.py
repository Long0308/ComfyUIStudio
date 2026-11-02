"""Same-origin proxy routes on the ComfyUI server so a UI panel can reach the bridge WITHOUT holding the secret.

The secret is read server-side (client.read_secret) and never sent to the browser.  Only these are proxied:
GET /codex_lane/health, GET /codex_lane/jobs/{job_id}, POST /codex_lane/video/shot.  A GPU video step still needs the
user's own `gpu_approved` value in the body: the engine refuses GPU work without it.
"""
from __future__ import annotations

import asyncio
import re

from aiohttp import web

from . import client

JOB_ID = re.compile(r"[a-z]{2}[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}")


async def _bridge(method: str, path: str, body: dict | None = None) -> web.Response:
    def work():
        return client.call(method, path, client.read_secret(), body)

    try:
        return web.json_response(await asyncio.get_running_loop().run_in_executor(None, work))
    except client.BridgeError as error:
        status = 409 if "HTTP 409" in str(error) else (400 if "HTTP 400" in str(error) else 502)
        return web.json_response({"ok": False, "error": str(error)}, status=status)


def register(routes) -> None:
    @routes.get("/codex_lane/health")
    async def health(request):
        return await _bridge("GET", "/v1/health")

    @routes.get("/codex_lane/jobs/{job_id}")
    async def job(request):
        job_id = request.match_info["job_id"]
        if not JOB_ID.fullmatch(job_id):
            return web.json_response({"ok": False, "error": "not a bridge job id"}, status=400)
        return await _bridge("GET", f"/v1/jobs/{job_id}")

    @routes.post("/codex_lane/video/shot")
    async def video(request):
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "body is not JSON"}, status=400)
        return await _bridge("POST", "/v1/video/shot", body if isinstance(body, dict) else None)
