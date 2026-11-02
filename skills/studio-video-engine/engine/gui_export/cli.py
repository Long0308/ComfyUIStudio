"""CLI glue: GET-only node discovery, then a local copy/export. Never POST."""
from pathlib import Path
from urllib.parse import quote

from ..comfy.client import ComfyClient
from ..core.errors import Refused
from .export import export_gui


def register(verbs, kind):
    command = verbs.add_parser("export-gui", help="export one approved, prepared shot to the ComfyUI workflow browser (CPU only)")
    command.add_argument("--episode", required=True)
    command.add_argument("--out", required=True, help="export receipts/steplog folder inside this episode")
    command.add_argument("--prepared", required=True, help="video: H3 parent of SHOT/preparation.json; image: local prepared take folder")
    command.add_argument("--shot", required=True)
    command.add_argument("--tier", choices=("preview",), default="preview")
    command.add_argument("--machine", default=None)
    if kind == "image":
        command.add_argument("--anchor-pack", required=True, help="approved shot pack whose exact guide/reference inputs the local graph uses")
        command.add_argument("--prompt-batch", default=None, help="current confirmed prompt batch; required where the image domain requires provenance")
    command.set_defaults(gui_export_kind=kind)


def run(ctx, args):
    if args.gui_export_kind == "video":
        from .video import load_video
        prepared = load_video(ctx, Path(args.prepared), args.shot, args.tier)
    else:
        from .images import load_images
        prepared = load_images(ctx, Path(args.prepared), args.shot, args.tier, anchor_pack=Path(args.anchor_pack),
                               prompt_batch=Path(args.prompt_batch) if args.prompt_batch else None)
    client = ComfyClient(ctx.machine["comfy"]["url"].rstrip("/"))
    cache = {}

    def info(name):
        if name not in cache:
            response = client.get("/object_info/" + quote(name, safe=""))
            value = response.get(name) if isinstance(response, dict) else None
            if not isinstance(value, dict):
                raise Refused(f"GUI_NODE: {name} is missing from the configured ComfyUI")
            cache[name] = value
        return cache[name]

    return export_gui(ctx, prepared, kind=args.gui_export_kind, out=Path(args.out), object_info=info)
