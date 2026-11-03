"""Opt-in local HTML canvases, isolated from the containing document."""
from copy import deepcopy
import html
from pathlib import Path
from urllib.parse import unquote, urlsplit

LIMIT = 2 * 1024 * 1024


def contains(node):
    if isinstance(node, list): return any(map(contains, node))
    if not isinstance(node, dict): return False
    return bool(node.get('t') == 'Div' and 'canvas' in node['c'][0][1]) or any(map(contains, node.values()))


def attributes(node):
    if node.get('t') == 'Div' and 'canvas' in node['c'][0][1]:
        values = dict(node['c'][0][2])
        if set(values) - {'src', 'title', 'interactive'}:
            raise ValueError('Canvas supports src, title and interactive attributes')
        if not values.get('src') or not values.get('title'):
            raise ValueError('Canvas requires a local HTML src and an accessible title')
        if values.get('interactive', 'false') not in ('true', 'false'):
            raise ValueError('Canvas interactive must be true or false')
        if node['c'][1]:
            raise ValueError('Put the canvas explanation outside its empty block')
        return values
    return None


def prepare(node, directory):
    if isinstance(node, list): return [prepare(n, directory) for n in node]
    if not isinstance(node, dict): return node
    values = attributes(node)
    if values:
        src = values['src']
        url = urlsplit(src)
        path = (Path(directory) / unquote(url.path)).resolve()
        if url.scheme or url.netloc or url.query or url.fragment or not path.is_relative_to(Path(directory).resolve()):
            raise ValueError('Canvas requires a bundled local HTML file, not a live URL')
        if path.suffix.lower() not in ('.html', '.htm') or not path.is_file() or path.stat().st_size > LIMIT:
            raise ValueError('Canvas requires a self-contained HTML file of at most 2 MiB')
        content = path.read_text(encoding='utf-8')
        interactive = values.get('interactive') == 'true'
        # CSP precedes the payload. The opaque iframe cannot access editor state,
        # cookies or local files. CSP blocks resource fetches, not all navigation;
        # interactive canvases must be trusted. Scripts are opt-in per canvas.
        policy = ("default-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; "
                  "connect-src 'none'; img-src data: blob:; font-src data:; media-src data: blob:; "
                  "style-src 'unsafe-inline'; script-src " + ("'unsafe-inline'" if interactive else "'none'"))
        payload = '<meta http-equiv="Content-Security-Policy" content="' + html.escape(policy, quote=True) + '">' + content
        title = html.escape(values['title'], quote=True)
        output = ('<figure class="ff-media ff-canvas"><dialog open class="ff-canvas-dialog" aria-label="' + title + '">'
                  '<button type="button" class="ff-canvas-expand" aria-label="Expand ' + title + '">Expand</button>'
                  '<iframe class="ff-canvas-frame" inert tabindex="-1" title="' + title + '" sandbox="' + ('allow-scripts' if interactive else '') + '" '
                  'referrerpolicy="no-referrer" srcdoc="' + html.escape(payload, quote=True) + '"></iframe>'
                  '</dialog><figcaption>' + title + '</figcaption></figure>')
        return {'t':'RawBlock', 'c':['html', output]}
    return {key:prepare(value, directory) for key,value in deepcopy(node).items()}
