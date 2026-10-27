import argparse
from pathlib import Path
import sys

from .core import Error, config, render
from .publish import publish, setup_ci


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render editable documents and themed slides together")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "publish", "setup-ci"):
        p = commands.add_parser(name)
        if name != "setup-ci":
            p.add_argument("source", type=Path)
        for flag in ("repo", "theme", "themes-dir", "quarto", "site-dir", "slug", "branch", "remote"):
            p.add_argument("--" + flag)
        if name == "render":
            p.add_argument("--output", required=True, type=Path)
        elif name == "publish":
            p.add_argument("--yes", action="store_true", help="Confirm committing and pushing rendered artifacts")
            p.add_argument("--deploy", action="store_true", help="Also request the explicitly installed Pages workflow")
        else:
            p.add_argument("--provider", choices=["github", "gitlab"], required=True)
    args = parser.parse_args(argv)
    try:
        settings = config(getattr(args, "source", Path.cwd() / "source.md"), vars(args))
        if args.command == "render":
            render(settings, args.output)
            print(f"Rendered: {args.output.resolve()}")
        elif args.command == "publish":
            publish(settings, confirmed=args.yes, deploy=args.deploy)
        else:
            setup_ci(settings, args.provider)
        return 0
    except (Error, OSError, ValueError, KeyError) as exc:
        print(f"folioforge: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("folioforge: cancelled", file=sys.stderr)
        return 130
