"""Local deterministic typography and original-logo placement for wardrobe edits."""
from pathlib import Path
import math
import json

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
import torch


class NewteconsUnicodeText:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "PHÒNG\nTHIẾT BỊ"}),
            "font_size": ("INT", {"default": 64, "min": 8, "max": 512}),
            "color": ("STRING", {"default": "#ffffff"}),
        }, "optional": {
            "font": (["Arial Bold", "Tahoma Bold"], {"default": "Arial Bold"}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "render"
    CATEGORY = "NEWTECONS/branding"

    def render(self, text, font_size, color, font="Arial Bold"):
        fonts = {"Arial Bold": "arialbd.ttf", "Tahoma Bold": "tahomabd.ttf"}
        if font not in fonts:
            raise ValueError("Choose a verified local Unicode font")
        font_path = Path("C:/Windows/Fonts") / fonts[font]
        font = ImageFont.truetype(str(font_path), font_size)
        bounds = ImageDraw.Draw(Image.new("L", (1, 1))).multiline_textbbox(
            (0, 0), text, font=font, spacing=8, align="center")
        width = max(1, math.ceil(bounds[2] - bounds[0]))
        height = max(1, math.ceil(bounds[3] - bounds[1]))
        alpha = Image.new("L", (width + 8, height + 8), 0)
        ImageDraw.Draw(alpha).multiline_text(
            (4 - bounds[0], 4 - bounds[1]), text, font=font,
            fill=255, spacing=8, align="center")
        rgb = Image.new("RGB", alpha.size, ImageColor.getrgb(color))
        return (torch.from_numpy(np.array(rgb).astype(np.float32) / 255)[None],
                torch.from_numpy(np.array(alpha).astype(np.float32) / 255)[None])


class NewteconsPerspectiveComposite:
    @classmethod
    def INPUT_TYPES(cls):
        fields = {"destination": ("IMAGE",), "source": ("IMAGE",), "mask": ("MASK",)}
        for name, value in zip(("x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4"),
                               (0, 0, 100, 0, 100, 100, 0, 100)):
            fields[name] = ("FLOAT", {"default": value, "min": -16384, "max": 16384})
        return {"required": fields}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "composite"
    CATEGORY = "NEWTECONS/branding"

    def composite(self, destination, source, mask, x1, y1, x2, y2, x3, y3, x4, y4):
        count, height, width, channels = destination.shape
        if channels != 3 or source.shape[-1] != 3:
            raise ValueError("Brand compositing requires RGB images")
        if source.shape[0] not in (1, count) or mask.shape[0] not in (1, count):
            raise ValueError("Source and mask batches must be one or match destination")
        if tuple(source.shape[1:3]) != tuple(mask.shape[1:3]):
            raise ValueError("Source and mask dimensions must match")
        sh, sw = source.shape[1:3]
        target_quad = [(x1, y1), (x2, y2), (x3, y3), (x4, y4)]
        points = np.asarray(target_quad, dtype=np.float64)
        if not np.isfinite(points).all():
            raise ValueError("Brand corners must be finite coordinates")
        edges = np.roll(points, -1, axis=0) - points
        turns = edges[:, 0]*np.roll(edges[:, 1], -1) - edges[:, 1]*np.roll(edges[:, 0], -1)
        if not (np.all(turns > 1e-9) or np.all(turns < -1e-9)):
            raise ValueError("Brand corners must form a convex quadrilateral in perimeter order")
        source_quad = [(0, 0), (sw, 0), (sw, sh), (0, sh)]
        matrix, values = [], []
        for (x, y), (u, v) in zip(target_quad, source_quad):
            matrix.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y],
                           [0, 0, 0, x, y, 1, -v*x, -v*y]])
            values.extend([u, v])
        try:
            coefficients = np.linalg.solve(np.asarray(matrix, dtype=np.float64), values)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Brand corners do not define a valid perspective transform") from exc
        result = destination.clone()
        for index in range(count):
            rgb = (source[min(index, source.shape[0]-1)].detach().cpu().numpy().clip(0, 1)*255).round().astype(np.uint8)
            alpha = (mask[min(index, mask.shape[0]-1)].detach().cpu().numpy().clip(0, 1)*255).round().astype(np.uint8)
            rgba = Image.fromarray(np.dstack([rgb, alpha]))
            warped = rgba.transform((width, height), Image.Transform.PERSPECTIVE,
                                    coefficients, Image.Resampling.BICUBIC)
            layer = torch.from_numpy(np.asarray(warped).copy()).to(destination.device, destination.dtype) / 255
            opacity = layer[..., 3:4]
            result[index] = destination[index]*(1-opacity) + layer[..., :3]*opacity
        return (result,)


class NewteconsLocalMarkRemoval:
    """Remove bounded mark pixels using neighboring cloth, without a replacement panel."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "regions_json": ("STRING", {"multiline": True, "default": "[]"}),
        }}

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove"
    CATEGORY = "NEWTECONS/branding"

    def remove(self, image, regions_json):
        from scipy.ndimage import binary_dilation, distance_transform_edt, gaussian_filter

        regions = json.loads(regions_json)
        if not isinstance(regions, list) or not regions:
            raise ValueError("Provide at least one explicitly bounded mark region")
        count, height, width, channels = image.shape
        if channels != 3:
            raise ValueError("Mark removal requires RGB")
        result = image.clone()
        masks = np.zeros((count, height, width), dtype=np.float32)
        for region in regions:
            x, y, w, h = [region[key] for key in ("x", "y", "width", "height")]
            if any(type(value) is not int for value in (x, y, w, h)):
                raise ValueError("Region coordinates must be integers")
            if min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
                raise ValueError("Mark region is outside the image")
            mode = region.get("mode", "bright")
            threshold = region.get("threshold", 0.55)
            grow = region.get("grow", 2)
            if (mode not in ("bright", "colored_on_white", "dark", "rectangle")
                    or not isinstance(threshold, (int, float)) or not math.isfinite(threshold)
                    or not 0 < threshold < 1 or type(grow) is not int or not 0 <= grow <= 8):
                raise ValueError("Invalid removal mode, threshold, or growth")
            # Include external context for a region filled completely, but never edit outside its bounds.
            pad = 12
            left, top = max(0, x-pad), max(0, y-pad)
            right, bottom = min(width, x+w+pad), min(height, y+h+pad)
            for index in range(count):
                pixels = result[index, top:bottom, left:right].detach().cpu().numpy().copy()
                roi = pixels[y-top:y-top+h, x-left:x-left+w]
                if mode == "bright":
                    marks = roi.min(axis=-1) > threshold
                elif mode == "colored_on_white":
                    marks = ((roi.max(axis=-1) - roi.min(axis=-1)) > threshold) | (roi.mean(axis=-1) < 0.55)
                elif mode == "dark":
                    marks = roi.max(axis=-1) < threshold
                else:
                    marks = np.ones((h, w), dtype=bool)
                if grow:
                    marks = binary_dilation(marks, iterations=grow)
                mask = np.zeros(pixels.shape[:2], dtype=bool)
                mask[y-top:y-top+h, x-left:x-left+w] = marks
                if not mask.any():
                    continue
                if mask.all():
                    raise ValueError("Mark region leaves no context for local reconstruction")
                _, nearest = distance_transform_edt(mask, return_indices=True)
                reconstructed = pixels.copy()
                reconstructed[mask] = pixels[nearest[0][mask], nearest[1][mask]]
                for _ in range(24):
                    smoothed = gaussian_filter(reconstructed, sigma=(0.65, 0.65, 0))
                    reconstructed[mask] = smoothed[mask]
                tensor = torch.from_numpy(reconstructed).to(image.device, image.dtype)
                result[index, top:bottom, left:right] = tensor
                masks[index, top:bottom, left:right][mask] = 1
        return result, torch.from_numpy(masks).to(image.device, image.dtype)


NODE_CLASS_MAPPINGS = {
    "NewteconsUnicodeText": NewteconsUnicodeText,
    "NewteconsPerspectiveComposite": NewteconsPerspectiveComposite,
    "NewteconsLocalMarkRemoval": NewteconsLocalMarkRemoval,
}
