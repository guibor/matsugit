import argparse
from pathlib import Path
import sys
import json
import subprocess

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
    commands.add_parser('setup-charts', help='Install the optional isolated local chart backend')
    template = commands.add_parser('template', help='Print or create an editable Markdown starter')
    from .authoring import TEMPLATES
    template.add_argument('name', choices=sorted(TEMPLATES))
    template.add_argument('--output', type=Path)
    template.add_argument('--fragment', action='store_true')
    lint = commands.add_parser('lint', help='Check slide structure and density (not visual proof)')
    lint.add_argument('source', type=Path)
    lint.add_argument('--quarto')
    lint.add_argument('--json', action='store_true')
    lint.add_argument('--strict', action='store_true', help='Exit 2 if any warning is found')
    lint.add_argument('--rendered', type=Path, help='Also inspect an existing local render using Playwright (network blocked)')
    editor = commands.add_parser("edit-table", help="Edit one Markdown table in a local browser window")
    editor.add_argument("source", type=Path)
    editor.add_argument("--output", required=True, type=Path)
    editor.add_argument("--no-open", action="store_true")
    editor.add_argument("--port", type=int, default=0)
    for name in ("render", "publish", "setup-ci"):
        p = commands.add_parser(name)
        if name != "setup-ci":
            p.add_argument("source", type=Path)
            p.add_argument('--handout', action='store_true', default=None,
                           help='Also render a slide-ordered presenter handout with notes')
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
        if args.command == 'setup-charts':
            from .charts import setup
            setup()
            return 0
        if args.command == 'template':
            from .authoring import template
            print(template(args.name, args.output, args.fragment))
            return 0
        if args.command == 'lint':
            from .lint import check, rendered
            settings = config(args.source, vars(args))
            findings = check(args.source, settings['quarto'])
            if args.rendered:
                findings.extend(rendered(args.rendered))
            print(json.dumps(findings, indent=2) if args.json else
                  '\n'.join(f"{f['code']}: {f['slide']}: {f['message']}" for f in findings)
                  or 'No structural warnings. Visual review is still required.')
            return 2 if findings and args.strict else 0
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
    except (Error, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"folioforge: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("folioforge: cancelled", file=sys.stderr)
        return 130
