"""Selectable local project controls. No render is queued on import."""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

# Do not conceal a broken route registration on an actual ComfyUI installation.
try:
    from server import PromptServer
except ModuleNotFoundError as exc:
    if exc.name != "server":
        raise
else:
    from .routes import register
    register(PromptServer.instance.routes)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
