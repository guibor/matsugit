import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from matsugit import core, source_ci
from matsugit.converter import converter
from matsugit.export_boundary import MARKER
from matsugit.exports import export_file
from matsugit.publish import setup_ci
from matsugit.source import read


class ExportBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'deck.md'
        self.text = '---\ntitle: Boundary test\nslide-layout: structured\n---\n\n## INCLUDED\n\nPublic text.\n\n' + MARKER + '\n\n## OMITTED_SENTINEL\n\n[Attachment](working-only.txt)\n'
        self.source.write_text(self.text)
        (self.root / 'working-only.txt').write_text('OMITTED_ATTACHMENT')
        env = patch.dict(os.environ, {'MATSUGIT_CONFIG':str(self.root / 'absent.json'),
                                     'MATSUGIT_THEMES_DIR':str(self.root / 'themes')})
        env.start(); self.addCleanup(env.stop)
        self.command = converter()
        self.settings = core.config(self.source, {'theme':'default', 'quarto':shutil.which('quarto') or 'quarto',
                                                 '_preview_pandoc':self.command})

    def test_only_standalone_top_level_marker_is_active(self):
        for example in (f'```html\n{MARKER}\n```', f'    {MARKER}', f'> {MARKER}',
                        f'::: notes\n{MARKER}\n:::', f'A literal `{MARKER}`.',
                        '<!-- another comment\n' + MARKER + '\n-->'):
            with self.subTest(example=example):
                ast = read(example + '\n\nKEEP_AFTER_EXAMPLE\n', 'markdown', self.command, for_export=True)
                self.assertIn('KEEP_AFTER_EXAMPLE', json.dumps(ast))
        for ending in ('\n', '\r\n'):
            text = self.text.replace('\n', ending)
            self.assertNotIn('OMITTED_SENTINEL', json.dumps(read(text, 'markdown', self.command, for_export=True)))
            self.assertIn('OMITTED_SENTINEL', json.dumps(read(text, 'markdown', self.command)))

    def test_normalize_drops_tail_before_assets_and_source_download(self):
        (self.root / 'working-only.txt').unlink()
        output = self.root / 'out'; output.mkdir()
        ast = core.normalize(self.settings, output)
        self.assertIn('INCLUDED', json.dumps(ast))
        self.assertNotIn('OMITTED', json.dumps(ast))
        self.assertNotIn('OMITTED', (output / 'source.md').read_text())
        self.assertFalse((output / 'assets').exists())
        self.assertEqual(self.source.read_text(), self.text)

    @unittest.skipUnless(os.environ.get('QUARTO') and shutil.which('pdftotext') and os.environ.get('MATSUGIT_EXPORT_PYTHON'), 'Set browser export tools for PDF check')
    def test_real_pdf(self):
        output = self.root / 'deck.pdf'
        export_file(dict(self.settings,quarto=os.environ['QUARTO']), 'pdf', output)
        text = subprocess.check_output(['pdftotext',str(output),'-'],text=True)
        self.assertIn('INCLUDED',text)
        self.assertNotIn('OMITTED',text)
        self.assertEqual(self.source.read_text(),self.text)

    def test_native_ci_keeps_git_source_and_publishes_clean_output(self):
        repo = self.root / 'repo'; repo.mkdir()
        settings = dict(self.settings, repo=repo)
        setup_ci(settings, 'gitlab')
        bundle = repo / 'matsugit-site/demo'; bundle.parent.mkdir()
        source_ci.prepare(settings, bundle, {'ci_layout':'native', 'provider':'gitlab',
            'project_url':'https://example.invalid/demo', 'directory':'matsugit-site/demo'})
        before = (bundle / 'source.md').read_bytes()
        self.assertIn(b'OMITTED_SENTINEL', before)
        self.assertEqual(len(list((bundle / 'assets').glob('*working-only.txt'))), 1)
        # Exercise the installed CI code, stubbing only the final Quarto process.
        script = '''import runpy, sys
from pathlib import Path
sys.path.insert(0, '.matsugit-ci')
import core
original = core.run
def run(argv, cwd=None, text=None):
    if len(argv) > 1 and argv[1] == 'render':
        Path(cwd, argv[argv.index('--output')+1]).write_text('<html>synthetic</html>')
        return ''
    return original(argv, cwd, text)
core.run = run
runpy.run_path('.matsugit-ci/build.py', run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=repo,
                                env=dict(os.environ, QUARTO=shutil.which('quarto') or 'quarto'),
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((bundle / 'source.md').read_bytes(), before)
        generated = repo / '.matsugit-ci/site/demo'
        for name in ('source.md', 'render.qmd', 'slides.qmd'):
            self.assertNotIn('OMITTED', (generated / name).read_text())
        self.assertFalse(list(generated.rglob('*working-only*')))
        workflow = (repo / 'matsugit.gitlab-ci.yml').read_text()
        self.assertIn('publish: .matsugit-ci/site', workflow)

    @unittest.skipUnless(os.environ.get('QUARTO'), 'Set QUARTO for real HTML/ZIP/PowerPoint exports')
    def test_real_export_formats(self):
        settings = dict(self.settings, quarto=os.environ['QUARTO'])
        for kind in ('html', 'zip', 'pptx'):
            with self.subTest(kind=kind):
                output = self.root / ('deck.' + kind)
                export_file(settings, kind, output)
                if kind == 'html':
                    data = output.read_bytes()
                else:
                    with zipfile.ZipFile(output) as archive:
                        data = b'\n'.join(archive.read(name) for name in archive.namelist())
                self.assertIn(b'INCLUDED', data)
                self.assertNotIn(b'OMITTED_SENTINEL', data)
                self.assertNotIn(b'OMITTED_ATTACHMENT', data)
        self.assertEqual(self.source.read_text(), self.text)
