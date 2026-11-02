"""Pillow helpers (CPU only, lazily imported: a missing Pillow is ``Uncertain`` with a clear message)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain


def pil() -> Any:
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - environment dependent
        raise Uncertain("Pillow is required for image sheets (pip install pillow)") from error
    return Image


def load_rgb(path: Path) -> Any:
    image = pil().open(path)
    image.load()
    return image.convert("RGB")


def fit_height(image: Any, height: int) -> Any:
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), pil().Resampling.LANCZOS)


def cast_sheet(paths: list[Path], dest: Path, height: int = 768) -> dict[str, Any]:
    """One side-by-side reference sheet of the cast images (the edit nodes take two images: scene + this sheet).

    The sheet is a DERIVED file: the receipt keeps its sha256 and the source list."""
    if not paths:
        raise Refused("cast_sheet needs at least one reference image")
    tiles = [fit_height(load_rgb(p), height) for p in paths]
    sheet = pil().new("RGB", (sum(t.width for t in tiles), height), (255, 255, 255))
    x = 0
    for tile in tiles:
        sheet.paste(tile, (x, 0))
        x += tile.width
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, format="PNG")
    return {"path": Path(dest).resolve().as_posix(), "width": sheet.width, "height": sheet.height,
            "sources": [Path(p).resolve().as_posix() for p in paths]}


def native_copy(source: Path, dest: Path, width: int, height: int, *, tolerance: float, center_crop: bool) -> dict[str, Any]:
    """``source`` resized to ``width x height`` (Lanczos). A source whose aspect ratio differs by more than
    ``tolerance`` is refused unless ``center_crop`` says to crop it to the target aspect first (recorded)."""
    image = load_rgb(source)
    target, have = width / height, image.width / image.height
    cropped = None
    if abs(have - target) / target > tolerance:
        if not center_crop:
            raise Refused(f"source aspect {have:.4f} differs from {target:.4f} by more than {tolerance}; "
                          "pass --center-crop to crop it to the native aspect first (recorded in the receipt)")
        new_w = min(image.width, round(image.height * target))
        new_h = min(image.height, round(image.width / target))
        left, top = (image.width - new_w) // 2, (image.height - new_h) // 2
        image = image.crop((left, top, left + new_w, top + new_h))
        cropped = {"box": [left, top, left + new_w, top + new_h]}
    resized = image.resize((width, height), pil().Resampling.LANCZOS)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    resized.save(dest, format="PNG")
    return {"width": width, "height": height, "resample": "lanczos", "source_aspect": round(have, 5),
            "aspect_stretch_pct": round(abs(have - target) / target * 100, 3) if cropped is None else 0.0, "crop": cropped}
