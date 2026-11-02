> MERGED into SKILL.md 2026-10-28
## Ending as its own segment, joined after the main film (T-E42 addendum; foundation of T-E45 P2) — for root to merge into SKILL.md

Principle: the ending (logo disc, logo hold, vocabulary cards, end plate, EndLogo) is a **compositing-only** part of the film. It is rendered
on its own, as SILENT closed-GOP video, and joined after the main segment by **stream copy**; the audio is one mix that is never cut at the
join. Changing the logo hold, a card, the plate text or the end card therefore re-renders only the ending segment, and the ending never
decodes a shot video, so in the 4K master it does not wait for any restored core.

### Commands (all in `remotion-kit/`, CPU only)

```
node render.cjs --config C --segments-plan                         # the plan: [{id, kind, start, end_exclusive, frames, shot_video_frames}], plan sha256
node render.cjs --config C --mode review|master --segment main   --out main.mp4
node render.cjs --config C --mode review|master --segment ending --out ending.mp4   # stages NO shot video
node render.cjs --config C --mode review|master --audio-only --out mix.wav          # whole-film audio, 48 kHz, once
node tools/join-segments.cjs --segments main.mp4,ending.mp4 --audio mix.wav --out film.mp4 [--overwrite]
node render.cjs --config C --segment ending --within A-B --png-seq DIR             # a few frames of a segment as PNG (pixel-parity check)
```

### Decisions

* **The plan.** Segments cover `[0, total)` exactly (no gap, no overlap). Without declared `config.segments`: a config with an iris ending is
  cut into `main` and `ending`; any other config is the single segment `main` (no join). `config.segments` (`[{id, kind, start, end_exclusive}]`)
  declares explicit cuts; it is refused when it does not cover the film, repeats an id, has an empty segment, or cuts inside an iris, dip or
  both-pictures window (one effect belongs to one segment). The plan carries a sha256 of its cut list.
* **(c) Iris continuity: the MAIN segment owns the iris.** The iris is a mask over the last shot's picture, so it depends on shot video; the
  ending would otherwise need that shot's frames. The cut is the **first frame after which no shot video is mounted**, computed with the
  compositor's own `pictureMode` and tail windows (not from a number written in the config): for the iris that is `ending.discIn + 3`
  (the iris does not close to nothing: a circle of `irisEndRadius` stays until the logo disc is opaque, then the picture is the backdrop).
  The ending starts on the opaque disc over the backdrop. first-episode derived timeline: main f0-2144 (2145 f), ending f2145-3299 (1155 f), join frame 2145.
  The alternative (the ending owns the iris) was rejected: the ending would need the last shot's picture frames, so a logo-hold or card change
  would decode that clip again, and a 4K master ending would wait for that shot's restored core.
* **(a) Join.** One codec parameter set for every segment: h264 `yuv420p`, crf 18 (review) / 16 (master), `colorSpace bt709` (tags
  `bt709/bt709/bt709`, range tv), 30 fps, `-x264-params open-gop=0`, no audio. MEASURED with Remotion 4.0.536: the encode is Remotion's
  `pre-stitcher` step (libx264; the `stitcher` step only stream-copies), and the default libx264 output already joins framemd5-identical
  (closed GOP is the default, B-frames stay inside a file); `open-gop=0` is passed so the property does not depend on a default. The join
  (`ffmpeg -f concat -c:v copy`, `bitexact`) writes `<film>.join-record.json` with the proof and refuses the film unless:
  every segment still has the sha256 and framemd5 list of its render record (a flipped byte is refused); the records belong to one plan
  and are contiguous in the given order; width/height/fps/pix_fmt/codec/profile/level/time_base/colour tags are identical; the film's
  framemd5 md5 column equals the concatenation of the segments' columns element by element (not the whole rows: pts restarts per segment);
  pts runs 0..N-1 and the first frame of each segment sits at the frames before it; `nb_read_frames == total`; the film decodes with no
  error. Result on the first episode: 3300 frames, `H_film == H_seg` 3300/3300, pts continuous, decode clean.
* **(b) Audio.** The audio is one mix, never cut at a join: `--audio-only` renders the whole film audio once (`codec wav`, 48 kHz);
  48000 / 30 = 1600 samples per frame, so a join at frame J is sample J x 1600 (first episode: frame 2145, sample 3432000). The join encodes it once
  to AAC 192k after the join; music bed and ambience simply continue (the music-bed loop crossfade is part of that one mix). The record states
  `audio_join: {policy: 'single timeline mix, not cut at the join', join_frame, join_sample, samples_per_frame, mix_sha256,
  pcm_of_film_vs_mix_slack_samples}`; the join refuses a mix that is not 48 kHz or differs from the film length by more than one frame
  (first episode: mix 5280016 samples, decoded film 5280016, slack 0).
* **(d) Determinism.** `ending.mp4` rendered twice in separate runs has the same sha256 (`f307a77a...`), and joining either with the same main
  and mix gives the same film sha256 (`6681b2d8...`). A re-render of the ending alone reproduces the joined film byte for byte.
* **Pixel parity (e).** A segment frame is the same compositor frame as the film's: PNG bytes (rgba) of f2144 (main), f2145, f2146, f2147,
  f2700 and f3299 (ending) from `--segment ... --within --png-seq` equal the same frames of `--png-seq` on the full film.
* **Records.** A segment record carries `segment {id, kind, start, end_exclusive, frames, plan_sha256, plan_total, uses_shot_video}`,
  `codec`, `framemd5` (the md5 column) and its digest, `silent: true`, and the existing `shot_sources`. `uses_shot_video` is derived from the
  staged sources: the first-episode ending stages 0 picture clips and 0 tail clips (the main segment stages 14 and 3). Its `shot_sources` still lists
  the 12 dialogue WAVs, which are staged (audio and images are always staged) but not played in a silent render.

### Limits

* `--audio-only` stages every source like a full render (the compositor mounts all shots to collect the audio assets), so it is not cheaper
  than a full render in staging; it is cheap in CPU (no screenshot): the first episode about 90 s.
* The first episode's review clips carry an audible audio track (mean about -19 dB, measured on three of its shots and one tail). The compositor's
  `<Video>` plays it in a full render, and `--audio-only` includes it identically (f100-219 of the full render vs the same samples of
  `mix.wav`: difference -43 dB below the signal at lag 0, i.e. AAC noise only), while a silent segment carries no audio. So the mix, not the
  segments, is the only place audio exists. Whether that clip audio (next to the dialogue WAV) is wanted in the film is an existing-behaviour
  question, not changed here (v008 parity is untouched).
* `config.segments` cuts are validated against transition windows only; they are not yet used by the planner (T-E45 P1) and a segment cache
  (`inputs_slice_sha256`) is the next step (P2 proper).
