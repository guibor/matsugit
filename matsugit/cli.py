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
    sync = commands.add_parser('sync', help='Fetch/check or explicitly fast-forward the real source checkout; never push')
    sync.add_argument('source', type=Path)
    sync.add_argument('--check', action='store_true', help='Fetch and report only; leave working files untouched')
    sync.add_argument('--yes', action='store_true', help='Confirm fast-forward of a clean checkout')
    sync.add_argument('--json', action='store_true')
    adopt = commands.add_parser('adopt', help='Move exact source/assets into a checkout and leave local symlinks; no commit/push')
    adopt.add_argument('source', type=Path)
    adopt.add_argument('--repo', required=True, type=Path)
    adopt.add_argument('--destination', required=True, help='Unused source path relative to the checkout')
    adopt.add_argument('--yes', action='store_true')
    adopt.add_argument('--fingerprint', help='Require this reviewed plan fingerprint')
    inventory = commands.add_parser('source-files', help='List a self-contained source and its referenced local assets')
    inventory.add_argument('source', type=Path)
    inventory.add_argument('--root', type=Path, help='For in-place publication, permit assets within this existing repository')
    cursor = commands.add_parser('setup-cursor', help='Install the shared interactive workspace, skill and commands into local Cursor')
    cursor.add_argument('--checkout', type=Path)
    cursor.add_argument('--check', action='store_true')
    targets = commands.add_parser('target', help='Configure named publishing checkouts without publishing')
    targets.add_argument('action', choices=['list', 'set', 'default'])
    targets.add_argument('name', nargs='?')
    for flag in ('repo', 'provider', 'branch', 'remote', 'site-dir', 'site-url', 'theme', 'expected-remote', 'deployment', 'build', 'ci-layout', 'source-dir'):
        targets.add_argument('--' + flag)
    targets.add_argument('--default', action='store_true')
    targets.add_argument('--json', action='store_true')
    export = commands.add_parser('export', help='Export a local file, optionally into a configured synced folder')
    export.add_argument('source', type=Path)
    export.add_argument('--format', choices=['html', 'zip', 'pptx', 'pdf'], required=True)
    export.add_argument('--output', type=Path)
    export.add_argument('--sync-folder', action='store_true')
    export.add_argument('--replace', action='store_true', help='Explicitly replace an existing export, including external edits')
    export.add_argument('--theme')
    export.add_argument('--quarto')
    export.add_argument('--reference-doc', type=Path)
    folder = commands.add_parser('export-folder', help='Configure a local OneDrive/synced export folder; no API access')
    folder.add_argument('directory', type=Path)
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
    commands.add_parser('setup-diagrams', help='Install the optional local D2 backend (Node.js 22+ and npm)')
    commands.add_parser('setup-export', help='Install isolated Chromium support for PDF and diagram export')
    template = commands.add_parser('template', help='Print or create an editable Markdown/Org starter')
    from .authoring import TEMPLATES, ELEMENTS
    template.add_argument('name', choices=sorted(TEMPLATES.keys() | ELEMENTS.keys()))
    template.add_argument('--output', type=Path)
    template.add_argument('--fragment', action='store_true')
    template.add_argument('--format', choices=['markdown', 'org'], default='markdown')
    conversion = commands.add_parser('convert', help='Convert inert slide source on stdin, retaining semantic blocks')
    conversion.add_argument('--from', dest='reader', choices=['markdown', 'org'], required=True)
    conversion.add_argument('--to', dest='writer', choices=['markdown', 'org'], required=True)
    plain = commands.add_parser('check', help='Explain slide-structure problems in plain language (reads text only)')
    plain.add_argument('source', type=Path)
    plain.add_argument('--json', action='store_true')
    plain.add_argument('--strict', action='store_true', help='Exit 2 if anything needs fixing')
    lint = commands.add_parser('lint', help='Check slide structure and density (not visual proof)')
    lint.add_argument('source', type=Path)
    lint.add_argument('--quarto')
    lint.add_argument('--json', action='store_true')
    lint.add_argument('--strict', action='store_true', help='Exit 2 if any warning is found')
    lint.add_argument('--rendered', type=Path, help='Also inspect an existing local render using Playwright (network blocked)')
    editor = commands.add_parser("edit-table", help="Edit one Markdown or Org table in a local browser window")
    editor.add_argument("source", type=Path)
    editor.add_argument("--output", required=True, type=Path)
    editor.add_argument("--no-open", action="store_true")
    editor.add_argument("--port", type=int, default=0)
    for name in ("render", "publish", "publish-plan", "setup-ci"):
        p = commands.add_parser(name)
        if name != "setup-ci":
            p.add_argument("source", type=Path)
            p.add_argument('--handout', action='store_true', default=None,
                           help='Also render a slide-ordered presenter handout with notes')
        for flag in ("repo", "theme", "themes-dir", "quarto", "site-dir", "slug", "branch", "remote", "target"):
            p.add_argument("--" + flag)
        if name == "render":
            p.add_argument("--output", required=True, type=Path)
        elif name == "publish":
            p.add_argument("--yes", action="store_true", help="Confirm committing and pushing rendered artifacts")
            p.add_argument("--deploy", action="store_true", help="Also request the explicitly installed Pages workflow")
        elif name == 'setup-ci':
            p.add_argument("--provider", choices=["github", "gitlab"], required=True)
        if name in ('publish', 'publish-plan'):
            p.add_argument('--move-source', action='store_true', default=None, help='For source CI: move source/assets into target and leave local symlinks (explicit opt-in)')
            p.add_argument('--build', choices=['ci', 'local'], help='Build on CI from source, or render locally before pushing')
            p.add_argument('--ci-layout', choices=['native', 'topics'])
            p.add_argument('--source-dir')
    args = parser.parse_args(argv)
    try:
        if args.command == 'source-files':
            from .adopt import inventory
            print(json.dumps([str(path) for path in inventory(args.source, root=args.root)]))
            return 0
        if args.command == 'adopt':
            from . import adopt
            data = adopt.plan(args.source, args.repo, args.destination)
            if args.fingerprint and args.fingerprint != data['fingerprint']:
                raise Error('Relocation plan changed; review again')
            if args.yes:
                adopt.apply(data)
            print(json.dumps(data, indent=2))
            return 0
        if args.command == 'sync':
            from .git_sync import sync
            data = sync(args.source, check=args.check or not args.yes, confirmed=args.yes)
            print(json.dumps(data, indent=2) if args.json else
                  f"{data['status']}: {data['repo']} ({data['ahead']} ahead, {data['behind']} behind)\n"
                  + data['changes'] + ('\nUse --yes to apply a clean fast-forward.' if not args.yes else ''))
            return 0
        if args.command == 'setup-cursor':
            from .cursor import install
            print(install(args.checkout, check=args.check))
            return 0
        if args.command == 'setup-export':
            from .exports import setup
            setup()
            return 0
        if args.command == 'target':
            from . import targets
            if args.action == 'list':
                data = targets.settings()
                print(json.dumps({'default': data.get('default_publish_target'), 'targets': data.get('publish_targets', {})}, indent=2))
            elif args.action == 'default':
                targets.resolve(args.name)
                print(targets.save({'default_publish_target': args.name}))
            else:
                print(targets.configure(args.name or '', vars(args), args.default))
            return 0
        if args.command == 'export-folder':
            from .targets import save
            directory = args.directory.expanduser().resolve()
            if not directory.is_dir():
                raise Error('Select an existing local sync folder; no account is connected automatically')
            print(save({'export_directory': str(directory)}))
            return 0
        if args.command == 'export':
            from .exports import export_file
            result = export_file(config(args.source, vars(args)), args.format, args.output,
                                 sync_folder=args.sync_folder, reference=args.reference_doc, replace=args.replace)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'setup-diagrams':
            from .diagrams import setup
            setup()
            return 0
        if args.command == 'setup-charts':
            from .charts import setup
            setup()
            return 0
        if args.command == 'template':
            from .authoring import template
            print(template(args.name, args.output, args.fragment, args.format))
            return 0
        if args.command == 'convert':
            from .source import convert
            from .converter import converter
            print(convert(sys.stdin.read(), args.reader, args.writer, converter()), end='')
            return 0
        if args.command == 'check':
            from .check import check, report
            data = check(args.source)
            print(json.dumps(data, indent=2) if args.json else report(data))
            return 2 if data['problems'] and args.strict else 0
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
        elif args.command == 'publish-plan':
            from .targets import plan
            print(json.dumps(plan(settings), indent=2))
        else:
            setup_ci(settings, args.provider)
        return 0
    except (Error, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"matsugit: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("matsugit: cancelled", file=sys.stderr)
        return 130
