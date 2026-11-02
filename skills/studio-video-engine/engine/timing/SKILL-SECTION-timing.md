> MERGED into SKILL.md 2026-10-28
### Word timing: `jjv timing words`, `jjv qa words` (T-E33) -- section for SKILL.md, root merges it

`engine/timing/{recipe,sound,onset,firstword,q1,gate,recognise,whisper_worker,dialogue,words,wavs,run,cli}.py`, recipe
`recipes/timing/words-onset-v001.json` (every threshold; `document_schema` names the layout the editorial stage reads).  CPU only; no
GPU, no ComfyUI, no network.  Wiring lines: `engine/timing/CLI-PATCH.md`.

Pipeline (`timing words --episode E --dialogue F --out DIR`): (1) recognition: `whisper_worker.py` runs with `python -I` in the
machine's recognition Python (`machine.timing.python` / `--python`) and model (`machine.timing.model_dir` / `--model`); a missing
interpreter, model or package is `Uncertain` (exit 2) with the reason; the script text stays authoritative and a script word that
was not heard makes the line `Uncertain` (no estimated time); the line's last word ends where its speech ends (end of the last RMS
run; the recognised end stays in `raw_whisper_end_s`). (2) onset rule on EVERY word, a port of the verified hand-run v003/v004 tools:
line-first word = first sustained speech run (breath/click burst skipped, unvoiced pre-roll fused with speech -> first voiced
window); every word: start in silence (< floor) -> rising edge of the first sustained voiced run (rule A); start on sound but a
pause (0.05 s within 0.20 s of the start, 0.10 s within 0.40 s) precedes the word's sound -> edge after the pause (rule B,
repeated, shift capped at 0.60 s); never earlier, never later than end - 2 f, ends kept; a stop closure inside a word ('liquid',
about 0.08 s) does NOT move. (3) Q1 gate (below). Outputs, write-once, no timestamp: `WORD-TIMING.json` (same layout as v003/v004),
`WORD-TIMING-QA.json` (every word's audit row, line-first rows, Q1 rows + negative control), `timing-receipt.json` (input/output
shas, recipe sha, source).  `--recognised WORD-TIMING.json` skips step 1 and re-applies the rules (ends kept).

`jjv qa words --episode E --timing F [--out R]` (Q1): per word an independent detector (10 ms windows, silence < -55 dBFS for
>= 0.06 s starting <= 0.40 s after the word start, edge at -45 dBFS) gives the audible onset after a pause; FAIL if any word is lit
> 0 f early or > 2 f late; words with no pause before them are `n/a`.  PASS also needs the built-in NEGATIVE CONTROL: one passing
word shifted 5 f earlier must be flagged (recorded in the receipt); a gate that cannot show that is FAIL; no word after a pause =
`UNTESTABLE` (exit 2).  Every WAV is hash-bound to its declared sha256 (`Refused` on mismatch; outside the episode root needs
`--allow-outside`).

Exit codes: 0 PASS; 1 Q1 FAIL / rule violation (files still written); 2 missing or unreadable input, recognition not configured,
unheard script word, UNTESTABLE.

Parity (measured, `tests/test_timing_parity_ep04.py`): from the recognised word times of the first episode (fixture
`engine/timing/fixtures/parity-words-v003-to-v004.json`, WAVs read in place) the engine reproduces the hand-run v004: 108/108
words, 4 fields each, 0 differences; 25 moved words with the same old/new frames; the per-word audit rows and the 108 Q1 rows
equal the hand-run QA file. Opt-in live check (`JJV_TIMING_PYTHON`, `JJV_TIMING_MODEL`): faster-whisper from scratch on the 12
WAVs gives the same 108 start frames and the same 25 new frames (the hand-run chain differs only in last-word ends by <= 1 f,
S06_B's segment boundary by 7 f).

**Recipes (root decisions 2026-10-27):** `timing/words-onset-v003` is the domain default (`default_for_domain`); `v001` and `v002` stay selectable with
`--recipe` (v002 lost its default flag, nothing else).  Rules A/B and the line-first rule are identical in all three; only Q1 differs.
v002: pause >= 0.10 s (a stop closure is not a pause), onset = first window of a sustained VOICED run (>= 0.03 s above -35 dBFS), late 3-6 f WARN, > 6 f FAIL.
v003 = v002 with onset_voiced_dbfs -42 (the rule lights at the -45 dBFS consonant edge; -35 calls the consonant early) and max_early_frames 1 (33 ms is below what
a viewer sees); early > 1 f FAIL; late 1-2 f PASS, 3-6 f `WARN-late` (listed in `summary.warn_words` and the receipt `warnings`, does not block), > 6 f FAIL.
Negative controls (all must be flagged, else FAIL): a passing word shifted 5 f earlier AND one shifted 2 f earlier (`negative_control.controls`).
Measured on the hand-run v004 reference: v001 FAIL (1 early 'liquid', 5 late); v002 FAIL (5 early at -1 f); v003 PASS (33 tested, 30 pass, 0 early, 0 late,
3 WARN: `S01_B:and` +3, `S06_B:and` +3 and +4).  Pinned in `tests/test_timing_{v002,v003}.py` / `test_timing_parity_ep04.py`.

Tests: `tests/test_timing_{rules,q1,recognise,run,cli,parity_ep04,v002,v003,modules}.py` (synthetic-WAV cases: silence start, pause inside the first
0.4 s, the 'liquid' closure, caps, shift limit, burst before speech, unvoiced pre-roll; Q1 per-word limits, negative control, UNTESTABLE;
worker with a fake model; refusals; CLI handlers; the parity gate proven red by tampering a threshold; size/neutrality/no-network).
