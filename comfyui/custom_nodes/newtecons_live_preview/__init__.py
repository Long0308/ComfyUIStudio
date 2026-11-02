"""
Newtecons Live Preview Extension for ComfyUI.
Serves web/live_preview.js to restore and synchronize live API execution previews
on the active canvas without reloading graphs or mutating inputs.
"""

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
