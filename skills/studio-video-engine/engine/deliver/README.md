# Delivery adapters (M5)

CPU only. Register `engine.deliver.cli.register_cli(stages)` and dispatch
`deliver`, `brand`, `publish` to `run_delivery(args)` (shared CLI wiring is supplied separately).
Before registration the same parsers run with `python -m engine.deliver.cli …`.

```
jjv deliver film-2k --episode E --master master.mp4
jjv brand title --episode E
jjv brand join --episode E
jjv publish studio --episode E --dry-run
jjv publish studio --episode E --publish
```

Every verb accepts `--delivery-config FILE`, `--repo-root DIR`, `--out DIR`.
Defaults: `<episode>/engine/delivery.json`, normal engine repository root, output from
the selected config block. Paths in delivery.json are relative to its directory,
while command-line `--out`, `--master` and brand input overrides use the caller's cwd.
Episode paths/roots/slugs use the existing config loader's resolver. This adapter reads
the episode identity and domain delivery policy only: no voice/restoration job is loaded or submitted.
Malformed or missing JSON is uncertain (exit 2), failed guards exit 1.

The separate delivery sidecar avoids changing the episode schema owned by the config milestone.
It must repeat the episode id and domain exactly. Engine code contains no film/domain/machine paths.

Example (all machine, title, asset and library values must be supplied by the caller):

```json
{
  "schema": "jjv/delivery-config/v1",
  "episode_id": "example",
  "domain": "your-configured-domain",
  "film_2k": {"out": "../delivery/v001/2k"},
  "brand": {
    "kit": "/path/to/brand-kit",
    "workspace": "/path/to/workspace",
    "packages": "/path/to/node_modules",
    "browser": "/path/to/chrome-headless-shell",
    "props": {
      "titleEn": "Example episode title",
      "titleVi": "Vietnamese episode title",
      "subtitle": "Episode subtitle",
      "brandLine": "BRAND",
      "background": "episode-background.png",
      "logo": "brand-logo.png"
    },
    "chime": "/path/to/optional-chime.wav",
    "target_lufs": -20,
    "intro": "/path/to/reusable-intro.mp4",
    "title": "../delivery/v001/title/title.mp4",
    "film": "../delivery/v001/film-without-brand-voice.mp4",
    "title_out": "../delivery/v001/title",
    "join_out": "../delivery/v001/join"
  },
  "publish": {
    "library": "/path/to/film-library.json",
    "studio_url": "http://127.0.0.1:5050",
    "out": "../delivery/v001/publication",
    "artifacts": [{
      "path": "../delivery/v001/2k/film-2k.mp4",
      "sha256": "64 lowercase hex characters, from the actual artifact",
      "receipt": "../delivery/v001/2k/receipt.json",
      "role": "film_2k",
      "version": "v001",
      "provenance": "Description supported by the receipt",
      "review_status": "CANDIDATE"
    }]
  }
}
```

`brand.props.titleEn` must equal episode.title. All six text/art props are required so
the kit's example defaults never supply another episode's title or background. The kit
provides `src/index.jsx` with `EpisodeTitle`, `public/`, and tools `build_segment_audio.py`,
`mux_segment.py`, `join_intro_v001.py`. Python needs numpy for those existing tools.
The rendering adapter reuses the kit compositions, uses the existing renderer's CPU
SwiftShader settings and JSX conversion, injects package/browser/temp locations and stores
its bundle under the output directory. No writes into the kit. No new audio-mixing or
AAC-concat algorithm is implemented. Without `chime`, the title has intentional silence.

Outputs are version directories: an existing directory is refused; failed files/receipts
remain for diagnosis. A verified technical receipt does **not** assert human acceptance.
Title runtime is recorded in seconds; the earlier ~20 s number is a target, not a guarantee.
The supplied kit is 4K/30 fps; its title length is derived from the actual render and must
be divisible by 16 frames for the legacy join's AAC alignment. Join also requires silent
head audio edges; incompatible streams may cause the legacy tool to rematch only the head.
Film video is never encoded by the join. That tool's audio policy encodes intro+title
audio once and copies film AAC packets; "lossless join" refers to video and film AAC,
not to bit-identical PCM across AAC decoder states.

2K requires a domain-declared 2560x1440 Lanczos delivery and an actual master-size input
with its declared fps and one audio track. It uses libx264 medium CRF 18, yuv420p, passthrough
frames and `-c:a copy`. Receipt contains input/output SHA256, decoded frame counts, fps,
copied-audio MD5 and every command/exit/time. Join stores full framemd5 files for each
used segment and the output, verifies the complete sequence, and checks full-range luma
on seven frames centered at title→film; any frame with every luma sample >=250 is refused.
Intro→title white transitions are outside that gate.

Publish defaults to a write-free plan: exact proposed rows, existing ids and new_count,
with no HTTP access. Content ids are sha256[:20]; collisions with any different requested row field
refuse. Artifact SHA must equal the config pin and appear in a structured `sha256` or
`output_sha256` field in its receipt. For legacy rows whose historical receipt omitted
an output, an explicit `binding_receipt` may supply a separate hash inventory while the
library keeps its original `receipt` pointer. Such an inventory is evidence of bytes,
not evidence of approval. Existing rows/films/metadata are retained. New films are appended
when absent; existing film metadata is never refreshed. There is no update/delete API.

`--publish` takes an OS publication lock, rechecks source hashes, backs up the exact library
bytes, records an intent, appends new rows via atomic replacement, records the resulting
library hash, GETs `/api/films?episode_id=…`, verifies every requested row field plus exists for every
configured row, and writes receipt.json. URLs must use literal 127.0.0.1; redirects and
environment proxies are disabled. Readback failure after write returns uncertain (exit 2),
leaves the additive write and evidence intact; rerun a dry plan/readback after investigating.
An already-published run keeps library bytes unchanged. Writers ignoring this adapter's
lock can still race after the final compare; Studio integration should share the lock.

Synthetic tests take explicit filesystem inputs:

```
python -m pytest tests/m5 -q -p no:cacheprovider --basetemp TEMP \
  --brand-kit KIT --media-workdir MEDIA
node --check engine/deliver/render_title.cjs
node --check engine/deliver/jsx_loader.cjs
```

`--media-workdir` injects fixture storage for ffmpeg and fake HTTP tests; it is not an
engine override. This avoids private temp directory ACLs that prevent child processes
from opening fixtures in some Windows test hosts. No production paths are embedded in tests.
