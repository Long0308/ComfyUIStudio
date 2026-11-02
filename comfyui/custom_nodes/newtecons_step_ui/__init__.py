"""
NEWTECONS Step UI — frontend-only ComfyUI extension (no nodes, no server routes).

Serves web/step_ui.js: a dark numbered step tab bar over the canvas for NEWTECONS
workflows (graph.extra has a 'newtecons_*' key; JennieJoy graphs are ignored). Clicking a
step zooms the canvas to that group and opens a VÀO/RA panel: the group's input image
(LoadImage value via GET /view) and its latest output (GET /history + /view). It never
queues a prompt and never POSTs. Engine (Codex OAuth) thumbnails come from a static
manifest written on the host by tools/comfy_layout/step_ui_assets.py.

v004 workflows (graph.extra.newtecons_route_plan): tab "00 CHỌN LUỒNG" (LOCAL vs CODEX LAN GPT)
and tab "09 DUYỆT & UPSCALE" (source + 1080/2K/4K target) apply that plan to the canvas graph
only — node modes and ComfySwitchNode values, like Ctrl+M — and tab 09 copies the engine
command `jjv images approve ... --sha <sha>`; approvals are written by the engine, not here.
"""

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

from server import PromptServer
from .step_routes import register_routes
register_routes(PromptServer.instance.routes)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
