"""Altair preparation and offline Vega-Lite export, never document Python execution."""
from copy import deepcopy
import json
import math
import re
import xml.etree.ElementTree as ET


def validate(spec):
    if not isinstance(spec, dict) or len(json.dumps(spec)) > 1_000_000:
        raise ValueError('Vega-Lite needs a JSON object of at most 1 MB')
    count = 0

    def walk(value, depth=0, literal=False):
        nonlocal count
        count += 1
        if depth > 40 or count > 50_000:
            raise ValueError('Vega-Lite specification is too complex')
        if isinstance(value, dict):
            # Static, self-contained exhibits only. Compose multiple views in Markdown.
            forbidden = set() if literal else set(value) & {'url', 'href', 'expr', 'params', 'facet', 'repeat',
                                                           'concat', 'hconcat', 'vconcat'}
            if forbidden:
                raise ValueError('Unsupported Vega-Lite option: ' + ', '.join(sorted(forbidden)))
            mark = value.get('mark')
            if not literal and (mark == 'image' or isinstance(mark, dict) and mark.get('type') == 'image'):
                raise ValueError('Vega-Lite image marks are not allowed; use Markdown images')
            for k, v in value.items():
                if not literal and k in ('width', 'height') and (not isinstance(v, (int, float)) or not 40 <= v <= 2400):
                    raise ValueError('Vega-Lite dimensions must be numeric, between 40 and 2400')
                walk(v, depth + 1, literal or k in ('values', 'datasets'))
        elif isinstance(value, list):
            if len(value) > 5000:
                raise ValueError('Vega-Lite supports at most 5000 items per array')
            for v in value:
                walk(v, depth + 1, literal)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Vega-Lite numbers must be finite')

    walk(spec)
    return deepcopy(spec)


def table_spec(data):
    import altair as alt
    rows = [{'category': label, 'series': data['headers'][j + 1], 'value': value,
             'position': i, 'xvalue': float(label) if data['kind'] == 'scatter' else i}
            for i, (label, values) in enumerate(zip(data['labels'], data['values']))
            for j, value in enumerate(values)]
    base = alt.Chart(alt.Data(values=rows))
    category = alt.X('category:N', title=None, sort=data['labels'],
                     axis=alt.Axis(labelAngle=-35 if len(rows) > 8 else 0))
    value = alt.Y('value:Q', title=data['unit'], scale=alt.Scale(zero=True))
    colour = alt.Color('series:N', title=None, sort=data['headers'][1:],
                       legend=None if len(data['headers']) == 2 else alt.Legend(orient='top'))
    kind = data['kind']
    if kind == 'barh':
        chart = base.mark_bar().encode(y=alt.Y('category:N', title=None, sort=data['labels']),
                x=alt.X('value:Q', title=data['unit']), yOffset='series:N', color=colour)
    elif kind in ('bar', 'stacked', 'stacked100'):
        if kind != 'bar':
            value = alt.Y('value:Q', title=data['unit'] if kind == 'stacked' else 'Share',
                          stack='normalize' if kind == 'stacked100' else 'zero',
                          axis=alt.Axis(format='.0%') if kind == 'stacked100' else alt.Axis())
        chart = base.mark_bar().encode(x=category, y=value, color=colour)
        if kind == 'bar':
            chart = chart.encode(xOffset='series:N')
    elif kind == 'line':
        chart = base.mark_line(point=True, strokeWidth=3).encode(
            x=category, y=value, color=colour, order='position:Q')
    else:
        chart = base.mark_circle(size=90).encode(
            x=alt.X('xvalue:Q', title=data['headers'][0], scale=alt.Scale(zero=False)), y=value, color=colour)
    if data.get('highlight') and len(data['headers']) == 2 and kind in ('bar', 'barh'):
        chart = chart.encode(color=alt.condition(alt.datum.category == data['highlight'],
                                                alt.value(data['colours']['accent']),
                                                alt.value(data['colours']['muted'])))
    if kind in ('bar', 'barh') and len(rows) <= 24:
        labels = chart.mark_text(**({'align': 'left', 'dx': 6} if kind == 'barh' else
                                    {'baseline': 'bottom', 'dy': -5})).encode(
            text=alt.Text('value:Q', format=',.3~g'), color=alt.value(data['colours']['ink']))
        chart = chart + labels
    return chart.to_dict()


def render(data, colours, width):
    import altair as alt
    import vl_convert as vlc
    spec = validate(data['spec']) if 'spec' in data else table_spec(dict(data, colours=colours))
    # Explicit slot sizes keep labels readable in columns, rather than shrinking a full chart.
    spec['width'] = width
    spec['height'] = 340 if width >= 700 else 300
    spec['autosize'] = {'type': 'fit', 'contains': 'padding'}
    spec['background'] = colours['background']
    config = spec.setdefault('config', {})
    defaults = {
        'font': 'DejaVu Sans',
        'view': {'stroke': None},
        'axis': {'labelFontSize': 17, 'titleFontSize': 18, 'titleFontWeight': 500,
                 'labelColor': colours['ink'], 'titleColor': colours['ink'],
                 'gridColor': colours['grid'], 'domainColor': colours['grid'],
                 'tickColor': colours['grid'], 'labelLimit': max(100, width // 3),
                 'titlePadding': 12},
        'legend': {'labelFontSize': 16, 'titleFontSize': 17, 'labelColor': colours['ink']},
        'range': {'category': colours['series']},
        'mark': {'color': colours['accent']},
        'text': {'fontSize': 17, 'color': colours['ink']},
    }
    for key, value in defaults.items():
        if isinstance(value, dict):
            config[key] = dict(value, **config.get(key, {}))
        else:
            config.setdefault(key, value)
    validate(spec)
    # Altair uses its bundled schema; no remote schema or data is fetched.
    alt.Chart.from_dict(spec, validate=True)
    svg = vlc.vegalite_to_svg(spec, allowed_base_urls=[], show_warnings=True)
    root = ET.fromstring(svg)
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] in ('script', 'foreignObject', 'image'):
            raise ValueError('Vega-Lite produced unsupported active content')
        if any(k.rsplit('}', 1)[-1] == 'href' and not v.startswith('#') for k, v in element.attrib.items()):
            raise ValueError('Vega-Lite produced an external resource')
        if any(not match.strip(' \t\r\n\"\x27').startswith('#')
               for value in element.attrib.values() for match in re.findall(r'url\(([^)]*)\)', value, re.I)):
            raise ValueError('Vega-Lite produced an external paint resource')
    return {'svg': svg, 'spec': spec, 'backend': 'altair'}
