> Runtime update2026-10-19: Masterv005/job388d7b7e7956 is technically ready with12SeedVR2 7B pictures,5Mai +7softenedAlice WAVs andregistered exact-WAV ASR captions. `/films.html` and`GET /api/films` index3films andactual current/history/finishing/restorationjobs; `/api/film-media/<film>/<artifact>` verifies hash/range/ownership.95engine/caption/library/batchtests passed. Technical readiness is separate from current-hash broadcast acceptance. Thev004 notes below remain historical.

# Studio production API — verified 2026-10-18

Entry: `production-local/studio-app/server.py`; implementation: `engine.py`.
Current character-library extension: see [full prompt and expression operating contract](character-icon-library.md). Shared assets are at `J:/1.JennieHomeSchool/guilineicon/`. Header library link serves the catalog/full prompts/PNG/JSON/ZIP. Step 4 includes visible reuse instructions, stages the generated Mother/Alice/kitchen through `/api/assets/stage-library`, and `/api/characters/bind-expression` binds a hashed acting icon plus the full character description to a specific shot. Full-body canonicals remain in30/31; expression portraits supplement them in32/33. The API does not itself call an image-generation model. Current verification:56 engine and19 renderer tests. Canonical WAV feeds both temporal AddGuide and H3 standalone audio reference with explicit Picture/Audio speaker ownership tags; runtime lip/voice review remains required.
Run `python server.py` from that directory. Only one instance may own its held
`.studio.lock`. HTTP is threaded and bound to 127.0.0.1:5050. Do not restart
ComfyUI or modify the isolated VoiceStudio environment to fix a Studio defect.

Every API request carries `X-Episode-Id` or an `episode_id` query. Browser audio,
native clips, draft and Master use episode-scoped `/api/media/...` routes with
HTTP Range support. A missing Milk Master returns 404; another episode must
never serve as its substitute. State is atomic `studio-state.json`, with prior
versions in `revisions/`.

## Actual operating sequence

1. Crawl an HTTPS YouTube reference with `/api/agent-reach/crawl`. Persist actual
   extractor, metadata and transcript source. Missing subtitles stay missing.
   The ten Milk curriculum terms are curated suggestions, not extracted lyrics.
2. Edit vocabulary and dynamic shots. Keyword linking merges curriculum hits
   without discarding curated emphasis. Approve the actual storyboard before
   queueing inference.
3. Choose real `/profiles` IDs from the running VoiceStudio, then batch TTS.
   The deployed v0.5.6 `/generate` returns binary WAV with `X-Audio-Id`, not JSON.
   Keep the native WAV and a separate 48 kHz stereo derivative. Bind each take to
   exact cleaned speech, speaker, profile and SHA-256. Do not copy a bedtime take
   into every Milk shot. Pitch/speed controls are unsupported in this adapter;
   do not describe their displayed defaults as applied calibration.
4. Import real Mother/Alice references and the first shot anchor via
   `/api/assets/register`. Review imported images, then approve anchors. Select
   the shot in Studio; validate its API graph before submitting to ComfyUI.
   Export supported frontend widget/link values using installed `/object_info`.
   Never send a frontend `nodes` array as the API prompt. Require actual
   `prompt_id`, retain it, and reject unchanged duplicate pending/completed jobs.
5. Scan only outputs belonging to recorded prompt IDs. View native AV and
   accept the current file hash. `/api/anchors/carry` extracts with
   `select=eq(n\,last_used)` from the accepted **24 fps** source (119 for5s,
   143 for6s); it does not
   seek approximately to 4.95 seconds or resize the carry. Subsequent anchors
   must bind the previous accepted clip hash. Script, voice, source or anchor
   edits invalidate stale takes and downstream carries. Preserve native AV at
   sink18; explicit editorial carry at903 and exact first PNG at904. Re-scanning
   keeps review_scope/notes for the same source hash. `draft_visual` never means
   full AV approval. Verify actual decoded seam/motion separately.
6. Finish using real accepted native clips plus canonical VoiceStudio WAVs.
   `/api/render-draft` produces 720p first. Review that exact draft and submit
   its hash to `/api/draft/review` before `/api/render-master`. Renderer sources
   and commands are in `studio-app/finishing/README.md`. Caption timing supports
   `estimated` and registered `asr` modes. `POST /api/captions/timing/register`
   takes absolute `source_path` and `review_path` JSONs: one ASR/review record per
   current shot, exact cleaned text and current WAV SHA/duration, model and
   transcript/review hashes. The engine snapshots/validates evidence before
   publishing the binding. `/api/captions/timing/mode` changes mode only after
   validating its dependencies. The preservedv004 remains estimated and has no
   registered ASR binding. Neither mode certifies phonemes or lip sync. Native
   AV remains immutable. See [current evidence](../../jenniejoy-production-system/references/current-state.md).
7. A verified 1080p/30 fps/48 kHz stereo file plus current content/source hashes
   is necessary for a Master receipt. Broadcast acceptance additionally needs
   `qa/broadcast-evidence.json`, bound to the current Master/content hashes and
   hashed artifacts for all nine criteria. Never use hardcoded green passes.

GPU operations check the Comfy queue. Await VoiceStudio model unloading before
H3 submission. A Comfy `/free` response acknowledges an asynchronous request;
it does not prove that VRAM has already been released.

## HyperFrames and tutorials

Anti owns the HyperFrames installation and desktop packaging; Codex owns Studio,
UAT and Remotion, with post-handover integration fixes documented jointly.
Windows `HyperFrames.exe` is a custom .NET/WebView2 host. It is not an official
HeyGen Windows distribution. Keep the CLI patch/source and installed dependency
versions recorded. A package update may overwrite the custom `open` patch.

Studio renders a snapshot of the five-second Milk intro in a unique job folder.
This avoids the preview server's history lock and preserves the source workspace.
The verified run used HyperFrames 0.8.169, hardware browser GPU + GPU encoding,
and completed in 9.0 s. This is an intro-only artifact without audio, not a
75-second episode or a ten-word outro. Failed/unfinished jobs cannot publish a
Master. Restarted jobs require reconciliation before another render.

Tutorials share `steps.json`, PNG screenshots and Vietnamese burn-in captions,
SRT and VTT. Read/append the timeline from disk for each browser capture: a
serialized REPL closure may retain an old array/tab handle and overwrite earlier
captures. Validate the final step count and source fingerprint in both renders.
Call these screenshot-based walkthroughs, not continuous screen recordings.
Cursor v2 exports now include visible illustrative pointer movement/click rings
in both renderers,18 steps/204s/1080p15fps, full-decode exit0. Actual exported
frames were inspected. Preserve old no-cursor videos; `verified-delivery.json`
records new hashes and the shared source fingerprint. Captures predate library
controls; Step4 reuse instructions describe those current controls. Allowlisted,
episode-scoped `/api/tutorial/remotion.mp4`, `hyperframes.mp4`, `captions.srt`
and `captions.vtt` serve the files with media Range support.

WAV playback completed in Chrome for S01_A, S03_A and S06_B. The Codex in-app
browser crashed twice on starting the same WAV. Record this as a host-specific
failure with Chrome as the verified workaround; neither browser playback nor
ffprobe establishes listening or lip-sync acceptance.

## Verification

`python -m unittest -q test_engine`:47 regressions; `node --test
finishing/test_renderer.cjs`:10 tests. Native wrapper build: zero warnings/errors.
HyperFrames Milk template check after SVG/contrast fixes: zero lint/runtime/
layout/contrast errors. Live 20 concurrent API reads completed without stalling.
UI overflow checks passed at 375, 768 and 1440 px after layout stabilization.

Evidence, incident tracker, tutorial and UAT report live in
`JennieJoyKids-Story/03-drinking-milk/uat/2026-10-18/`. A technical engine pass
does not waive missing picture, character, continuity, speech or mix reviews.


## Incremental editing — current contract

See [incremental pipeline](incremental-pipeline.md) for the dependency matrix, executable APIs, cache receipts, per-shot picture/audio overrides and independent HyperFrames component cache. Native prompt changes retain their review/carry gates. Editorial translations and keywords preserve storyboard approval. Actual render evidence is recorded under the episode qa/incremental-smoke directory; source/tests alone are not media QA.
