import argparse
from pathlib import Path
import sys

from .core import Error, config, render
from .publish import publish, setup_ci


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render editable documents and themed slides together")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ('status', 'update', 'rollback'):
        p = commands.add_parser(name, help=f'{name.title()} configured versioned renderer bundles')
        select = p.add_mutually_exclusive_group(required=True)
        select.add_argument('--all', action='store_true')
        select.add_argument('--repo', type=Path)
        p.add_argument('--config', type=Path, help='Explicit trusted renderer-update configuration')
        if name != 'status':
            p.add_argument('--dry-run', action='store_true')
        if name == 'update':
            p.add_argument('--version', help='Install a specific published version')
    commands.add_parser("setup-editor", help="Provision a verified isolated Pandoc when needed")
    editor = commands.add_parser("edit-table", help="Edit one Markdown table in a local browser window")
    editor.add_argument("source", type=Path)
    editor.add_argument("--output", required=True, type=Path)
    editor.add_argument("--no-open", action="store_true")
    editor.add_argument("--port", type=int, default=0)
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
        if args.command in ('status', 'update', 'rollback'):
            from .updates import manage
            manage(args.command, args.config, args.all, args.repo,
                   getattr(args, 'dry_run', False), getattr(args, 'version', None))
            return 0
        if args.command == "setup-editor":
            from .converter import install_converter
            install_converter()
            return 0
        if args.command == "edit-table":
            from .table_editor import serve
            return serve(args.source, args.output, open_browser=not args.no_open, port=args.port)
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
