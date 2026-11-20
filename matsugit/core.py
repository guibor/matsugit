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
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote, unquote, urlsplit

if __package__:
    from .compat import env, existing, global_config, project_configs
    from .layout import metadata as display_metadata, slides as slide_layout, plain
    from .components import prepare as evidence_components
    from .canvas import prepare as canvas_components
    from .charts import prepare as chart_components
    from .diagrams import prepare as diagram_components
    from .handout import prepare as handout_layout
else:  # The standalone CI bundle imports core directly.
    from compat import env, existing, global_config, project_configs
    from layout import metadata as display_metadata, slides as slide_layout, plain
    from components import prepare as evidence_components
    from canvas import prepare as canvas_components
    from charts import prepare as chart_components
    from diagrams import prepare as diagram_components
    from handout import prepare as handout_layout


class Error(Exception):
    pass


def resource_limit(name, default):
    value = os.environ.get(name, str(default))
    if not re.fullmatch(r'[1-9][0-9]{0,11}', value):
        raise Error(f'{name} must be a positive byte limit')
    return int(value)


def bounded_source(source, text=None):
    limit = resource_limit('MATSUGIT_MAX_SOURCE_BYTES', 8 * 1024 * 1024)
    message = f'Document exceeds the {limit} byte source limit (MATSUGIT_MAX_SOURCE_BYTES)'
    if text is not None:
        if len(text) > limit or len(text.encode('utf-8')) > limit:
            raise Error(message)
        return text
    if not source.is_file():
        raise Error('Document must be a regular file')
    with source.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise Error('Document must be a regular file')
        if info.st_size > limit:
            raise Error(message)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise Error(message)
    return data.decode('utf-8')


def copy_asset(source, output, limit):
    """Hash and copy the same bounded stream; never leave a partial attachment."""
    if not source.is_file():
        raise Error('Attachment must be a regular file')
    with source.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Error(f'Attachment exceeds its size or remaining total budget: {source.name}')
        output.mkdir(exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.asset-', dir=output)
        count, digest = 0, hashlib.sha256()
        try:
            with os.fdopen(fd, 'wb') as destination:
                while chunk := stream.read(min(1024 * 1024, limit - count + 1)):
                    count += len(chunk)
                    if count > limit:
                        raise Error(f'Attachment grew beyond its size budget: {source.name}')
                    digest.update(chunk)
                    destination.write(chunk)
            prefix = digest.hexdigest()[:16] + '-'
            name = source.name if source.name.startswith(prefix) else prefix + source.name
            os.replace(temporary, output / name)
            return name, count
        finally:
            Path(temporary).unlink(missing_ok=True)


def expand_runtime(directory):
    """Large runtime assets are stored compressed (name.js.gz) to keep the package
    small. Write each one out as the file the page loads, and drop the .gz.
    A runtime without compressed files (an installed CI copy) is left as it is."""
    import gzip
    for packed in sorted(Path(directory).glob('*.gz')):
        target = packed.with_suffix('')
        target.write_bytes(gzip.decompress(packed.read_bytes()))
        packed.unlink()


def run(argv, cwd=None, text=None):
    try:
        result = subprocess.run([str(a) for a in argv], cwd=cwd, input=text,
                                text=True, encoding='utf-8', capture_output=True, check=True)
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
    shared = {}
    project = {}
    project_paths = project_configs(root)
    for path in (*global_config(), *project_paths):
        if path.is_file():
            data = read_json(path)
            settings.update(data)
            if path in project_paths:
                project.update(data)
            else:
                shared.update(data)
    overrides = overrides or {}
    target = overrides.get('target') or project.get('publish_target')
    if not target and not overrides.get('repo'):
        # An already-published source (including a symlink visit) stays in its
        # own target instead of being copied into the host's default target.
        matches = [name for name, profile in settings.get('publish_targets', {}).items()
                   if isinstance(profile, dict) and profile.get('repo')
                   and Path(profile['repo']).expanduser().resolve() == root]
        if len(matches) == 1:
            target = matches[0]
    if not target and not (overrides.get('repo') or project.get('repo')):
        target = settings.get('default_publish_target')
    if target and (overrides.get('target') or overrides.get('command') in ('publish', 'publish-plan', 'setup-ci')):
        from .targets import resolve
        settings.update(resolve(target, settings))
        settings['target'] = target
    settings.update({k: v for k, v in (overrides or {}).items() if v is not None})
    settings['move_source'] = bool(overrides.get('move_source'))  # Never enabled by document/project configuration.
    settings["source"] = source
    settings["source_root"] = root
    settings["repo"] = (root / Path(settings.get("repo", root)).expanduser()).resolve()
    installed_themes = env("MATSUGIT_THEMES_DIR",
                          existing("~/.config/matsugit/themes", "~/.config/folioforge/themes"))
    themes = settings.get("themes_dir", installed_themes)
    settings["themes_dir"] = (root / Path(themes).expanduser()).resolve()
    origin = ('override' if overrides.get('themes_dir') is not None else
              'project' if project.get('themes_dir') is not None else 'shared')
    # Preserve the shared library when a project supplies additional themes.
    roots = [(origin, themes), ('project', project.get('themes_dir')),
             ('shared', shared.get('themes_dir')), ('shared', installed_themes)]
    settings['_theme_roots'] = [(kind, (root / Path(value).expanduser()).resolve())
                               for kind, value in roots if value is not None]
    # Preserve existing publication paths, hence existing links and CI targets.
    site_dir = existing(settings['repo'] / 'matsugit-site', settings['repo'] / 'folioforge-site').name
    for key, default in (("theme", env("MATSUGIT_DEFAULT_THEME", "default")), ("branch", "main"), ("remote", "origin"),
                         ("site_dir", site_dir), ("quarto", os.environ.get("QUARTO", "quarto"))):
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


def theme_roots(settings):
    roots, seen = [], set()
    for origin, directory in [*settings.get('_theme_roots', [('configured', settings['themes_dir'])]),
                              ('built-in', Path(__file__).parent / 'themes')]:
        directory = Path(directory).resolve()
        if directory not in seen:
            roots.append((origin, directory))
            seen.add(directory)
    return roots


def resolve_theme(settings, name):
    """One ordered lookup for discovery, inheritance, preview and exports."""
    if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', name):
        raise Error('Invalid theme name; use letters, numbers, hyphens or underscores')
    attempted = []
    for origin, root in theme_roots(settings):
        attempted.append(f'{origin}: {root / name / "theme.json"}')
        candidate = root / name
        if not candidate.exists() and not candidate.is_symlink():
            continue
        try:
            directory = inside(root, name)
            manifest = inside(directory, 'theme.json')
            with manifest.open(encoding='utf-8') as stream:
                raw = stream.read(65537)
            if len(raw.encode('utf-8')) > 65536:
                raise Error('theme.json exceeds 64 KiB')
            data = json.loads(raw)
            if not isinstance(data, dict) or not (data.get('extends') or (data.get('document') and data.get('slides'))):
                raise Error('theme.json needs document and slides, or extends')
        except (Error, OSError, ValueError) as error:
            raise Error(f'Theme {name!r} at {candidate} ({origin}) is invalid: {error}. '
                        'Repair that theme and Refresh; no other theme was substituted.') from error
        return {'name': name, 'origin': origin, 'path': str(directory)}, data
    raise Error(f'Theme {name!r} was not found. Searched ' + '; '.join(attempted) +
                '. Install it in a listed theme directory or correct themes_dir, then Refresh. '
                'Your selected theme was not changed.')


def theme_options(settings):
    """List names and their actual origins without rendering or reading source."""
    candidates, details = set(), {}
    for _, root in theme_roots(settings):
        if root.is_dir():
            candidates.update(p.name for p in root.iterdir())
    for name in sorted(candidates):
        try:
            details[name], _ = resolve_theme(settings, name)
        except (Error, OSError, ValueError):
            continue
    return {'default': settings['theme'], 'themes': sorted(details), 'details': details}


def install_theme(settings, output):
    def resolve(name, parents=()):
        if name in parents or len(parents) >= 8:
            raise Error('Theme inheritance cycle or depth exceeds eight')
        location, own = resolve_theme(settings, name)
        theme = Path(location['path'])
        if not parents:
            settings['_resolved_theme'] = location
        manifest, files = resolve(own['extends'], (*parents, name)) if own.get('extends') else ({}, {})
        for key in ('document', 'slides', 'charts', 'diagrams', 'powerpoint'):
            if key in own:
                files[own[key]] = inside(theme, own[key])
        for asset in own.get('assets', []):
            files[asset] = inside(theme, asset)
        manifest.update({k:v for k,v in own.items() if k not in ('extends', 'assets')})
        manifest['assets'] = sorted(set(files) - {manifest.get(k) for k in ('document', 'slides', 'charts', 'diagrams', 'powerpoint')})
        return manifest, files
    manifest, files = resolve(settings['theme'])
    (output / "theme").mkdir(parents=True, exist_ok=True)
    write_json(output / "theme/theme.json", manifest)
    for name, source in files.items():
        if not source.is_file():
            raise Error(f"Missing theme file: {source}")
        dest = inside(output / "theme", name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    return manifest


def diagram_fences(text, render=False):
    """Translate native Mermaid fences outside other fenced code examples."""
    lines, active = [], None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^( {0,3})(`{3,}|~{3,})(.*?)(\r?\n)?$", line)
        if match:
            indent, fence, info, ending = match.groups()
            if active:
                if fence[0] == active[0] and len(fence) >= active[1] and not info.strip():
                    active = None
            else:
                active = (fence[0], len(fence))
                if info.strip() == "{mermaid}":
                    line = (indent + fence + "{mermaid}" + (ending or "\n") + "%%| eval: true\n"
                            if render else indent + fence + "mermaid" + (ending or "\n"))
        lines.append(line)
    return "".join(lines)


def mermaid_block(attributes, code):
    """Emit a native diagram cell, without allowing file includes or code execution."""
    safe_options = {"label", "fig-cap", "fig-width", "fig-height", "fig-align", "fig-responsive"}
    lines = []
    for line in code.splitlines():
        if line.lstrip().startswith("%%|"):
            match = re.fullmatch(r"\s*%%\|\s*([a-z-]+):\s*(.*?)\s*", line)
            if not match or match[1] not in safe_options:
                raise Error("Unsupported Mermaid cell option; file includes are not allowed")
        lines.append(line)
    # Longer delimiters preserve diagram labels that happen to contain backticks.
    fence = '`' * max(3, 1 + max((len(x) for x in re.findall(r'`+', code)), default=0))
    cell = {"t": "RawBlock", "c": ["markdown", fence + "{mermaid}\n" + '\n'.join(lines) + '\n' + fence]}
    identifier, classes, values = attributes
    return {"t": "Div", "c": [[identifier, ["ff-media", "ff-diagram", *[c for c in classes if c != "mermaid"]], values], [cell]]}


def normalize(settings, output, *, source_text=None, editable_source=True, for_export=True):
    source = settings["source"]
    fmt = {".md": "markdown", ".markdown": "markdown", ".qmd": "markdown", ".org": "org"}.get(source.suffix.lower())
    if not fmt:
        raise Error("Supported sources: .md, .markdown, .qmd and .org")
    pandoc = settings.get('_preview_pandoc', [settings["quarto"], "pandoc"])
    text = bounded_source(source, source_text)
    if fmt == "markdown":
        text = diagram_fences(text)
    if __package__:
        from .source import read, write_org, visible_sources
    else:
        from source import read, write_org, visible_sources
    ast = visible_sources(read(text, fmt, pandoc, for_export=for_export))
    # Keep declarative display settings, not filters/includes/executable settings.
    ast["meta"] = display_metadata(ast.get("meta", {}))
    asset_limit = resource_limit('MATSUGIT_MAX_ASSET_BYTES', 128 * 1024 * 1024)
    asset_budget = resource_limit('MATSUGIT_MAX_TOTAL_ASSET_BYTES', 512 * 1024 * 1024)
    copied = {}

    local_links = 0

    def resource(value, canvas=False):
        nonlocal asset_budget
        url = urlsplit(value)
        if not canvas and (url.scheme in {"https", "http", "mailto", "tel"} or value.startswith("#")):
            return value
        if url.scheme or url.netloc or not url.path:
            raise Error(f"Unsupported resource URL: {value}")
        raw = Path(unquote(url.path))
        path = (source.parent / raw).resolve()
        if raw.is_absolute() or not path.is_relative_to(settings["source_root"]) or any(p.startswith(".") for p in path.relative_to(settings["source_root"]).parts):
            raise Error(f"Resource outside the source project or hidden: {value}")
        allowed = {'.html', '.htm'} if canvas else {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".csv", ".txt", ".md", ".mp4", ".webm", ".mp3"}
        if not path.is_file() or path.suffix.lower() not in allowed:
            raise Error(f"Missing or unsupported attachment: {value}")
        if canvas and (path.stat().st_size > 2 * 1024 * 1024 or url.query or url.fragment):
            raise Error('Canvas requires a self-contained HTML file of at most 2 MiB, without query/fragment')
        if path not in copied:
            limit = min(asset_limit, asset_budget, 2 * 1024 * 1024 if canvas else asset_limit)
            name, size = copy_asset(path, output / 'assets', limit)
            copied[path] = name
            asset_budget -= size
        name = copied[path]
        return "assets/" + quote(name) + ("#" + url.fragment if url.fragment else "")

    def image_slot(image, classes, content):
        height = dict(image['c'][0][2]).get('height', '')
        fixed = re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:px|pt|cm|mm|in|em|rem)', height)
        values = []
        if fixed and float(re.match(r'[0-9.]+', height)[0]) > 0:
            classes = [*classes, 'ff-media-fixed']
            values = [['style', '--ff-image-height:' + height]]
        return {'t':'Div', 'c':[['',classes,values],[content]]}

    def visit(node):
        nonlocal local_links
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        kind = node.get("t")
        if kind == 'Div' and 'canvas' in node['c'][0][1]:
            if __package__:
                from .canvas import attributes
            else:
                from canvas import attributes
            values = attributes(node)
            values['src'] = resource(values['src'], canvas=True)
            node['c'][0][2] = list(map(list, values.items()))
        if kind == "CodeBlock" and "mermaid" in node["c"][0][1]:
            return mermaid_block(*node["c"])
        if kind == "Link":
            attrs, label, (href, _) = node["c"]
            url = urlsplit(href)
            path = Path(unquote(url.path))
            if (url.scheme in ('', 'file') and not url.netloc and url.path
                    and (path.is_absolute() or not (source.parent / path).resolve().is_relative_to(settings['source_root']))):
                # A workstation address is not a publishable attachment. Do not
                # resolve or read it, or leave an unusable link in the shared copy.
                local_links += 1
                if not label or plain(label) in (href, unquote(href), str(path)):
                    label = [{'t':'Str', 'c':path.name}]
                return {'t':'Span', 'c':[attrs, visit(label)]}
        if kind in {"Image", "Link"}:
            node["c"][-1][0] = resource(node["c"][-1][0])
        if kind in {"RawBlock", "RawInline"} and node["c"][0] == "html":
            parser = ResourceHTML(resource)
            parser.feed(node["c"][1])
            parser.close()
            node["c"][1] = "".join(parser.output)
        node = {key: visit(value) for key, value in node.items()}
        if kind == 'Para' and len(node['c']) == 1 and node['c'][0].get('t') == 'Image':
            # Pandoc leaves uncaptioned standalone images as paragraphs, not figures.
            names = [c for c in node['c'][0]['c'][0][1] if c.startswith('media-')]
            return image_slot(node['c'][0], ['ff-media','ff-image',*names], node)
        if kind == "Div" and "ff-media" in node["c"][0][1] and len(node["c"][1]) == 1:
            child = node["c"][1][0]
            if child.get("t") == "Div" and "ff-media" in child["c"][0][1]:
                outer, inner = node["c"][0], child["c"][0]
                child["c"][0] = [outer[0] or inner[0], list(dict.fromkeys(outer[1] + inner[1])),
                                  list(dict(inner[2] + outer[2]).items())]
                return child
        if kind == "Figure":
            images = [block for block in node["c"][2]
                      if block.get("t") in {"Para", "Plain"} and len(block["c"]) == 1
                      and block["c"][0].get("t") == "Image"]
            if len(images) == 1 and len(node["c"][2]) == 1:
                classes = [c for c in images[0]["c"][0]["c"][0][1] if c.startswith("media-")]
                return image_slot(images[0]['c'][0], ['ff-media','ff-image',*classes], node)
        return node

    ast = visit(ast)
    if local_links:
        print(f'Rendering {local_links} local file link(s) as text. Use a web URL for a clickable shared link.',
              file=sys.stderr)
    if fmt == 'org' and editable_source:
        (output / 'source.org').write_text(write_org(ast, pandoc), encoding='utf-8')

    def span_tables(node):
        if isinstance(node, list):
            return [span_tables(n) for n in node]
        if not isinstance(node, dict):
            return node
        if node.get('t') == "Table":
            _, _, _, head, bodies, foot = node["c"]
            rows = head[1] + foot[1] + [row for body in bodies for row in body[2] + body[3]]
            if any(cell[2] != 1 or cell[3] != 1 for row in rows for cell in row[1]):
                table = run([*pandoc, "-f", "json", "-t", "html"], text=json.dumps(dict(ast, blocks=[node])))
                return {"t": "RawBlock", "c": ["html", table]}
        return {key: span_tables(value) for key, value in node.items()}

    ast = span_tables(ast)
    if editable_source:
        markdown = run([*pandoc, "-f", "json", "-t", "markdown", "--standalone", "--wrap=none"], text=json.dumps(ast))
        (output / "source.md").write_text(markdown, encoding="utf-8")
    return ast


def prepare_diagrams(ast, output, theme, colours=None, cache=None):
    appearance = read_json(inside(output / 'theme', theme['diagrams'])) if theme.get('diagrams') else {}
    return diagram_components(ast, output, appearance, colours, cache)


def math_html(node):
    """Keep parsed TeX intact without activating Quarto's CDN math loaders."""
    if isinstance(node, list):
        return [math_html(child) for child in node]
    if not isinstance(node, dict):
        return node
    if node.get('t') == 'Math':
        kind, tex = node['c']
        display = kind['t'] == 'DisplayMath'
        left, right = (r'\[', r'\]') if display else (r'\(', r'\)')
        mode = 'display' if display else 'inline'
        return {'t': 'RawInline', 'c': ['html',
            f'<span class="math {mode} matsugit-math">{left}{html.escape(tex)}{right}</span>']}
    return {key: math_html(value) for key, value in node.items()}


def render(settings, output, edit_url=None, *, source_text=None,
           formats=('document', 'slides'), _prepared=None, _transform=None):
    output = Path(output).resolve()
    if not formats or any(fmt not in ('document', 'slides') for fmt in formats):
        raise Error('Unknown render format')
    if settings.get('handout') and 'slides' not in formats:
        raise Error('A presenter handout requires slides; omit --only document or --handout')
    if _prepared is None and output.exists() and any(output.iterdir()):
        raise Error(f"Output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    pandoc = settings.get('_preview_pandoc', [settings['quarto'], 'pandoc'])
    if _prepared is None:
        theme = install_theme(settings, output)
        if source_text is None and 'document' in formats:
            source_text = bounded_source(settings['source'], None)
        ast = normalize(settings, output, source_text=source_text)
        colours = read_json(inside(output / 'theme', theme['charts'])) if 'charts' in theme else {}
        display_ast = canvas_components(evidence_components(chart_components(
            prepare_diagrams(ast, output, theme, colours), output, colours)), output)
    else:
        theme, ast, display_ast = _prepared
    print(f"Theme: {settings['theme']}; slide layout: {plain(ast['meta'].get('slide-layout')) or 'default'}", flush=True)
    # Quarto requires .qmd for Mermaid cells, even with the inert markdown engine.
    # Keep the published editable source in Markdown; this is a generated input.
    # Enable only native Mermaid display, not programming-language execution.
    inputs = []
    if 'document' in formats:
        if __package__:
            from .document import document
        else:
            from document import document
        document_ast = document(display_ast)
        document_ast = _transform(document_ast, 'document') if _transform else document_ast
        if source_text and settings['source'].suffix.lower() in ('.md', '.markdown', '.qmd'):
            if __package__:
                from .reading_tables import auto_tables
            else:
                from reading_tables import auto_tables
            auto_tables(document_ast, source_text)
        (output / "render.qmd").write_text(
            diagram_fences(run([*pandoc, '-f', 'json', '-t', 'markdown',
                               '--standalone', '--wrap=none'], text=json.dumps(math_html(document_ast))), render=True), encoding="utf-8")
        inputs.append('render.qmd')
    if 'slides' in formats:
        slide_ast = slide_layout(display_ast)
        if _transform:
            slide_ast = _transform(slide_ast, 'slides')
        slide_render_ast = slide_ast
        if not slide_ast['meta'].get('slide-title-page', {'c':True})['c']:
            # Pandoc generates its cover from title metadata; keep the reading title intact.
            slide_render_ast = dict(slide_ast, meta={k:v for k,v in slide_ast['meta'].items()
                                                    if k not in ('title', 'subtitle')})
        slide_source = run([*pandoc, "-f", "json", "-t", "markdown",
                            "--standalone", "--wrap=none"], text=json.dumps(math_html(slide_render_ast)))
        (output / "slides.qmd").write_text(diagram_fences(slide_source, render=True), encoding="utf-8")
        inputs.append('slides.qmd')
    shutil.copytree(Path(__file__).parent / "runtime", output / "runtime")
    expand_runtime(output / "runtime")
    has_math = math_html(display_ast) != display_ast
    math_header = ('<script src="runtime/math-config.js"></script>\n'
                   '<script defer src="runtime/mathjax-tex-svg.js"></script>\n') if has_math else ''
    (output / "media-head.html").write_text(
        '<link rel="stylesheet" href="runtime/media.css">\n'
        '<link rel="stylesheet" href="runtime/canvas.css">\n'
        '<link rel="stylesheet" href="runtime/layout.css">\n'
        '<link rel="stylesheet" href="runtime/document-fold.css">\n'
        '<script defer src="runtime/document-fold.js"></script>\n'
        '<script defer src="runtime/media.js"></script>\n'
        '<script defer src="runtime/canvas.js"></script>\n'
        '<script defer src="runtime/fit.js"></script>\n'
        '<script defer src="runtime/annotations.js"></script>\n' + math_header, encoding="utf-8")
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    source_name = 'source.org' if settings['source'].suffix.lower() == '.org' else 'source.md'
    links = '<a href="slides.html">Slides</a> ' if 'slides' in formats else ''
    links += f'<a href="{source_name}">Source</a>'
    if settings.get('handout'):
        links += ' <a href="handout.html">Presenter handout</a>'
        handout = run([*pandoc, '-f', 'json', '-t', 'markdown',
                       '--standalone', '--wrap=none'], text=json.dumps(math_html(handout_layout(slide_ast))))
        (output / 'handout.qmd').write_text(diagram_fences(handout, render=True), encoding='utf-8')
    if edit_url:
        links += f' <a href="{html.escape(edit_url, quote=True)}">Edit source</a>'
    (output / "navigation.html").write_text(
        f'<nav class="matsugit-nav folioforge-nav" aria-label="Document formats">{links}'
        f'<span>Updated <time datetime="{stamp}">{now.strftime("%d %b %Y, %H:%M UTC")}</time></span></nav>', encoding="utf-8")
    metadata = {
        "project": {"type": "default", "render": inputs},
        "execute": {"enabled": False, "eval": False},
        "engine": "markdown",
        # Parsed Math nodes above use the same local runtime in every output.
        "html-math-method": "plain",
        "include-in-header": "media-head.html",
        "format": {
            "html": {"theme": "default", "css": ["theme/" + theme["document"], "runtime/reading.css"],
                     "toc": ast["meta"].get("document-toc", {"c": True})["c"], "toc-depth": 3,
                     "grid": {"body-width": "3840px"},
                     "embed-resources": True, "format-links": False, "pagetitle": settings["source"].stem,
                     "include-before-body": "navigation.html", "include-after-body": "runtime/reading-footer.html"},
            "revealjs": {"theme": ["default", "theme/" + theme["slides"]], "embed-resources": True,
                         "slide-level": 2, "width": 1280,
                         "height": 960 if plain(ast['meta'].get('slide-aspect-ratio')) == '4:3' else 720,
                         "pagetitle": plain(ast['meta'].get('title')) or settings['source'].stem,
                         "scrollable": True,
                         "auto-stretch": False,
                         "slide-number": "c/t", "transition": "none",
                         "footer": ('<a class="matsugit-document-link folioforge-document-link" href="index.html" aria-label="Read the document version">Document</a>' if 'document' in formats else '')},
        },
    }
    if settings.get('handout'):
        # Quarto ignores project format options for files outside this render list.
        metadata['project']['render'].append('handout.qmd')
    write_json(output / "_quarto.yml", metadata)
    for fmt, filename in (("html", "index.html"), ("revealjs", "slides.html")):
        if ('document' if fmt == 'html' else 'slides') not in formats:
            continue
        print(f"Rendering {fmt}: {filename}", flush=True)
        source = "render.qmd" if fmt == "html" else "slides.qmd"
        run([settings["quarto"], "render", source, "--to", fmt, "--output", filename, "--no-execute"], cwd=output)
        if not (output / filename).is_file():
            raise Error(f"Renderer did not produce {filename}")
    if settings.get('handout'):
        print('Rendering presenter handout: handout.html', flush=True)
        run([settings['quarto'], 'render', 'handout.qmd', '--to', 'html', '--output',
             'handout.html', '--no-execute'], cwd=output)
    for name in (".quarto", "render_files", "source_files", "index_files", "slides_files", 'handout_files'):
        if (output / name).is_dir():
            shutil.rmtree(output / name)
    manifest = {"version": 1, "theme": settings["theme"], "updated": stamp, "edit_url": edit_url,
                "formats": list(formats),
                'handout': bool(settings.get('handout')),
                "source_file": source_name,
                "source_sha256": hashlib.sha256((output / source_name).read_bytes()).hexdigest(),
                "normalized_sha256": hashlib.sha256((output / "source.md").read_bytes()).hexdigest(),
                "files": sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file())}
    # The legacy manifest keeps already-installed CI working across the rename.
    manifest['files'].extend(['matsugit-manifest.json', 'folioforge-manifest.json'])
    write_json(output / "matsugit-manifest.json", manifest)
    write_json(output / "folioforge-manifest.json", manifest)
    return manifest
