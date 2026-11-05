"""Self-contained D2 diagrams using the upstream WASM parser and layout engine."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

if __package__:
    from .charts import style as chart_style
else:
    from charts import style as chart_style

RUNTIME = Path(__file__).parent / 'diagram_runtime'
LIMIT = 64000
SVG_LIMIT = 8 * 1024 * 1024


def runtime_path():
    return Path(os.environ.get('MATSUGIT_DIAGRAM_RUNTIME',
                '~/.local/share/matsugit/diagrams')).expanduser().resolve()


def setup():
    """Explicitly install a locked optional backend; rendering never downloads."""
    npm = shutil.which('npm')
    if not npm or not shutil.which('node'):
        raise ValueError('D2 needs Node.js 22+ and npm, then run matsugit setup-diagrams')
    version = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    if not re.fullmatch(r'v\d+\.\d+\.\d+', version) or int(version[1:].split('.')[0]) < 22:
        raise ValueError('D2 needs Node.js 22+; found ' + version)
    target = runtime_path()
    target.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'package-lock.json'):
        shutil.copyfile(RUNTIME / name, target / name)
    subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund',
                    '--prefix', str(target)], check=True)
    print('D2 backend ready:', target, flush=True)


def is_diagram(node):
    return isinstance(node, dict) and node.get('t') == 'CodeBlock' and 'd2' in node['c'][0][1]


def contains(node):
    if isinstance(node, list):
        return any(contains(n) for n in node)
    return isinstance(node, dict) and (is_diagram(node) or any(contains(v) for v in node.values()))


def style(theme=None, colours=None):
    """D2 colour tokens derive from the chart palette unless explicitly replaced."""
    theme = theme or {}
    if not isinstance(theme, dict) or set(theme) - {'layout', 'palette'}:
        raise ValueError('Diagram theme supports only layout and palette')
    layout = theme.get('layout', 'elk')
    if layout not in ('elk', 'dagre', 'tala'):
        raise ValueError('D2 layout must be elk, dagre or tala')
    c = chart_style(colours or {})
    palette = {'N1': c['ink'], 'N2': c['muted'], 'N3': c['grid'],
               'N4': '#f4f6fa', 'N5': c['background'], 'N6': c['background'],
               'N7': c['background'], 'B1': c['accent'], 'B2': c['accent'],
               'B3': c['grid'], 'B4': '#edf2fa', 'B5': '#f5f7fc',
               'B6': c['background'], 'AA2': c['series'][1 % len(c['series'])],
               'AA4': '#edf2fa', 'AA5': '#f5f7fc', 'AB4': '#eef5f2', 'AB5': '#f5f8f6'}
    overrides = theme.get('palette', {})
    if not isinstance(overrides, dict) or set(overrides) - set(palette) or any(
            not isinstance(v, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', v) for v in overrides.values()):
        raise ValueError('D2 palette requires known D2 tokens and six-digit hex colours')
    return {'layout': layout, 'palette': dict(palette, **overrides)}


def validate_svg(svg):
    """Reject active or externally linked output, including Markdown labels."""
    if len(svg.encode('utf-8')) > SVG_LIMIT or re.search(r'<!DOCTYPE|<!ENTITY', svg, re.I):
        raise ValueError('D2 output is too large or contains an XML entity declaration')
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError('D2 did not produce valid SVG') from exc
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        raise ValueError('D2 did not produce an SVG image')
    forbidden = {'script', 'iframe', 'object', 'embed', 'image', 'img', 'audio', 'video',
                 'link', 'meta', 'animate', 'animatetransform', 'set'}
    for element in root.iter():
        tag = element.tag.rsplit('}', 1)[-1].lower()
        if tag in forbidden:
            raise ValueError(f'D2 output contains unsupported element {tag}')
        for name, value in element.attrib.items():
            key = name.rsplit('}', 1)[-1].lower()
            if key.startswith('on') or key in ('src', 'srcdoc') or (
                    key == 'href' and not value.startswith('#')):
                raise ValueError('D2 output contains an active or external resource')
        css = ((element.text or '') if tag == 'style' else '') + ' '.join(element.attrib.values())
        if re.search(r'@import|expression\s*\(|\\', css, re.I):
            raise ValueError('D2 output contains unsupported CSS')
        for url in re.findall(r'url\((.*?)\)', css, re.I | re.S):
            if not url.strip(' \t\n\'"').startswith(('#', 'data:font/', 'data:application/font-')):
                raise ValueError('D2 output contains an external CSS resource')
    return svg


def render_svg(code, appearance):
    if not code.strip() or len(code.encode('utf-8')) > LIMIT:
        raise ValueError('D2 blocks must be nonempty and at most 64 KB')
    target = runtime_path()
    node = shutil.which('node')
    if not node or not (target / 'node_modules/@d2lang/d2/package.json').is_file():
        raise ValueError('D2 backend unavailable. Run matsugit setup-diagrams (Node.js 22+ and npm required)')
    tokens = '\n'.join(f'      {k}: "{v}"' for k, v in appearance['palette'].items())
    themed = 'vars: {\n  d2-config: {\n    theme-overrides: {\n' + tokens + '\n    }\n  }\n}\n' + code
    payload = {'code': themed, 'layout': appearance['layout'],
               'salt': hashlib.sha256(themed.encode()).hexdigest()[:16]}
    with tempfile.TemporaryDirectory(prefix='matsugit-d2-') as directory:
        try:
            result = subprocess.run([node, '--max-old-space-size=1024', str(RUNTIME / 'render.mjs'), str(target)],
                                    cwd=directory, input=json.dumps(payload), text=True,
                                    capture_output=True, timeout=45)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('D2 exceeded 45 seconds; simplify this diagram') from exc
    if result.returncode:
        raise ValueError('D2 rendering failed: ' + result.stderr[-3000:])
    return validate_svg(result.stdout)


def prepare(node, output, theme=None, colours=None, cache=None):
    if isinstance(node, list):
        return [prepare(n, output, theme, colours, cache) for n in node]
    if not isinstance(node, dict):
        return node
    if not is_diagram(node):
        return {k: prepare(v, output, theme, colours, cache) for k, v in node.items()}
    attrs, code = node['c']
    options = dict(attrs[2])
    if set(options) - {'layout', 'caption'}:
        raise ValueError('D2 block options: layout="elk|dagre|tala", caption="Description"')
    appearance = style(dict(theme or {}, **({'layout': options['layout']} if 'layout' in options else {})), colours)
    # Invalidate cached geometry after an engine, wrapper or theme change.
    engine = runtime_path() / 'node_modules/@d2lang/d2/package.json'
    version = engine.read_text() if engine.is_file() else 'missing'
    key = hashlib.sha256(json.dumps([code, appearance, version,
                         (RUNTIME / 'render.mjs').read_text()], sort_keys=True).encode()).hexdigest()
    cached = Path(cache) / (key + '-d2.svg') if cache else None
    svg = validate_svg(cached.read_text()) if cached and cached.is_file() else render_svg(code, appearance)
    if cached and not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(svg, encoding='utf-8')
    assets = Path(output) / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    name = key[:20] + '-d2.svg'
    (assets / name).write_text(svg, encoding='utf-8')
    title = options.get('caption', 'D2 diagram')
    # Quarto treats image alt text as a figure caption; keep the accessible label
    # on the wrapper and render an explicit caption only when the author asks.
    image = {'t': 'Image', 'c': [['', [], []], [], ['assets/' + name, '']]}
    blocks = [{'t': 'Para', 'c': [image]}]
    if options.get('caption'):
        blocks.append({'t': 'Div', 'c': [['', ['ff-caption'], []], [{'t': 'Para', 'c': [{'t': 'Str', 'c': title}]}]]})
    # Not ff-diagram: that role is currently reserved for live Mermaid capture.
    return {'t': 'Div', 'c': [[attrs[0], ['ff-media', 'ff-d2', *[c for c in attrs[1] if c.startswith('media-')]],
                             [['role', 'img'], ['aria-label', title]]], blocks]}


if __name__ == '__main__' and sys.argv[1:] == ['--setup']:
    setup()
