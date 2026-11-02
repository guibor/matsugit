"""Authenticated loopback editor with recoverable, single-writer table sessions."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from urllib.parse import urlsplit
import webbrowser

from .converter import converter, convert
from .core import Error

ASSETS = Path(__file__).parent / "editor_assets"
MAX_BYTES = 1024 * 1024
ALLOWED = {"Table", "TableBody", "Str", "Space", "SoftBreak", "LineBreak", "Plain", "Para",
           "Strong", "Emph", "Strikeout", "Code", "Link", "BulletList", "OrderedList",
           "AlignDefault", "AlignLeft", "AlignRight", "AlignCenter", "ColWidth", "ColWidthDefault",
           "DefaultStyle", "Decimal", "DefaultDelim", "Period", "OneParen", "TwoParens"}


def nodes(value):
    if isinstance(value, dict):
        if "t" in value:
            yield value
        for item in value.values():
            yield from nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from nodes(item)


def rows(table):
    _, _, _, head, bodies, foot = table["c"]
    return head[1] + [row for body in bodies for row in body[2] + body[3]] + foot[1]


def validate(ast):
    if len(ast["blocks"]) != 1 or ast["blocks"][0]["t"] != "Table":
        raise Error("Select exactly one Markdown pipe/grid table, without surrounding prose")
    table = ast["blocks"][0]
    if table["c"][1] != [None, []]:
        raise Error("Keep the table caption outside the selected table")
    found = list(nodes(table))
    if sum(n["t"] == "Table" for n in found) != 1:
        raise Error("Nested tables are not supported")
    for node in found:
        if node["t"] not in ALLOWED:
            raise Error(f"Unsupported table content: {node['t']}. The source was not changed.")
        if node["t"] == "Link":
            url = urlsplit(node["c"][-1][0])
            if url.scheme not in {"", "http", "https", "mailto", "tel"}:
                raise Error("Unsupported link scheme")
    all_rows = rows(table)
    cells = [cell for row in all_rows for cell in row[1]]
    if not cells or len(cells) > 4000 or len(all_rows) > 500:
        raise Error("Table editor supports 1-4000 cells and at most 500 rows")
    if any(not 1 <= cell[2] <= 500 or not 1 <= cell[3] <= 100 for cell in cells):
        raise Error("Invalid merged-cell dimensions")
    return table


def plain(value):
    return " ".join(" ".join(n["c"] if n["t"] == "Str" else n["c"][1]
                              for n in nodes(value) if n["t"] in {"Str", "Code"}).split())


def signature(table):
    alignments = [column[0] for column in table['c'][2]]
    content = [[(cell[2], cell[3], plain(cell[4]),
              [(n["t"], n['c'][1] if n['t'] == 'Code' else plain(n),
                n['c'][0] if n['t'] == 'OrderedList' else n["c"][-1] if n["t"] == "Link" else None)
               for n in nodes(cell[4]) if n["t"] in {"Strong", "Emph", "Strikeout", "Code", "Link", "BulletList", "OrderedList"}])
             for cell in row[1]] for row in rows(table)]
    blocks = [[['Text' if block['t'] in {'Para', 'Plain'} else block['t'] for block in cell[4]]
               for cell in row[1]] for row in rows(table)]
    return (len(table['c'][3][1]), alignments, content, blocks)


class TableHTML(HTMLParser):
    """Reject unsupported HTML rather than silently discard pasted data/styles."""
    def handle_starttag(self, tag, attrs):
        if tag not in {"table", "thead", "tbody", "tfoot", "tr", "td", "th", "p", "strong", "b",
                       "em", "i", "s", "del", "code", "a", "br", "ul", "ol", "li", "colgroup", "col"}:
            raise Error(f"Unsupported table HTML: {tag}")
        for key, value in attrs:
            if key not in {"rowspan", "colspan", "colwidth", "data-colwidth", "style", "href", "title", "rel", "target", "start"}:
                raise Error(f"Unsupported table attribute: {key}")
            if key == "style" and not all(re.fullmatch(r"\s*(?:(?:min-width|width):\s*\d+(?:px|%)|text-align:\s*(?:left|center|right))\s*", part)
                                           for part in value.split(";") if part.strip()):
                raise Error("Only column widths and text alignment are accepted as inline styles")
            if key == "href" and urlsplit(value).scheme not in {"", "http", "https", "mailto", "tel"}:
                raise Error("Unsupported link scheme")

    handle_startendtag = handle_starttag


class TableDocument:
    def __init__(self, source, command=None, fmt='markdown'):
        if len(source.encode("utf-8")) > MAX_BYTES:
            raise Error("Selected table is too large (maximum 1 MiB)")
        self.command = command or converter()
        self.format = fmt
        if fmt == 'org':
            if re.search(r'^\s*#\+TBLFM:', source, re.I | re.M):
                raise Error('Use native Org tools for formula tables; visual edits cannot update formula references')
            from .source import read
            self.ast = read(source, fmt, self.command)
        elif fmt == 'markdown':
            self.ast = json.loads(convert(self.command, source, "markdown", "json"))
        else:
            raise Error('Table format must be markdown or org')
        self.table = validate(self.ast)
        self.html = convert(self.command, json.dumps(self.ast), "json", "html")

    def check_import(self, html):
        if not isinstance(html, str) or len(html.encode('utf-8')) > MAX_BYTES:
            raise Error('Expected table HTML up to 1 MiB')
        table = validate(json.loads(convert(self.command, html, 'html', 'json')))
        if signature(table) != signature(self.table):
            raise Error('The visual editor cannot preserve this table exactly. Source unchanged; use the source editor.')
        return {'ok': True}

    def serialize(self, html):
        if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_BYTES:
            raise Error("Expected table HTML up to 1 MiB")
        parser = TableHTML()
        parser.feed(html)
        parser.close()
        ast = json.loads(convert(self.command, html, "html", "json"))
        table = validate(ast)
        cells = [cell for row in rows(table) for cell in row[1]]
        grid = (any(cell[2] != 1 or cell[3] != 1 or len(cell[4]) > 1 for cell in cells)
                or len(table["c"][3][1]) != 1
                or any(n["t"] in {"BulletList", "OrderedList", "LineBreak"} for cell in cells for n in nodes(cell[4])))
        writer = ("markdown-pipe_tables-simple_tables-multiline_tables" if grid
                  else "markdown-grid_tables-simple_tables-multiline_tables")
        text = convert(self.command, json.dumps(ast), "json", writer, "--wrap=auto", "--columns=100").strip() + "\n"
        reparsed = json.loads(convert(self.command, text, "markdown", "json"))
        if signature(validate(reparsed)) != signature(table):
            raise Error("This conversion would change cells or formatting. Nothing was saved.")
        if any(n["t"] in {"RawInline", "RawBlock"} for n in nodes(reparsed)):
            raise Error("Cannot represent this table without HTML. Nothing was saved.")
        format_name = 'grid' if grid else 'pipe'
        if self.format == 'org':
            from .source import read, write_org
            native = write_org(ast, self.command)
            if not grid and signature(validate(read(native, 'org', self.command))) == signature(table):
                text, format_name = native, 'org'
            else:
                text = '#+begin_export markdown\n' + text + '#+end_export\n'
                format_name = 'org-grid'
            if signature(validate(read(text, 'org', self.command))) != signature(table):
                raise Error('This Org conversion would change the table. Nothing was saved.')
        return {"markdown": text, "format": format_name, "rows": len(rows(table)),
                "columns": len(table["c"][2])}


class TableSession:
    """Checkpoints are not commits: only explicit Save produces the output file."""
    def __init__(self, document, source, output):
        self.document = document
        self.output = Path(output)
        self.path = self.output.with_name(self.output.name + '.draft.json')
        self.source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
        self.draft = None
        self.client = None
        self.revision = -1
        self.attached = False
        self.seen = 0
        self.command = None
        self.import_document = document
        if self.path.is_symlink():
            raise Error('Recovery file is a symlink; left untouched')
        if self.path.exists():
            if self.path.stat().st_size > MAX_BYTES * 3:
                raise Error('Recovery file is too large; left untouched')
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or data.get('version') != 1 or data.get('source_sha256') != self.source_hash:
                raise Error('Recovery belongs to a different source table; left untouched')
            result = document.serialize(data['html'])
            self.draft = dict(data, markdown=result['markdown'])

    def open(self, client):
        if not isinstance(client, str) or not re.fullmatch(r'[A-Za-z0-9-]{16,80}', client):
            raise Error('Invalid editor identity')
        self.client, self.revision, self.attached = client, -1, True
        self.seen, self.command = time.monotonic(), None
        self.import_document = (TableDocument(self.draft['markdown'], self.document.command, self.document.format)
                                if self.draft else self.document)
        return {'html': self.draft['html'] if self.draft else self.document.html,
                'recovered': bool(self.draft)}

    def owns(self, client):
        return bool(self.client and client == self.client)

    def checkpoint(self, html, revision):
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise Error('Invalid draft revision')
        if revision < self.revision:
            raise Error('An older draft cannot replace a newer edit')
        if revision == self.revision:
            if not self.draft or html != self.draft['html']:
                raise Error('Conflicting draft revision')
            return self.draft
        result = self.document.serialize(html)
        data = {'version': 1, 'source_sha256': self.source_hash, 'html': html,
                'markdown': result['markdown']}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                         prefix='.matsugit-draft-', delete=False) as stream:
            temp = Path(stream.name)
            try:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)
        self.draft, self.revision = data, revision
        return data

    def save(self, html):
        result = self.document.serialize(html)
        fd = os.open(self.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(result['markdown'])
        return result

    def status(self):
        return {'has_draft': bool(self.draft),
                'attached': self.attached and time.monotonic() - self.seen < 75,
                'command': self.command}


def serve(source, output, *, open_browser=True, port=0, idle_timeout=900):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise Error("Output already exists; choose a new output file")
    if not (ASSETS / "editor.js").is_file():
        raise Error("Editor bundle missing; update matsugit with spacemacs-sync")
    if Path(source).stat().st_size > MAX_BYTES:
        raise Error('Selected table is too large (maximum 1 MiB)')
    fmt = 'org' if Path(source).suffix.lower() == '.org' else 'markdown'
    text = Path(source).read_text(encoding="utf-8")
    document = TableDocument(text, fmt=fmt)
    session = TableSession(document, text, output)
    token = secrets.token_urlsafe(32)
    state = {"done": False, "saved": False, "last": time.monotonic()}
    origin = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body, content_type="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            try:
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Closing a tab must not abort its checkpoint or the server.

        def authorized(self, api=False):
            if self.headers.get("Host") != urlsplit(origin).netloc:
                self.reply(403, {"error": "Invalid host"})
                return False
            if self.headers.get("Origin") not in {None, origin}:
                self.reply(403, {"error": "Invalid origin"})
                return False
            if api and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.reply(403, {"error": "Invalid session"})
                return False
            return True

        def owner(self):
            if not session.owns(self.headers.get('X-matsugit-Client')):
                self.reply(409, {'error': 'This editor was replaced by another tab. Resume from your source editor.'})
                return False
            session.seen = time.monotonic()
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            if not self.authorized(api=path.startswith("/api/")):
                return
            if path == "/api/table":
                state["last"] = time.monotonic()
                self.reply(200, {"html": session.draft['html'] if session.draft else document.html,
                                 "name": Path(source).name})
            elif path == '/api/status':
                self.reply(200, session.status())
            elif path == "/api/ping":
                if not self.owner():
                    return
                session.attached = True
                state["last"] = time.monotonic()
                self.reply(200, session.status())
            elif path in {"/", "/editor.js", "/editor.css"}:
                name = "index.html" if path == "/" else path[1:]
                mime = {"index.html": "text/html; charset=utf-8", "editor.js": "text/javascript", "editor.css": "text/css"}[name]
                self.reply(200, (ASSETS / name).read_bytes(), mime)
            else:
                self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.authorized(api=True):
                return
            if self.headers.get("Content-Type") != "application/json":
                self.reply(415, {"error": "Expected JSON"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= MAX_BYTES:
                    raise Error("Request too large")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise Error('Expected a JSON object')
                state["last"] = time.monotonic()
                if self.path == '/api/open':
                    self.reply(200, dict(session.open(data.get('client')), name=Path(source).name))
                    return
                if self.path == '/api/control':
                    action = data.get('action')
                    if action == 'save':
                        if session.status()['attached']:
                            session.command = 'save'
                        self.reply(200, session.status())
                    elif action == 'save-draft':
                        if not session.draft:
                            raise Error('No saved draft is available; resume the editor')
                        result = session.save(session.draft['html'])
                        state.update(done=True, saved=True)
                        self.reply(200, result)
                    elif action == 'cancel':
                        session.path.unlink(missing_ok=True)
                        state['done'] = True
                        self.reply(200, {'cancelled': True})
                    else:
                        raise Error('Unknown session action')
                    return
                if not self.owner():
                    return
                if self.path == "/api/cancel":
                    session.path.unlink(missing_ok=True)
                    state["done"] = True
                    self.reply(200, {"cancelled": True})
                elif self.path in ('/api/draft', '/api/detach'):
                    if 'html' in data:
                        session.checkpoint(data['html'], data.get('revision'))
                        print(json.dumps({'event': 'draft', 'path': str(session.path)}), flush=True)
                    if self.path == '/api/detach':
                        session.attached = False
                    self.reply(200, {'checkpointed': session.revision})
                elif self.path == '/api/check':
                    self.reply(200, session.import_document.check_import(data['html']))
                elif self.path in {"/api/preview", "/api/save"}:
                    result = (session.save(data['html']) if self.path == '/api/save'
                              else document.serialize(data['html']))
                    if self.path == "/api/save":
                        state.update(done=True, saved=True)
                    self.reply(200, result)
                else:
                    self.reply(404, {"error": "Not found"})
            except (Error, OSError, ValueError, KeyError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})

    class BoundedServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

    with BoundedServer(("127.0.0.1", port), Handler) as server:
        server.timeout = 1
        origin = f"http://127.0.0.1:{server.server_port}"
        url = origin + "/#" + token
        print(json.dumps({"event": "ready", "url": url, "port": server.server_port,
                          'protocol': 2, 'draft': str(session.path)}), flush=True)
        if open_browser:
            webbrowser.open(url, new=1)
        while not state["done"] and time.monotonic() - state["last"] < idle_timeout:
            server.handle_request()
    suspended = not state['done'] and session.draft
    print(json.dumps({"event": "saved" if state["saved"] else 'suspended' if suspended else "cancelled",
                      "output": str(output), 'draft': str(session.path)}), flush=True)
    return 0 if state["saved"] else 3 if suspended else 2
