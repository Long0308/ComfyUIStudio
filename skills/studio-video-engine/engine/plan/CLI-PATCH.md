> MERGED into SKILL.md 2026-10-28
# CLI-PATCH: wire `jjv plan explain` into `bin/jjv.py` (root applies; the T-E45 P0 builder may not edit that file)

Three additions, each between the same `# --- ... stage ---` markers the other stages use.  Anchors: the end of the timing
import block, the end of `build_parser()`, and the end of `_dispatch()`.  Checked on a scratch copy of `bin/jjv.py` of
2026-10-27 22:07 (only SKILL_ROOT repointed): `plan explain --old V15 --new V15` printed the JSON and exited 0, a missing
directory printed `{"ok": false, ...}` and exited 1.  If other builders moved those anchors, re-apply by hand: the three
blocks below do not depend on anything else in the file.

```diff
@@ -36,6 +36,9 @@
 # --- timing stage (T-E33) ---------------------------------------------------------------
 from engine.timing.cli import register_cli as register_timing, run_qa_words, run_timing  # noqa: E402
 # --- end timing stage -------------------------------------------------------------------
+# --- plan stage (T-E45 P0) --------------------------------------------------------------
+from engine.plan.cli import register_cli as register_plan, run_plan  # noqa: E402
+# --- end plan stage ---------------------------------------------------------------------
 
 
 def build_parser() -> argparse.ArgumentParser:
@@ -73,6 +76,9 @@
     # --- timing stage (T-E33) ---
     register_timing(stages)
     # --- end timing stage ---
+    # --- plan stage (T-E45 P0) ---
+    register_plan(stages)
+    # --- end plan stage ---
     return parser
 
 
@@ -152,6 +158,10 @@
     if args.stage == "qa" and args.verb == "words":
         return run_qa_words(args)
     # --- end timing stage ---
+    # --- plan stage (T-E45 P0) ---
+    if args.stage == "plan" and args.verb == "explain":
+        return run_plan(args)
+    # --- end plan stage ---
     return 2
 
 
```

`engine/plan/cli.py` exposes `register_cli(stages)` and `run_plan(args)`; `bin/jjv.py`'s own `main()` already maps
`EngineError` to its exit code (1 refused, 2 unreadable) and prints `{"ok": false, "error": ...}`.  A `--json-out` that
already exists makes `run_plan` raise `FileExistsError` (exclusive create): `jjv.main()` turns that into exit 2 -- use the
standalone entry below when you want the 1.

## Until the patch is applied

`python -I engine/plan/__main__.py explain --old DIR --new DIR [--target review|master|all] [--json-out FILE] [--verbose]`
(the skill root is added by the file itself; same JSON on stdout, human table on stderr, same exit codes).

## What the command reads (read-only) and prints

* `DIR` = one version of the episode inputs: either `plan-inputs.json` (`jjv/plan-inputs/v1`, optional keys `config`,
  `mix_plan`, `mix_wav_sha256`, `render_record`, `segments`, `pins`, `gpu_cores`) or the review-hd layout:
  `config/review-config*.json`, `RECEIPT.json` (mix plan path + sha + mix wav sha), `render-record-picture-*.json` (pins),
  `mix-plan*.json`.  Two candidates for one file is `Refused` (exit 1), never a silent pick.
* `gpu_cores.<shot>`: free-form leaves of the shot's GPU job (`seed`, `prompt`, `anchor_sha256`, ...; `upscale_*` keys go to the
  SeedVR2 node) and `core_receipt`: a receipt whose text contains the new core sha (then the GPU job is NOT listed as needed).
* Policy `recipes/plan/policy-v001.json` (what a slice may drop; `audio_slice.include_word_windows`), costs
  `recipes/plan/costs-v001.json` (every number tagged measured / derived / unmeasured, with its source).
* Output: `jjv/plan-explain/v1` JSON (`headline`, `summary`, `rows[]` with node, status, why, leaves, action_code, action,
  est_seconds / est_basis / cost_lines, requires_approval) and a table on stderr.  Exit 0 also when GPU jobs are listed:
  `explain` never runs, queues or posts anything (tests block sockets and Popen while it runs).
