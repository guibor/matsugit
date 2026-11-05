"""Installed native CI versus local renderer, with no accounts or publication.

The default test compares real Pandoc output and packaged theme/runtime files.
Set MATSUGIT_PARITY_RENDER=1 for the actual Quarto HTML boundary as well.
"""
import json
import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import unquote
from itertools import product
from unittest.mock import patch

from matsugit import core, source_ci
from matsugit import preview
from matsugit.converter import converter
from matsugit.publish import setup_ci
from matsugit.source import convert

ROOT = Path(__file__).resolve().parents[1]


class EmbeddedCSS(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.styles = html; self.feed(html)

    def handle_starttag(self, tag, attrs):
        url = dict(attrs).get('href', '') if tag == 'link' else ''
        if url.startswith('data:text/css'):
            kind, _, value = url.partition(',')
            self.styles += base64.b64decode(value).decode() if ';base64' in kind else unquote(value)

# Only the final HTML renderer is replaced in the fast contract test. Pandoc,
# normalization, layout, theme copying and the installed CI entrypoint are real.
STUB = '''
original_run = core.run
def render_stub(argv, cwd=None, text=None):
    if len(argv) > 1 and argv[1] == 'render':
        Path(cwd, argv[argv.index('--output') + 1]).write_text('<html>stub</html>')
        return ''
    return original_run(argv, cwd, text)
core.run = render_stub
'''


class RenderParityTests(unittest.TestCase):
    def exercise(self, real=False):
        command = converter()
        with tempfile.TemporaryDirectory(prefix='matsugit-parity-') as temporary:
            root = Path(temporary)
            theme = root/'themes/synthetic'; theme.mkdir(parents=True)
            (theme/'theme.json').write_text(json.dumps({'document':'document.css','slides':'slides.scss'}))
            (theme/'document.css').write_text(':root { --parity-color: #164bc4; }')
            (theme/'slides.scss').write_text('/*-- scss:defaults --*/\n$body-color: #142d4e;\n/*-- scss:rules --*/\n.reveal { --parity-color: #164bc4; }')
            text = (ROOT/'tests/fixtures/render-parity.md').read_text()
            env = dict(os.environ, MATSUGIT_CONFIG=str(root/'absent.json'))
            # Both formats, both visibility values, two theme configurations.
            cases = [('markdown',False,'default'),('org',True,'synthetic')] if real else product(('markdown','org'), (False,True), ('default','synthetic'))
            for fmt, flag, style in cases:
                with self.subTest(fmt=fmt, visible=flag, theme=style):
                    case = f'{fmt}-{flag}-{style}'
                    repo = root/f'repo-{case}'; repo.mkdir()
                    draft = text.replace(': false', ': true') if flag else text
                    source = root/('deck.org' if fmt == 'org' else 'deck.md')
                    source.write_text(convert(draft, 'markdown', 'org', command) if fmt == 'org' else draft)
                    with patch.dict(os.environ, env):
                        settings = core.config(source, {'repo':str(repo),'theme':style,'themes_dir':str(theme.parent),
                                                        'quarto':shutil.which('quarto') or 'quarto','_preview_pandoc':command})
                        if real: settings.pop('_preview_pandoc')
                        setup_ci(settings, 'gitlab')
                        bundle = repo/'matsugit-site/demo'; bundle.parent.mkdir()
                        source_ci.prepare(settings, bundle, {'ci_layout':'native','provider':'gitlab',
                            'project_url':'https://example.invalid/test/parity','branch':'main','directory':'matsugit-site/demo'})
                        local = root/f'local-{case}'
                        if real:
                            core.render(settings, local)
                        else:
                            scope = {'core':core, 'Path':Path}; exec(STUB, scope)
                            try: core.render(settings, local)
                            finally: core.run = scope['original_run']
                        previews = []
                        for format in ('document','slides'):
                            destination = root/f'preview-{case}-{format}'
                            if not real:
                                scope = {'core':core, 'Path':Path}; exec(STUB, scope)
                            try: preview.render(settings, destination, source.read_text(), format)
                            finally:
                                if not real: core.run = scope['original_run']
                            previews.append(destination)
                    # Use installed imports in a separate process, as the runner does.
                    script = "import sys, runpy\nfrom pathlib import Path\nsys.path.insert(0,'.matsugit-ci')\nimport core\n"
                    if not real:
                        script += f"core.config_original=core.config\ndef ci_config(*args,**kwargs):\n r=core.config_original(*args,**kwargs); r['_preview_pandoc']={command!r}; return r\ncore.config=ci_config\n"
                        script += STUB
                    script += "runpy.run_path('.matsugit-ci/build.py',run_name='__main__')\n"
                    result = subprocess.run([sys.executable,'-c',script],cwd=repo,env=env,capture_output=True,text=True,timeout=300)
                    self.assertEqual(result.returncode,0,result.stderr[-5000:])
                    for name in ('render.qmd','slides.qmd'):
                        self.assertEqual((local/name).read_text(),(bundle/name).read_text(),name)
                    for name in ('document.css','slides.scss','theme.json'):
                        self.assertEqual((local/'theme'/name).read_bytes(),(bundle/'theme'/name).read_bytes())
                    for name in ('layout.css','media.css','canvas.css'):
                        self.assertEqual((local/'runtime'/name).read_bytes(),(bundle/'runtime'/name).read_bytes())
                    document, slides = (local/'render.qmd').read_text(), (local/'slides.qmd').read_text()
                    # Org can escape underscores in its Markdown representation.
                    document, slides = document.replace('\\_', '_'), slides.replace('\\_', '_')
                    self.assertEqual('SourceSentinel' in document,flag)
                    self.assertEqual('SourceSentinel' in slides,flag)
                    self.assertEqual('NotesSentinel' in document,flag)
                    self.assertIn('NotesSentinel',slides)
                    for literal in ('LITERAL_SOURCE','LITERAL_NOTES','Illustrative Author'):
                        self.assertIn(literal,document); self.assertIn(literal,slides)
                    self.assertIn('columns',slides)
                    self.assertIn('.quote',slides)
                    for destination, name, has_notes in [(previews[0],'render.qmd',flag),(previews[1],'slides.qmd',True)]:
                        generated = (destination/name).read_text()
                        self.assertEqual('SourceSentinel' in generated,flag)
                        self.assertEqual('NotesSentinel' in generated,has_notes)
                        self.assertIn('LITERAL_NOTES',generated)
                    if real:
                        for name in ('index.html','slides.html'):
                            for folder in (local,bundle,previews[0 if name=='index.html' else 1]):
                                html = (folder/name).read_text()
                                self.assertEqual('SourceSentinel' in html,flag)
                                self.assertEqual('NotesSentinel' in html,flag or name=='slides.html')
                                self.assertIn('LITERAL_NOTES',html)
                                self.assertIn('Illustrative Author',html)
                                if style == 'synthetic':
                                    self.assertTrue('--parity-color' in EmbeddedCSS(html).styles, f'{folder.name}/{name}: theme CSS missing')

    def test_packaged_ci_inputs_match_local_renderer(self):
        self.exercise()

    @unittest.skipUnless(os.environ.get('MATSUGIT_PARITY_RENDER'), 'Opt-in Quarto HTML parity')
    def test_real_html_parity(self):
        self.exercise(real=True)


if __name__ == '__main__': unittest.main()
