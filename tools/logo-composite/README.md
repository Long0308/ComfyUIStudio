# NEWTECONS Logo Composite Tool v001

Deterministic CPU-only perspective compositor for still images. It uses the versioned helmet, vest and collar artwork already in `docs/media-stage`; it does not synthesize or redraw logos. The vest back uses the centered white NEWTECONS lockup shown in the `site_male/back.png` canon render.

## Run

Requires Python, OpenCV and NumPy. Run from the workspace root:

```powershell
python docs/media-stage/LOGO-COMPOSITE-TOOL-V001/logo_composite.py `
  --image path\to\input.png `
  --spec path\to\spec.json `
  --out path\to\output.png
```

Each item has `kind` (`helmet`, `vest_chest`, `vest_back`, or `collar`), a `quad` of four `[x,y]` pixel points ordered top-left, top-right, bottom-right, bottom-left, `curvature` in radians, and `size_scale` relative to that quad. Curvature bends the artwork around a cylindrical surface. `size_scale` uniformly scales around the quad center.

The output and adjacent `<output>.receipt.json` are created exclusively; either existing path causes a refusal. The receipt records the source, spec, output and logo asset hashes, each item bbox, and the changed-pixel guard. Any changed pixel outside the union of item bboxes causes an assertion failure. Same source, spec, assets and tool version give byte-identical pixels.

## Demo

`spec-S07_A_IMAGEGEN2_c03.json` covers all three visible helmets and all three visible vests in the referenced still. Chest marks use the canon wearer-left chest position, which appears on the viewer-right side of each vest in a front view. The tool output remains an unapproved visual candidate.
