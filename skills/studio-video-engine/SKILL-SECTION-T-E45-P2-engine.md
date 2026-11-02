> MERGED into SKILL.md 2026-10-28
## segments.json (T-E45 P2, engine side)

`jjv editorial build-config` now also writes `segments.json` (`jjv/segments/v1`, `schemas/segments.schema.json`) next to `review-config.json` and `events.json`. It is additive: the two existing documents are byte-identical to before, the summary lists `outputs["segments.json"]` with `sha256`/`bytes`, and write-once applies (a different rebuild is refused). Code: `engine/editorial/segments.py` (pure `plan_segments`, build wiring `from_build`).

**What it is.** The cut list of the film: `{schema, episode_id, fps, total_frames, main_frames, join_frame, cut_points, segments[]}`, each segment `{id, kind, start, end_exclusive, frames, shots_visible, transition_id(s)?, card_term?, inputs_slice_hint}`. Kinds: `intro`, `shot_span`, `transition`, `logo_hold`, `card`, `plate`, `ending` (the EndLogo end card).

**Rules (enforced, `Refused` otherwise).**
* The segments cover `[0, total_frames)` exactly: no gap, no overlap, every segment >= 1 frame, ids unique, `cut_points == [0, ...starts, total]`.
* An effect window is `start .. end_exclusive` of a transition record (catalog `window` mode, `presets.window`). A cut is never inside a window (edges are fine). Overlapping windows merge into one `transition` segment listing every id. A hard cut or a carry (empty window) makes no transition segment; its clip boundary is still a cut.
* Candidate cuts: 0, intro end, every shot start, dialogue end, every card start, plate start, main end, total, every window edge, the join frame. Candidates inside a window are dropped; an explicit cut inside a window (`extra_cuts`) is refused, naming the transition and the frames.
* `join_frame` (iris endings, else null) = `logo_disc.in + 3`: the first frame in which no shot video is drawn. It equals the cut the kit makes between `main` and `ending` (`remotion-kit/lib/segments.cjs`), and the iris window is cut short there because the rest of the iris is vector (logo disc, hold, shrink under card 1). Segments from the join on have `shots_visible: []`; the `logo_hold` segment's hint still lists the last shot (its captions run).
* Ids: `intro`, `shot-<id>-<n>`, `tr-<id>[+<id>]`, `card-NN` (suffix `-n` only if a card is split), `logo-hold`, `plate`, `ending`.
* `inputs_slice_hint` is an index only (shots, transitions, icons, cards the segment touches); the kit computes the real dependency-slice hash.
* The output is canonical (`pretty_json`), a rebuild is byte-identical.

**Proof (tests/test_editorial_segments.py, 97 tests).**
* Property test: 80 synthetic timelines (plain and derived, with and without join): exact cover, no cut inside any window.
* Kit agreement (node): the engine cut list of plain and derived ep04 is accepted by the kit's own `config.segments` validation; a cut inserted inside the iris window is refused by the kit (the gate goes red); on the adapter-built kit config `render.cjs --segments-plan` puts main/ending at the same frame as `join_frame` (2145).
* Mutant: removing the "drop candidates inside windows" filter turns 79 tests red.
* One boundary (T1010 `cut_push` 12 -> 10 frames): only `tr-T1010` (end 1022 -> 1020) and `shot-S04_A-1` (start 1022 -> 1020) change; every segment from f1100 on is identical.

**Caveats.** The cut list does not decide what is rendered: the kit still renders any cut list through `--segment` / `config.segments`. The engine does not know the master (4K) bindings; the same list serves review and master. The plain ep04 plate and every `plate_in`/`card_slide` window are `transition` segments (their window is the whole effect); a `plate` segment exists only when the plate outlasts its window.
