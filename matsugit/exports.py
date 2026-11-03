"""Explicit local exports. Writing a synced folder is not proof of cloud sync."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit
import zipfile
import xml.etree.ElementTree as ET

from .core import Error, install_theme, normalize, render, run, read_json
from .layout import slides
from .charts import prepare as charts, style
from .components import prepare as components
from .targets import settings as global_settings
from . import export_state


def setup():
    root = Path.home() / '.local/share/matsugit/export-tools'
    python = root / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(root)], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', 'playwright>=1.40'], check=True)
    subprocess.run([str(python), '-m', 'playwright', 'install', 'chromium'], check=True)
    print(f'PDF and diagram export ready: {python}')


def browser_artifacts(directory, pdf=None):
    if importlib.util.find_spec('playwright') is None:
        python = Path(os.environ.get('MATSUGIT_EXPORT_PYTHON', str(
            Path.home() / '.local/share/matsugit/export-tools' /
            ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))))
        if not python.is_file():
            raise Error('PDF/diagram export needs Chromium. Run matsugit setup-export once')
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        result = subprocess.run([str(python), '-m', 'matsugit.exports', str(directory),
                                 str(pdf) if pdf else ''], env=env, capture_output=True, text=True, timeout=240)
        if result.returncode:
            raise Error(result.stderr.strip() or 'Browser export failed')
        return json.loads(result.stdout)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('MATSUGIT_CHROME'))
        page = browser.new_page(viewport={'width': 1280, 'height': 720}, device_scale_factor=2)
        # Generated output is self-contained. Never fetch private links or remote images.
        page.route('**/*', lambda route: route.abort() if urlsplit(route.request.url).scheme in ('http', 'https') else route.continue_())
        path = directory / ('slides.html' if pdf else 'index.html')
        page.goto(path.as_uri() + ('?print-pdf' if pdf else ''), wait_until='load')
        page.evaluate('document.fonts.ready')
        diagrams = page.locator('svg.mermaid-js')
        if page.locator('.mermaid').count():
            page.wait_for_function('document.querySelectorAll(".mermaid").length === document.querySelectorAll("svg.mermaid-js").length', timeout=30000)
        names = []
        if pdf:
            page.wait_for_function('window.Reveal?.isReady() && document.documentElement.classList.contains("print-pdf")')
            page.evaluate('Reveal.configure({pdfSeparateFragments:false})')
            page.pdf(path=str(pdf), print_background=True, prefer_css_page_size=True)
        else:
            for index in range(diagrams.count()):
                name = f'diagram-{index}.png'
                diagrams.nth(index).screenshot(path=str(directory / name))
                names.append(name)
        browser.close()
    return names


def pptx_ast(ast, directory, pandoc, diagram_names):
    diagrams = iter(diagram_names)
    def visit(node):
        if isinstance(node, list):
            result = []
            for item in node:
                converted = visit(item)
                if isinstance(converted, dict) and converted.get('t') == 'Div' and not set(converted['c'][0][1]) & {'columns', 'column', 'notes'}:
                    # The PPTX writer otherwise silently loses tables/images nested in CSS wrappers.
                    result.extend(converted['c'][1])
                else:
                    result.append(converted)
            return result
        if not isinstance(node, dict):
            return node
        if node.get('t') == 'Div' and 'ff-diagram' in node['c'][0][1]:
            name = next(diagrams, None)
            if name is None:
                raise Error('A diagram could not be captured for PowerPoint; nothing exported')
            return {'t':'Para', 'c':[{'t':'Image', 'c':[['',[],[]], [], [name,'']]}]}
        if node.get('t') == 'RawBlock' and node['c'][0] == 'html':
            converted = json.loads(run([*pandoc, '-f', 'html', '-t', 'json'], text=node['c'][1]))
            return {'t':'Div', 'c':[['',[],[]], visit(converted['blocks'])]}
        if node.get('t') == 'Image':
            node['c'][-1][0] = unquote(node['c'][-1][0])
        if node.get('t') == 'Div' and 'columns' in node['c'][0][1] and len(node['c'][1]) > 2:
            # Pandoc's PowerPoint layouts only have two content placeholders.
            node['c'][0][1].remove('columns')
        return {key: visit(value) for key, value in node.items()}
    return visit(ast)


def color_reference(pandoc, directory, palette):
    """Use Pandoc's native layouts, with the selected theme's chart palette."""
    reference = directory / 'reference.pptx'
    subprocess.run([*pandoc, '-o', str(reference), '--print-default-data-file=reference.pptx'], check=True)
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    colors = style(palette)
    with zipfile.ZipFile(reference) as archive:
        files = {item.filename: archive.read(item) for item in archive.infolist()}
    for name, data in files.items():
        if not name.startswith('ppt/theme/') or not name.endswith('.xml'):
            continue
        root = ET.fromstring(data)
        for tag, value in {'dk1':colors['ink'], 'dk2':colors['ink'], 'lt1':colors['background'],
                           **{f'accent{i+1}':v for i,v in enumerate(colors['series'][:6])}}.items():
            element = root.find(f'.//a:clrScheme/a:{tag}', ns)
            if element is not None:
                element.clear()
                ET.SubElement(element, '{'+ns['a']+'}srgbClr', {'val': value.lstrip('#')})
        files[name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(reference, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return reference


def export_file(settings, kind, output=None, *, sync_folder=False, reference=None, source_text=None, replace=False):
    if kind not in ('html', 'zip', 'pptx', 'pdf'):
        raise Error('Supported export formats: html, zip, pptx, pdf')
    if output and sync_folder:
        raise Error('Choose --output or --sync-folder, not both')
    if sync_folder:
        directory = global_settings().get('export_directory')
        if not directory or not Path(directory).expanduser().is_dir():
            raise Error('Configure an existing folder with matsugit export-folder /path/to/OneDrive/Decks')
        output = Path(directory).expanduser() / (settings['slug'] + '.' + kind)
    if output is None:
        raise Error('Choose --output FILE or --sync-folder')
    output = Path(output).expanduser().absolute()
    previous = export_state.check(output, settings['source'], replace) if sync_folder or replace else None
    if not (sync_folder or replace) and (output.exists() or output.is_symlink()):
        raise Error(f'Export already exists; choose a new filename (nothing overwritten): {output}')
    if not output.parent.is_dir():
        raise Error('Export destination directory does not exist')
    warnings = []
    with tempfile.TemporaryDirectory(prefix='matsugit-export-') as temp:
        root = Path(temp)
        artifact = root / ('export.' + kind)
        rendered = root / 'render'
        if kind in ('html', 'zip', 'pdf'):
            render(settings, rendered, source_text=source_text)
            if kind == 'html':
                shutil.copyfile(rendered / 'slides.html', artifact)
                warnings.append('Standalone slide HTML; use ZIP for document/source links and the complete bundle.')
            elif kind == 'zip':
                with zipfile.ZipFile(artifact, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(rendered.rglob('*')):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, path.relative_to(rendered))
            else:
                browser_artifacts(rendered, artifact)
        else:
            rendered.mkdir()
            theme = install_theme(settings, rendered)
            ast = normalize(settings, rendered, source_text=source_text)
            palette = read_json(rendered / 'theme' / theme['charts']) if theme.get('charts') else {}
            ast = slides(components(charts(ast, rendered, palette)))
            if not ast['meta'].get('slide-title-page', {'c':True})['c']:
                ast['meta'] = {k:v for k,v in ast['meta'].items() if k not in ('title', 'subtitle')}
            names = []
            if 'ff-diagram' in json.dumps(ast):
                full = root / 'diagram-render'
                render(settings, full, source_text=source_text)
                names = browser_artifacts(full)
                for name in names:
                    shutil.copyfile(full / name, rendered / name)
            pandoc = [settings['quarto'], 'pandoc']
            ast = pptx_ast(ast, rendered, pandoc, names)
            reference = (Path(reference).expanduser().resolve() if reference else
                         rendered / 'theme' / theme['powerpoint'] if theme.get('powerpoint') else
                         color_reference(pandoc, root, palette))
            run([*pandoc, '-f', 'json', '-t', 'pptx', '--slide-level=2',
                 '--reference-doc', str(reference), '-o', str(artifact)],
                cwd=rendered, text=json.dumps(ast))
            warnings.append('Editable PowerPoint: native text/tables; charts and diagrams are images. CSS layouts, complex blocks and merged cells can differ. Review before sharing.')
        # Stage beside the destination, then recheck for edits made during rendering.
        fd, staged = tempfile.mkstemp(prefix='.matsugit-export-', dir=output.parent)
        try:
            with os.fdopen(fd, 'wb') as destination, artifact.open('rb') as source:
                shutil.copyfileobj(source, destination)
                destination.flush(); os.fsync(destination.fileno())
            if export_state.digest(output) != previous:
                raise Error('Export destination changed during rendering; nothing overwritten')
            if previous is None:
                # File-provider folders may not support hard links.
                with output.open('xb') as destination, open(staged, 'rb') as prepared:
                    shutil.copyfileobj(prepared, destination)
                    destination.flush(); os.fsync(destination.fileno())
            else:
                os.chmod(staged, output.stat().st_mode & 0o777)
                os.replace(staged, output)
        finally:
            Path(staged).unlink(missing_ok=True)
        if sync_folder or replace:
            try:
                export_state.record(output, settings['source'])
            except (OSError, Error) as error:
                warnings.append(f'Export saved, but ownership receipt failed: {error}. Next replacement needs confirmation.')
    return {'path': str(output), 'format': kind, 'warnings': warnings,
            'sync': 'Saved locally. OneDrive upload status is not verified.' if sync_folder else None}


if __name__ == '__main__':
    print(json.dumps(browser_artifacts(Path(sys.argv[1]), Path(sys.argv[2]) if sys.argv[2] else None)))
