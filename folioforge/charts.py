"""Bounded, table-backed charts. Matplotlib runs locally; document code never runs."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __package__:
    from .layout import plain, classes
else:
    from layout import plain, classes

KINDS = ('bar', 'barh', 'line', 'scatter')
DEFAULT = {'accent': '#2859a6', 'ink': '#202830', 'muted': '#687789',
           'grid': '#d9dfe7', 'background': '#ffffff',
           'series': ['#2859a6', '#6982a5', '#247363', '#986111']}


def style(theme):
    result = dict(DEFAULT, **theme)
    for key in DEFAULT:
        values = result[key] if key == 'series' else [result[key]]
        if not isinstance(values, list) or not 1 <= len(values) <= 8 or any(
                not isinstance(v, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', v) for v in values):
            raise ValueError(f'Chart theme {key} must contain hex colours')
    return result


def number(text):
    # Units belong in the chart attribute, not silently stripped from cell values.
    try:
        value = float(text.replace(',', '').strip())
    except ValueError as exc:
        raise ValueError(f'Chart cell must be a number, got {text!r}') from exc
    if not math.isfinite(value) or abs(value) > 1e15:
        raise ValueError('Chart values must be finite and at most 1e15 in magnitude')
    return value


def dataset(block):
    attrs = dict(block['c'][0][2])
    unknown = set(attrs) - {'type', 'unit', 'highlight', 'caption'}
    if unknown:
        raise ValueError('Unknown chart options: ' + ', '.join(sorted(unknown)))
    kind = attrs.get('type', 'bar')
    if kind not in KINDS:
        raise ValueError('Chart type must be ' + ', '.join(KINDS))
    children = block['c'][1]
    if len(children) != 1 or children[0].get('t') != 'Table':
        raise ValueError('A chart block must contain exactly one ordinary Markdown table')
    _, caption, specs, head, bodies, foot = children[0]['c']
    if caption[1] or foot[1] or len(head[1]) != 1:
        raise ValueError('Chart tables need one header row and no table caption/footer')
    rows = head[1] + [r for body in bodies for r in body[2] + body[3]]
    cells = []
    for row in rows:
        if any(cell[2:4] != [1, 1] for cell in row[1]):
            raise ValueError('Chart data cannot contain merged cells')
        cells.append([plain(cell[4]).strip() for cell in row[1]])
    if not 2 <= len(specs) <= 5 or not 2 <= len(cells) <= 31:
        raise ValueError('Charts support 1-30 rows and 1-4 value series')
    if any(len(row) != len(specs) for row in cells):
        raise ValueError('Chart rows have inconsistent column counts')
    labels = [row[0] for row in cells[1:]]
    if any(not x or len(x) > 80 for x in labels + cells[0]) or len(set(labels)) != len(labels):
        raise ValueError('Chart labels must be nonempty, distinct and at most 80 characters')
    unit = attrs.get('unit', '')
    if not unit or len(unit) > 80:
        raise ValueError('Give the chart an explicit unit, e.g. unit="people"')
    if attrs.get('highlight') and attrs['highlight'] not in labels:
        raise ValueError('Chart highlight must match a category label')
    return {'kind': kind, 'unit': unit, 'labels': labels, 'headers': cells[0],
            'values': [[number(cell) for cell in row[1:]] for row in cells[1:]],
            'highlight': attrs.get('highlight'), 'caption': attrs.get('caption', '')}


def worker(payload):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    import io
    import textwrap
    data, colours = payload['data'], style(payload['style'])
    matplotlib.rcParams.update({'svg.fonttype': 'none', 'font.family': 'DejaVu Sans',
                                'font.size': 16, 'text.usetex': False, 'text.parse_math': False,
                                'svg.hashsalt': 'folioforge', 'axes.formatter.use_mathtext': False})
    fig = Figure(figsize=(12, 5.5), layout='constrained', facecolor=colours['background'])
    ax = fig.subplots()
    ax.set_facecolor(colours['background'])
    n, count = len(data['labels']), len(data['headers']) - 1
    x = list(range(n))
    for j in range(count):
        values = [row[j] for row in data['values']]
        colour = colours['series'][j % len(colours['series'])]
        if data['kind'] in ('bar', 'barh'):
            width = .8 / count
            positions = [i + (j - (count - 1) / 2) * width for i in x]
            palette = [colours['accent'] if label == data['highlight'] else colours['muted']
                       for label in data['labels']] if data['highlight'] and count == 1 else colour
            bars = (ax.barh(positions, values, height=width, color=palette, label=data['headers'][j+1])
                    if data['kind'] == 'barh' else
                    ax.bar(positions, values, width=width, color=palette, label=data['headers'][j+1]))
            if n * count <= 24:
                ax.bar_label(bars, labels=[f'{v:,.2f}'.rstrip('0').rstrip('.') for v in values], padding=5, fontsize=14)
        elif data['kind'] == 'line':
            ax.plot(x, values, marker='o', linewidth=2.5, color=colour, label=data['headers'][j+1])
        else:
            ax.scatter([number(label) for label in data['labels']], values, s=60, color=colour, label=data['headers'][j+1])
    wrapped = ['\n'.join(textwrap.wrap(label, 20)) for label in data['labels']]
    if data['kind'] == 'barh':
        ax.set_yticks(x, wrapped)
        ax.invert_yaxis()
        ax.set_xlabel(data['unit'])
        ax.margins(x=.18)
        ax.grid(axis='x', color=colours['grid'])
    else:
        if data['kind'] != 'scatter':
            ax.set_xticks(x, wrapped, rotation=40 if n > 8 else 0, ha='right' if n > 8 else 'center')
        else:
            ax.set_xlabel(data['headers'][0])
        ax.set_ylabel(data['unit'])
        ax.margins(y=.18)
        ax.grid(axis='y', color=colours['grid'])
    ax.set_axisbelow(True)
    ax.tick_params(colors=colours['ink'])
    ax.xaxis.label.set_color(colours['ink'])
    ax.yaxis.label.set_color(colours['ink'])
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('bottom', 'left'):
        ax.spines[side].set_color(colours['grid'])
    if count > 1:
        ax.legend(frameon=False, loc='upper center', bbox_to_anchor=(.5, 1.16), ncol=count)
    out = io.StringIO()
    fig.savefig(out, format='svg', metadata={'Date': None})
    return out.getvalue()


def render_svg(data, colours):
    payload = {'data': data, 'style': style(colours)}
    if importlib.util.find_spec('matplotlib'):
        return worker(payload)
    python = Path(os.environ.get('FOLIOFORGE_CHART_PYTHON',
                                 '~/.local/share/folioforge/charts/bin/python')).expanduser()
    if not python.is_file():
        raise ValueError('Chart backend missing. Run folioforge setup-charts, or install folioforge[charts]')
    result = subprocess.run([str(python), str(Path(__file__).resolve()), '--worker'],
                            input=json.dumps(payload), text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Chart renderer failed: ' + result.stderr[-2000:])
    return result.stdout


def prepare(node, output, colours=None):
    if isinstance(node, list):
        return [prepare(n, output, colours) for n in node]
    if not isinstance(node, dict):
        return node
    node = deepcopy(node)
    if 'chart' in classes(node):
        data = dataset(node)
        svg = render_svg(data, colours or {})
        name = hashlib.sha256(svg.encode()).hexdigest()[:16] + '-chart.svg'
        (output / 'assets').mkdir(exist_ok=True)
        (output / 'assets' / name).write_text(svg, encoding='utf-8')
        title = data['caption'] or f"{data['headers'][1]} ({data['unit']})"
        image = {'t':'Image', 'c':[['',[],[]],[{'t':'Str','c':title}],['assets/'+name,'']]}
        figure = {'t':'Figure', 'c':[['',[],[]],[None,[{'t':'Plain','c':[{'t':'Str','c':title}]}]],
                                   [{'t':'Plain','c':[image]}]]}
        return {'t':'Div', 'c':[['',['ff-media','ff-chart'],[]],[figure]]}
    return {k: prepare(v, output, colours) for k, v in node.items()}


def setup():
    target = Path('~/.local/share/folioforge/charts').expanduser()
    uv = shutil.which('uv')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not (target/'bin/python').is_file():
        subprocess.run([uv,'venv',str(target)] if uv else [sys.executable,'-m','venv',str(target)], check=True)
    subprocess.run([uv,'pip','install','--python',str(target/'bin/python'),'matplotlib>=3.7'] if uv else
                   [str(target/'bin/python'),'-m','pip','install','matplotlib>=3.7'], check=True)
    print('Local chart backend ready:', target)


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    # Parent provides only parsed chart data; never import a document or eval code.
    print(worker(json.load(sys.stdin)))
elif __name__ == '__main__' and sys.argv[1:] == ['--setup']:
    setup()
