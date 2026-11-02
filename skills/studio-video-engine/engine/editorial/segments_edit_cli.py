"""``jjv edit review-render`` / ``jjv edit master-render``: edited engine inputs -> film, re-rendering only the segments the edit touched.

A thin shim: the work is ``remotion-kit/tools/edit-render.cjs`` (build-config -> kit adapter -> segment cache + one in-process render ->
stream-copy join with the framemd5 proof).  This module only validates the arguments, builds the node command line and returns its exit code
(0 built / explained, 1 refused or failed, 2 usage).  Wiring for ``bin/jjv.py`` is in ``CLI-PATCH-edit.md``.

CPU only: nothing here touches a GPU or ComfyUI.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from ..core.errors import Refused

SKILL_ROOT = Path(__file__).resolve().parents[2]
TOOL = SKILL_ROOT / "remotion-kit" / "tools" / "edit-render.cjs"

PASS_VALUES = (("browser", "--browser"), ("workdir", "--workdir"), ("build_concurrency", "--build-concurrency"), ("build_mode", "--build-mode"),
               ("force_segment", "--force-segment"), ("jsx_loader", "--jsx-loader"))
PASS_FLAGS = (("rehash_all", "--rehash-all"), ("no_hash_cache", "--no-hash-cache"), ("overwrite", "--overwrite"))


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache", required=True, help="cache folder: segments, audio mix, hash cache, engine output (reused between edits)")
    parser.add_argument("--out", help="the film (.mp4); required unless --explain")
    parser.add_argument("--explain", action="store_true", help="print which segments are stale and why; render nothing")
    parser.add_argument("--segments-file", help="engine segments.json (default: written by the build-config step)")
    parser.add_argument("--browser", help="cached chrome-headless-shell (or set REMOTION_BROWSER)")
    parser.add_argument("--workdir", help="staging folder (same volume as the sources lets files be linked, not copied)")
    parser.add_argument("--build-concurrency", choices=("1", "2"), help="Remotion concurrency (CPU only, at most 2)")
    parser.add_argument("--build-mode", choices=("inproc", "children"), help="inproc (default): one bundle and one browser; children: one render.cjs per segment")
    parser.add_argument("--force-segment", help="comma separated segment ids to re-render even when cached")
    parser.add_argument("--rehash-all", action="store_true", help="audit: ignore the verified-hash cache and read every byte again")
    parser.add_argument("--no-hash-cache", action="store_true", help="do not use or write the verified-hash cache")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing --out")
    parser.add_argument("--jsx-loader", choices=("no-child",), help="in-process JSX loader for sandboxes that block child processes")
    parser.add_argument("--episode", dest="episode_json", help="episode.json (build-config input)")
    parser.add_argument("--boundaries", help="boundaries.json (build-config input)")
    parser.add_argument("--word-timing", help="word timing document (build-config input)")
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH", help="a file outside the episode root inputs may reference; repeatable")


def register_cli(stages) -> None:
    """Add the ``edit`` stage (verbs ``review-render`` and ``master-render``) to the main parser."""
    edit = stages.add_parser("edit", help="edited inputs -> film, re-rendering only the touched segments (CPU)")
    verbs = edit.add_subparsers(dest="verb", required=True)
    review = verbs.add_parser("review-render", help="build-config -> kit adapter -> segment build (1080p review cut)")
    _common(review)
    review.add_argument("--episode-root", required=True, help="episode folder the engine records are relative to")
    review.add_argument("--episode-text", required=True, help="episode text file (intro, strings, captions, card details)")
    master = verbs.add_parser("master-render", help="segment build of the master kit config (4K cores bound with receipts)")
    _common(master)
    master.add_argument("--master-config", required=True, help="kit config of the master, built by the master adapter once the master is ready")
    master.add_argument("--episode-root", help="episode folder (only when the engine inputs are given to build the segment list)")
    master.add_argument("--episode-text", help="unused by the master (kept for symmetry)")
    from ..edit.master_config_cli import register_verb as register_master_config
    register_master_config(verbs)
    from ..assemble.cli import register_edit_verb as register_assemble
    register_assemble(verbs)


def build_command(args: argparse.Namespace) -> list[str]:
    """The node command line for one verb (pure; raises Refused for an argument combination the tool would refuse)."""
    mode = "review" if args.verb == "review-render" else "master"
    if not args.explain and not args.out:
        raise Refused("--out FILE.mp4 is required (or --explain)")
    node = shutil.which("node")
    if node is None:
        raise Refused("node is not on PATH: the segment renderer is the remotion-kit (Node + Remotion, CPU only)")
    if not TOOL.exists():
        raise Refused(f"{TOOL} is missing: the kit's edit tool is not installed")
    cmd = [node, str(TOOL), "--mode", mode, "--cache", args.cache]
    if args.out:
        cmd += ["--out", args.out]
    if args.explain:
        cmd.append("--explain")
    for attr, flag in (("episode_root", "--episode-root"), ("episode_json", "--episode-json"), ("boundaries", "--boundaries"), ("word_timing", "--word-timing"),
                       ("episode_text", "--episode-text"), ("segments_file", "--segments-file"), ("master_config", "--master-config")):
        value = getattr(args, attr, None)
        if value:
            cmd += [flag, value]
    for attr, flag in PASS_VALUES:
        value = getattr(args, attr, None)
        if value:
            cmd += [flag, str(value)]
    for attr, flag in PASS_FLAGS:
        if getattr(args, attr, False):
            cmd.append(flag)
    for item in args.allow_outside or []:
        cmd += ["--allow-outside", item]
    return cmd


def require_approved_master_config(path) -> None:
    """``edit master-render`` refuses a master-config that ``edit master-config`` stamped as not approved
    (final_gate domains only; a config with no stamp comes from a domain without the gate)."""
    import json
    stamp = json.loads(Path(path).read_text(encoding="utf-8")).get("final_gate")
    if isinstance(stamp, dict) and stamp.get("status") != "approved":
        raise Refused(f"FINAL_GATE_UNAPPROVED: master-render is a FINAL step; the master config says final_gate "
                      f"status {stamp.get('status')!r}, not 'approved' (NO_FINAL_UNTIL_SHOTS_APPROVED). "
                      "Build it without --preview and with --approvals covering every shot")


def run_edit(args: argparse.Namespace) -> int:
    """Run the node tool with inherited stdio; its exit code is ours (0 built / explained, 1 refused or failed, 2 usage)."""
    if args.verb == "master-config":
        from ..edit.master_config_cli import run_master_config
        return run_master_config(args)
    if args.verb == "master-render" and getattr(args, "master_config", None):
        require_approved_master_config(args.master_config)
    return subprocess.call(build_command(args))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jjv edit")
    stages = parser.add_subparsers(dest="stage", required=True)
    register_cli(stages)
    try:
        return run_edit(parser.parse_args(["edit", *(sys.argv[1:] if argv is None else argv)]))
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(SKILL_ROOT))
    sys.exit(main())
