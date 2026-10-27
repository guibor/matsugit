"""Editor-independent rendering. Quarto/Pandoc owns document parsing."""

from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote, unquote, urlsplit


class Error(Exception):
    pass


def run(argv, cwd=None, text=None):
    try:
        result = subprocess.run([str(a) for a in argv], cwd=cwd, input=text,
                                text=True, capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise Error(f"Executable not found: {argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise Error(f"{argv[0]} failed ({exc.returncode}): {(exc.stderr or exc.stdout).strip()}") from exc
    return result.stdout


def git(repo, *args):
    return run(["git", "-C", repo, *args]).strip()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Error(f"Expected a JSON object: {path}")
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative(value):
    path = Path(value)
    if path.is_absolute() or not path.parts or any(p.startswith(".") for p in path.parts):
        raise Error(f"Expected a non-hidden relative path: {value}")
    return path


def inside(root, value):
    root = Path(root).resolve()
    path = (root / relative(value)).resolve()
    if not path.is_relative_to(root):
        raise Error(f"Path escapes its root: {value}")
    return path


def config(source, overrides=None):
    source = Path(source).expanduser().resolve()
    try:
        root = Path(git(source.parent, "rev-parse", "--show-toplevel"))
    except Error:
        root = source.parent
    settings = {}
    global_file = Path(os.environ.get("FOLIOFORGE_CONFIG", "~/.config/folioforge/config.json")).expanduser()
    for path in (global_file, root / "folioforge.json"):
        if path.is_file():
            settings.update(read_json(path))
    settings.update({k: v for k, v in (overrides or {}).items() if v is not None})
    settings["source"] = source
    settings["source_root"] = root
    settings["repo"] = (root / Path(settings.get("repo", root)).expanduser()).resolve()
    themes = settings.get("themes_dir", os.environ.get("FOLIOFORGE_THEMES_DIR", "~/.config/folioforge/themes"))
    settings["themes_dir"] = (root / Path(themes).expanduser()).resolve()
    for key, default in (("theme", "default"), ("branch", "main"), ("remote", "origin"),
                         ("site_dir", "folioforge-site"), ("quarto", os.environ.get("QUARTO", "quarto"))):
        settings.setdefault(key, default)
    settings.setdefault("slug", re.sub(r"[^\w-]+", "-", source.stem.lower()).strip("-"))
    relative(settings["site_dir"])
    if len(relative(settings["slug"]).parts) != 1:
        raise Error("A slug must be a single directory name")
    return settings


class ResourceHTML(HTMLParser):
    """Keep ordinary HTML (including merged cells); reject active HTML inputs."""
    def __init__(self, resource):
        super().__init__(convert_charrefs=False)
        self.resource = resource
        self.output = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "iframe", "object", "embed", "base", "link", "style", "meta"}:
            raise Error(f"Active HTML <{tag}> is not supported in document source")
        values = []
        for key, value in attrs:
            if key.startswith("on") or key in {"srcdoc", "srcset", "style"}:
                raise Error(f"Unsupported HTML attribute: {key}")
            if key in {"src", "href", "poster"} and value:
                value = self.resource(value)
            values.append(key if value is None else f'{key}="{html.escape(value, quote=True)}"')
        self.output.append("<" + tag + (" " + " ".join(values) if values else "") + ">")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.output.append(f"</{tag}>")

    def handle_data(self, text):
        self.output.append(text)

    def handle_entityref(self, name):
        self.output.append(f"&{name};")

    def handle_charref(self, name):
        self.output.append(f"&#{name};")

    def handle_comment(self, data):
        self.output.append(f"<!--{data}-->")


def install_theme(settings, output):
    name = settings["theme"]
    theme = inside(settings["themes_dir"], name)
    if name == "default" and not theme.exists():
        theme = Path(__file__).parent / "themes/default"
    manifest = read_json(theme / "theme.json")
    (output / "theme").mkdir(parents=True, exist_ok=True)
    write_json(output / "theme/theme.json", manifest)
    for name in [manifest["document"], manifest["slides"], *manifest.get("assets", [])]:
        source = inside(theme, name)
        if not source.is_file():
            raise Error(f"Missing theme file: {source}")
        dest = inside(output / "theme", name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    return manifest


def normalize(settings, output):
    source = settings["source"]
    fmt = {".md": "markdown", ".markdown": "markdown", ".qmd": "markdown", ".org": "org"}.get(source.suffix.lower())
    if not fmt:
        raise Error("Supported sources: .md, .markdown, .qmd and .org")
    pandoc = [settings["quarto"], "pandoc"]
    ast = json.loads(run([*pandoc, "-f", fmt, "-t", "json"], text=source.read_text(encoding="utf-8")))
    # Do not propagate executable filters, includes, templates, or project settings.
    title = ast.get("meta", {}).get("title")
    if title and title.get("t") == "MetaInlines":
        ast["blocks"].insert(0, {"t": "Header", "c": [1, ["", [], []], title["c"]]})
    ast["meta"] = {}

    def resource(value):
        url = urlsplit(value)
        if url.scheme in {"https", "http", "mailto", "tel"} or value.startswith("#"):
            return value
        if url.scheme or url.netloc or not url.path:
            raise Error(f"Unsupported resource URL: {value}")
        raw = Path(unquote(url.path))
        path = (source.parent / raw).resolve()
        if raw.is_absolute() or not path.is_relative_to(settings["source_root"]) or any(p.startswith(".") for p in path.relative_to(settings["source_root"]).parts):
            raise Error(f"Resource outside the source project or hidden: {value}")
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".csv", ".txt", ".md", ".mp4", ".webm", ".mp3"}:
            raise Error(f"Missing or unsupported attachment: {value}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        name = path.name if path.name.startswith(digest + "-") else digest + "-" + path.name
        (output / "assets").mkdir(exist_ok=True)
        shutil.copyfile(path, output / "assets" / name)
        return "assets/" + quote(name) + ("#" + url.fragment if url.fragment else "")

    def visit(node):
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        kind = node.get("t")
        if kind in {"Image", "Link"}:
            node["c"][-1][0] = resource(node["c"][-1][0])
        if kind in {"RawBlock", "RawInline"} and node["c"][0] == "html":
            parser = ResourceHTML(resource)
            parser.feed(node["c"][1])
            parser.close()
            node["c"][1] = "".join(parser.output)
        node = {key: visit(value) for key, value in node.items()}
        if kind == "Table":
            _, _, _, head, bodies, foot = node["c"]
            rows = head[1] + foot[1] + [row for body in bodies for row in body[2] + body[3]]
            if any(cell[2] != 1 or cell[3] != 1 for row in rows for cell in row[1]):
                table = run([*pandoc, "-f", "json", "-t", "html"], text=json.dumps(dict(ast, blocks=[node])))
                return {"t": "RawBlock", "c": ["html", table]}
        return node

    ast = visit(ast)
    markdown = run([*pandoc, "-f", "json", "-t", "markdown", "--wrap=none"], text=json.dumps(ast))
    (output / "source.md").write_text(markdown, encoding="utf-8")


def render(settings, output, edit_url=None):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise Error(f"Output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    theme = install_theme(settings, output)
    normalize(settings, output)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    links = '<a href="slides.html">Slides</a> <a href="source.md">Source</a>'
    if edit_url:
        links += f' <a href="{html.escape(edit_url, quote=True)}">Edit source</a>'
    (output / "navigation.html").write_text(
        f'<nav class="folioforge-nav" aria-label="Document formats">{links}'
        f'<span>Updated <time datetime="{stamp}">{stamp}</time></span></nav>', encoding="utf-8")
    metadata = {
        "project": {"type": "default", "render": ["source.md"]},
        "execute": {"enabled": False, "eval": False},
        "engine": "markdown",
        "format": {
            "html": {"theme": "default", "css": "theme/" + theme["document"], "toc": True,
                     "embed-resources": True, "pagetitle": settings["source"].stem,
                     "include-before-body": "navigation.html"},
            "revealjs": {"theme": ["default", "theme/" + theme["slides"]], "embed-resources": True,
                         "slide-level": 2, "width": 1280, "height": 720, "scrollable": True,
                         "slide-number": "c/t", "transition": "none",
                         "footer": '<a class="folioforge-document-link" href="index.html" aria-label="Read the document version">Document</a>'},
        },
    }
    write_json(output / "_quarto.yml", metadata)
    for fmt, filename in (("html", "index.html"), ("revealjs", "slides.html")):
        print(f"Rendering {fmt}: {filename}", flush=True)
        run([settings["quarto"], "render", "source.md", "--to", fmt, "--output", filename, "--no-execute"], cwd=output)
        if not (output / filename).is_file():
            raise Error(f"Renderer did not produce {filename}")
    for name in (".quarto", "source_files", "index_files", "slides_files"):
        if (output / name).is_dir():
            shutil.rmtree(output / name)
    manifest = {"version": 1, "theme": settings["theme"], "updated": stamp, "edit_url": edit_url,
                "source_sha256": hashlib.sha256((output / "source.md").read_bytes()).hexdigest(),
                "files": sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file())}
    write_json(output / "folioforge-manifest.json", manifest)
    return manifest
