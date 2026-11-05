"""Conservative local preview patches. Export/CI always use the full renderer."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from . import core
from .layout import slides


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def pandoc_command(quarto):
    """Use Quarto's own bundled Pandoc, never an unrelated system version."""
    executable = shutil.which(str(quarto))
    if executable:
        directory = Path(executable).resolve().parent / 'tools'
        for candidate in (directory / 'pandoc', directory / 'x86_64/pandoc', directory / 'aarch64/pandoc'):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return [str(candidate)]
    return [str(quarto), 'pandoc']


def safe_inlines(nodes):
    for node in nodes:
        kind, content = node.get('t'), node.get('c')
        if kind in ('Str', 'Space', 'SoftBreak', 'LineBreak'):
            continue
        if kind in ('Emph', 'Strong', 'Strikeout', 'Superscript', 'Subscript', 'SmallCaps', 'Underline'):
            if safe_inlines(content):
                continue
        # Raw HTML, code, math, images, footnotes and attributed spans may need
        # Quarto processing or JS initialization. Leave them to a full render.
        if kind == 'Link' and content[0] == ['', [], []] and safe_inlines(content[1]):
            if re.match(r'^(?:https?://|mailto:|tel:|#)', content[2][0]):
                continue
        return False
    return True


def annotate(ast):
    """Keep block geometry unchanged: anchors surround only inert inline runs."""
    result = deepcopy(ast)
    slots = {}

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            kind = node.get('t')
            if kind in ('Plain', 'Para'):
                content = node['c']
                if content and safe_inlines(content):
                    key = 'ffp-' + str(len(slots))
                    slots[key] = deepcopy(content)
                    content[:] = [{'t': 'Span', 'c': [['', [], [['data-ff-preview', key]]], content[:]]}]
                    return
            for child in node.values():
                visit(child)

    visit(result.get('blocks', []))
    shape = deepcopy(result)

    def blank(node):
        if isinstance(node, list):
            return [blank(n) for n in node]
        if isinstance(node, dict):
            if node.get('t') == 'Span' and dict(node['c'][0][2]).get('data-ff-preview') in slots:
                return {'slot': dict(node['c'][0][2])['data-ff-preview']}
            return {k: blank(v) for k, v in node.items()}
        return node

    return result, {'shape': digest(blank(shape)), 'slots': slots}


def fragments(ast, changes, pandoc):
    if not changes:
        return []
    blocks = []
    for index, (key, inlines) in enumerate(changes.items()):
        blocks.extend([{'t': 'RawBlock', 'c': ['html', f'<!--ff-preview:{index}-->']},
                       {'t': 'Plain', 'c': inlines}])
    rendered = core.run([*pandoc, '-f', 'json', '-t', 'html5', '--wrap=none'],
                        text=json.dumps(dict(ast, meta={}, blocks=blocks)))
    parts = re.split(r'<!--ff-preview:\d+-->\n?', rendered)[1:]
    if len(parts) != len(changes):
        raise core.Error('Preview fragment count mismatch')
    return [{'id': key, 'html': html.strip()} for key, html in zip(changes, parts)]


def fingerprint(settings, output, theme):
    files = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (output / 'theme').rglob('*') if p.is_file()}
    # Immutable per plugin process, but also safe across a local renderer update.
    for root in (Path(__file__).parent / 'runtime', Path(__file__).parent / 'diagram_runtime', Path(__file__).parent):
        for p in root.glob('*'):
            if p.is_file() and p.suffix in ('.py', '.css', '.js', '.mjs', '.json'):
                files[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    executable = shutil.which(str(settings['quarto']))
    version = [(str(p), p.stat().st_size, p.stat().st_mtime_ns)
               for p in map(Path, [executable, *settings['_preview_pandoc'][:1]]) if p.is_file()] if executable else []
    return digest([files, settings['theme'], theme, str(settings['source']), str(settings['source_root']), version])


def render(settings, output, text, format='document', base=None):
    if format not in ('document', 'slides'):
        raise core.Error('Unknown preview format')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = dict(settings, handout=False, _preview_pandoc=pandoc_command(settings['quarto']))
    theme = core.install_theme(settings, output)
    previous = core.read_json(Path(base) / 'preview.json') if base and (Path(base) / 'preview.json').is_file() else {}
    signature = fingerprint(settings, output, theme)
    cache = output / 'chart-cache'
    if previous.get('signature') == signature and (Path(base) / 'chart-cache').is_dir():
        shutil.copytree(Path(base) / 'chart-cache', cache)
    ast = core.normalize(settings, output, source_text=text, editable_source=False)
    colours = core.read_json(core.inside(output / 'theme', theme['charts'])) if 'charts' in theme else {}
    display = core.canvas_components(core.evidence_components(core.chart_components(
        core.prepare_diagrams(ast, output, theme, colours, cache), output, colours, cache=cache)), output)
    from .source import visible_notes
    target = slides(display) if format == 'slides' else visible_notes(display)
    annotated, snapshot = annotate(target)
    snapshot.update(signature=signature, format=format)
    can_patch = (previous.get('signature') == signature and previous.get('format') == format
                 and previous.get('shape') == snapshot['shape'])
    if can_patch:
        changed = {key: value for key, value in snapshot['slots'].items()
                   if previous['slots'].get(key) != value}
        payload = {'changes': fragments(target, changed, settings['_preview_pandoc'])}
        core.write_json(output / 'patch.json', payload)
        kind = 'patch'
        print(f'Updating {len(changed)} text regions in {format}', flush=True)
    else:
        # Source downloads and generated inputs exist only for a full preview.
        # Source text is never written to the user's file.
        source_name = 'source.org' if settings['source'].suffix.lower() == '.org' else 'source.md'
        (output / source_name).write_text(text, encoding='utf-8')
        if source_name != 'source.md':
            (output / 'source.md').write_text('', encoding='utf-8')
        core.render(settings, output, source_text=text, formats=(format,),
                    _prepared=(theme, ast, display),
                    _transform=lambda value, fmt: annotated if fmt == format else value)
        kind = 'full'
    core.write_json(output / 'preview.json', snapshot)
    return {'theme': settings['theme'], 'kind': kind, 'format': format,
            'changed': len(payload['changes']) if can_patch else None}
