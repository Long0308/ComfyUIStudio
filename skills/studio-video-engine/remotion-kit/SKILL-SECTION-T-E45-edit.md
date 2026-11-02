> MERGED into SKILL.md 2026-10-28
## One-command edits: `jjv edit review-render | master-render` (T-E45 edit path, audit gap 4) - for root to merge into SKILL.md

**Principle.** An edit to a caption word, an effect, an icon, a card, the ending or the music is a change to the COMPOSITING layer. The film is the
stream-copy join of cached, silent, closed-GOP segments plus one audio mix, each with a node key over exactly the inputs it can depend on; an edit stales
the segments whose key changed and nothing else, and never a shot video (H3 / SeedVR2 are never asked again). One command takes the edited engine inputs to
the film:

```
jjv edit review-render --cache C --out film.mp4 --episode-root R --episode E/engine/episode.json --boundaries B --word-timing W --episode-text T [--explain]
jjv edit master-render --cache C --out film.mp4 --master-config KITMASTER.json (--segments-file S | the engine inputs)  [--explain]
```
(`engine/editorial/CLI-PATCH-edit.md` has the two wiring lines for `bin/jjv.py`; until then `node remotion-kit/tools/edit-render.cjs ...` is the same command.)
`--explain` prints which segments are stale and the changed leaf (`slice changed: shot:<id>.words.0.startF`) and renders nothing. Exit 0 built, 1 refused
(a corrupt cache entry, a binding whose hash changed, a join whose framemd5 differs, a step failed), 2 usage.

### What changed to make an edit cheap (all measured on the first episode's derived 3374-frame build, 1080p, CPU, concurrency 2)

| change | why it matters |
|---|---|
| ONE staging, ONE bundle, ONE browser for the whole build (`lib/inproc.cjs`; `--build-mode children` keeps the old one-render.cjs-per-segment path) | each child paid staging + webpack bundle + browser launch + composition select (~10 s fixed) per segment; the stale segments now share one of each. Same bytes: the in-process and child builds produce byte-identical segments and film (tests R15-B1) |
| audio slice = exactly what the mix reads (`lib/segdeps.cjs audioSlice`) | every clip is `<OffthreadVideo muted>`: no picture, tail or transition row is audio. A clip with a loud audio track leaves the mix PCM byte-identical (test R15-A3). Word timing is audio only when a music bed policy exists. Property test over every config leaf + two killed mutants |
| `shots[].onsetEvidence` / `speechOnsetF` are validator-only (`SHOT_VALIDATOR_ONLY_KEYS`) | a new word-timing document relabels EVERY shot; the first measurement staled 23 of 49 segments for one moved word. Now exactly the shot whose words moved (R15-V1 / V2) |
| fast join (`tools/join-segments.cjs`, `fast`) | segments are attested by their sha256 and their recorded frame hashes (not decoded again); the film is decoded ONCE and that single decode is the framemd5 proof, the frame count and the decoder-clean check. `H_film == H_seg` is still computed from the film, so a lying record is caught (R15-J3) |
| verified-hash cache (`lib/hashcache.cjs`, `CACHE/segments/hash-cache.json`) | the sha256 of a file is remembered under {path, size, mtime ns, inode}; an unchanged file costs a stat. `--rehash-all` is the audit path; `--no-hash-cache` switches it off. The probe (`ffprobe -count_packets`) of a clip is remembered under the clip's sha256 |
| staging reads each file once (`copyHashed`: copy and digest in one pass; with the cache and `--workdir` on the same volume, hard-link instead of copy) | was: hash the source, copy it, hash the copy |
| run record: `composite_only` | the build says whether any shot source (picture / tail / dialogue WAV sha) changed since the previous build in this cache: `composite-only: no shot source changed vs the previous build (27 sources compared)`, or which changed |

### Measured (first episode, derived timeline 3374 f, 49 segments; the same machine, CPU, concurrency 2)

| run | segments rendered | wall |
|---|---:|---:|
| cold build, in-process | 49 of 49 | **243 s** (render 229 s: segments 162, audio mix 45, frame hashes 14; join 12.6 s) |
| cold build, children (old path, same conditions) | 49 of 49 | **497 s** (the same film, byte for byte) |
| ONE word moved (first word of one dialogue shot, startF +2, new word-timing document -> build-config -> adapter -> build), in-process | **1** (the shot's own segment, 160 f) | **27.9 s** (build-config 0.6, adapt 0.1, bundle 4.5, render 8.4, join 12.3 of which the film decode 10.2) |
| the same edit, children mode | 1 | 26.9 s (one child: the per-segment overhead is paid once) |
| the same edit before the validator-only fix | 23 | 144 s (in-process) / 260 s (children) |

Proof for the edit: `H_film == H_seg` over 3374 of 3374 frames, pts continuous, `decode_clean`, `nb_read_frames` 3374; the in-process film and the children film
are byte-identical (same sha256); 23 frames (f1147-f1163 and f1307-f1312: the changed word, both cut neighbours) rendered through the segment path are
byte-identical PNGs to the same frames of the full-film compositor; against the cold film the framemd5 column differs on f1155-f1309 only (the re-encoded
segment: x264 rate control follows the first changed frame inside it) and is identical on the other 3219 frames.

### Where the time still goes (and what is deliberately not skipped)

* the film decode of the join (10 s for 3374 frames at 1080p): it IS the proof; not weakened.
* the webpack bundle (4.5 s): rebuilt each run (the staged assets are part of it).
* audio: an audio change renders the whole mix once (~45 s); a picture-only edit never does.
* `build-config` + adapter: under 1 s here.

### Master (4K)

`master-render` takes the master kit config (4K cores, seam blends, tails bound with receipts), built by the master adapter once the master is ready; keys include
mode, scale 2, crf 16 and the 4K bindings' shas, so a master segment never reuses a review entry. Not rendered here (CPU, no 4K film).
The "399 s" of the audit's table is the episode-local master config build (`build_master_config_v003.py`: verification of every chunk core, final and seam
variant, several checks hashing the same files), not the kit. Measured on the same machine with a warm OS file cache: sha256 of the 14 shot cores (3.2 GB) 1.7 s,
`ffprobe -count_packets` of the 14 cores 5.4 s, all 416 production mp4 (7.3 GB) hashed from Python in ~8 s: hashing alone does not reproduce 399 s, so the cold-disk
reads and the repeated checks of that script are where the time goes. With the cache a repeated verification costs a stat per file (14 cores: 1.7 s -> 0.00 s hash,
5.4 s -> 0.001 s probe). `engine/editorial/segments_hashcache.py` is the same cache for Python callers (its `HashCache.sha256(path)` replaces a plain `sha256(path)`);
wiring it into the episode-local `m2_common.sha256` is a one-line change owned by the episode scripts (not made here).

### Limits and trust boundaries (stated)

* The hash cache trusts {path, size, mtime ns, inode}; content changed with all four restored is not seen by it (R15-H4, R15-B1 step 4). The join still refuses such a segment
  (the film decode no longer matches the recorded frame hashes) and `--rehash-all` names it CORRUPT before anything renders. A file hashed within 2 s of its last write is not trusted (racy rule).
* Gates are unchanged: waivers, G-LABEL, receipts in master mode, tail / segment file checks, preview refusal, the guard against the kit source changing while a build runs.
* A bundle-time or font change re-renders everything (the pins are in every key).
