"""Authenticated loopback editor. Markdown is the only persisted table source."""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
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


def serve(source, output, *, open_browser=True, port=0, idle_timeout=900):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise Error("Output already exists; choose a new output file")
    if not (ASSETS / "editor.js").is_file():
        raise Error("Editor bundle missing; update Folioforge with spacemacs-sync")
    if Path(source).stat().st_size > MAX_BYTES:
        raise Error('Selected table is too large (maximum 1 MiB)')
    fmt = 'org' if Path(source).suffix.lower() == '.org' else 'markdown'
    document = TableDocument(Path(source).read_text(encoding="utf-8"), fmt=fmt)
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
            self.end_headers()
            self.wfile.write(data)

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

        def do_GET(self):
            path = urlsplit(self.path).path
            if not self.authorized(api=path.startswith("/api/")):
                return
            if path == "/api/table":
                state["last"] = time.monotonic()
                self.reply(200, {"html": document.html, "name": Path(source).name})
            elif path == "/api/ping":
                state["last"] = time.monotonic()
                self.reply(200, {"ok": True})
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
                if self.path == "/api/cancel":
                    state["done"] = True
                    self.reply(200, {"cancelled": True})
                elif self.path == '/api/check':
                    self.reply(200, document.check_import(data['html']))
                elif self.path in {"/api/preview", "/api/save"}:
                    result = document.serialize(data["html"])
                    if self.path == "/api/save":
                        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(fd, "w", encoding="utf-8") as stream:
                            stream.write(result["markdown"])
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
        print(json.dumps({"event": "ready", "url": url, "port": server.server_port}), flush=True)
        if open_browser:
            webbrowser.open(url, new=1)
        while not state["done"] and time.monotonic() - state["last"] < idle_timeout:
            server.handle_request()
    print(json.dumps({"event": "saved" if state["saved"] else "cancelled", "output": str(output)}), flush=True)
    return 0 if state["saved"] else 2
