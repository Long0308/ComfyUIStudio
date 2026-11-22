# Workshop AI assembly preview

Open `index.html` for the independently composed 1920×1080 landscape preview or
`portrait.html` for the 1080×1920 portrait preview. Both play a 20 second, 30 fps
timeline and include seek, pause and restart. HTML works from a local folder;
all artwork references are relative to this kit. The player is silent.

`renderFrame(frame)` is the public capture contract. It accepts integer frames
0–599, clamps out of range requests and calculates the complete SVG stage from
that frame alone. The playback clock only chooses frames. Capture does not use
playback, elapsed wall time, unseeded randomness, CSS animations or physics.

Seven scenes: hero 0–2s; engineers 2–5s; mechanical assembly 5–8s; illustrative
dashboard 8–11s; AI × BIM 11–13s; responsible AI 13–16s; event card 16–20s.
The original planning manifest uses 60 fps; multiply these preview frame numbers
by two when comparing with its master timing.

The mechanical assembly contains six independent, editable SVG parts. They
arrive from separate offsets, align, settle, lock and briefly activate. These
are native isometric vector illustrations, not extracted Revit geometry. Source
photographs and dashboards remain flat images with position/scale changes only.
Typography uses the outlined SVG assets bound in `text-content.json`, preserving
Vietnamese marks and avoiding installed-font dependencies. Portrait uses whole
phrases at compact width, with no slicing of glyphs.

Rebuild locally with Node.js, installed Chrome, FFmpeg and FFprobe:

```powershell
node animation/build-assets.cjs
node animation/build-content.cjs
node animation/render.cjs assets
node animation/verify-assets.cjs
node animation/render.cjs video
ffprobe -v error -show_streams -show_format -of json exports/workshop-ai-intro-1080p.mp4
```

`WORKSHOP_CHROME` can specify a different installed Chrome executable. The
renderer creates its own local HTTP server and temporary Chrome profile, uses
the Chrome DevTools Protocol directly, seeks each integer frame and passes the
PNG sequence to FFmpeg. It refuses to encode if any sampled required image fails
to load. It writes landscape samples, portrait samples and seek-order hashes to
`exports/` and `evidence/motion-preview-render.json`.

Export: `exports/workshop-ai-intro-1080p.mp4`. This is a first-stage 1080p motion
proof. It does not establish a live AI/Revit connection, native 4K detail,
independently confirmed event scheduling, or licensed music rights.
