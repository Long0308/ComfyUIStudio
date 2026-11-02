"""Registration/dispatch glue, also runnable directly until the shared CLI is wired."""
import argparse
import json
from pathlib import Path

from ..config.loader import REPO_ROOT
from ..core.errors import EngineError, Refused, exit_code_for
from ..publish.studio import publish_studio
from .brand import join, title
from .common import block, load_context, unresolved_name
from .film import film_2k
from .guard import contained_write
from .init import init_delivery


def register_cli(stages):
    for stage, verbs in (("deliver", ("film-2k", "init")), ("brand", ("title", "join")), ("publish", ("studio",))):
        sub = stages.add_parser(stage).add_subparsers(dest="verb", required=True)
        for verb in verbs:
            p = sub.add_parser(verb)
            p.add_argument("--episode", required=True)
            p.add_argument("--delivery-config", help="default: canonical <episode>/engine/delivery.json (init: the file to write; "
                           "an explicit path must lie outside every episode tree and is non-canonical)")
            p.add_argument("--repo-root", default=str(REPO_ROOT), help="repository used to resolve episode slugs")
            p.add_argument("--out", help="fresh output directory; default from delivery config")
            if stage == "deliver" and verb == "film-2k":
                p.add_argument("--master", required=True)
            if stage == "brand" and verb == "join":
                for flag in ("intro", "title", "film"):
                    p.add_argument(f"--{flag}")
            if stage == "publish":
                mode = p.add_mutually_exclusive_group()
                mode.add_argument("--publish", action="store_true")
                mode.add_argument("--dry-run", action="store_true")


def run_delivery(args):
    if args.stage == "deliver" and args.verb == "init":
        result = init_delivery(args.episode, delivery_config=args.delivery_config, repo_root=Path(args.repo_root))
        print(json.dumps(result, ensure_ascii=True))
        return 0
    ctx = load_context(args.episode, delivery_config=args.delivery_config, repo_root=Path(args.repo_root))
    if args.stage in ("brand", "publish"):
        block(ctx, args.stage)  # clear Refused (exit 1) when the sidecar has no such block
    section = "film_2k" if args.stage == "deliver" else args.stage
    cfg = ctx["config"].get(section, {})
    output = args.out or cfg.get("out" if args.stage != "brand" else f"{args.verb}_out")
    if output and unresolved_name(output):
        raise Refused(unresolved_name(output))
    if output and not isinstance(output, str):
        raise Refused(f"output for {args.stage} must be a path string")
    out = None
    if output:  # write target: contained in the repo root, no reparse points, nothing created here
        candidate = Path(args.out) if args.out else Path(ctx["base"]) / output
        out = contained_write(candidate, Path(args.repo_root), f"{args.stage} output")
    if args.stage != "publish" and out is None:
        raise Refused(f"--out or delivery.json {section}.{args.verb}_out is required")
    if args.stage == "deliver":
        result = film_2k(ctx, args.master, out)
    elif args.stage == "brand":
        result = title(ctx, out) if args.verb == "title" else join(
            ctx, out, intro=args.intro, title_file=args.title, film=args.film)
    else:
        result = publish_studio(ctx, publish=args.publish, out=out)
    print(json.dumps(result, ensure_ascii=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jjv")
    register_cli(parser.add_subparsers(dest="stage", required=True))
    try:
        return run_delivery(parser.parse_args(argv))
    except EngineError as exc:
        print(json.dumps({"error": str(exc)}))
        return exit_code_for(exc, posted=False)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
