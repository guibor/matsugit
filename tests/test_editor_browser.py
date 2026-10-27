"""Opt-in real Chromium tests; only synthetic local tables are used."""
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '| Area | Team | Result |\n| --- | --- | --- |\n| North | **Alpha** | 12 |\n| North | Beta | 18 |\n| South | Gamma | 24 |\n'


@unittest.skipUnless(os.environ.get('FOLIOFORGE_BROWSER_TESTS'), 'Opt-in local browser tests')
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import expect
        cls.expect = staticmethod(expect)
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ.get('CHROME', '/opt/google/chrome/chrome'), args=['--no-sandbox'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    @contextmanager
    def session(self, source=SOURCE):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            input_path, output = directory / 'table.md', directory / 'result.md'
            input_path.write_text(source)
            process = subprocess.Popen([sys.executable, '-m', 'folioforge', 'edit-table', str(input_path), '--output', str(output), '--no-open'],
                                       cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            page = None
            try:
                self.assertTrue(select.select([process.stdout], [], [], 20)[0], 'Server startup timed out')
                line = process.stdout.readline()
                if not line:
                    self.fail(process.stderr.read())
                event = json.loads(line)
                page = self.browser.new_page(viewport={'width': 1440, 'height': 960})
                page.goto(event['url'])
                self.expect(page.locator('#status')).to_have_text(re.compile('^(Ready|Unavailable)$'))
                self.assertEqual(page.locator('#status').inner_text(), 'Ready', page.locator('#error').inner_text() + '\n' + page.evaluate('window.folioforgeEditor?.getHTML() || "No editor"'))
                yield page, process, output, event['url']
            finally:
                if page:
                    page.close(run_before_unload=False)
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)

    def select_cells(self, page, first, last):
        page.evaluate('''([first,last]) => {
            const editor=window.folioforgeEditor, cells=[];
            editor.state.doc.descendants((node,pos) => { if(['tableCell','tableHeader'].includes(node.type.name)) cells.push(pos); });
            editor.commands.setCellSelection({anchorCell:cells[first],headCell:cells[last]});
        }''', [first, last])

    def test_merge_split_format_save_reopen_desktop_and_mobile(self):
        with self.session() as (page, process, output, _url):
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            self.select_cells(page, 0, 1)
            page.get_by_role('button', name='Merge selected cells', exact=True).click()
            self.assertEqual(page.locator('th[colspan="2"]').count(), 1)
            page.get_by_role('button', name='Split merged cell', exact=True).click()
            self.assertEqual(page.locator('th[colspan="2"]').count(), 0)
            page.get_by_role('button', name='Undo', exact=True).click()
            self.assertEqual(page.locator('th[colspan="2"]').count(), 1)
            page.get_by_role('button', name='Redo', exact=True).click()
            self.assertEqual(page.locator('th[colspan="2"]').count(), 0)
            self.select_cells(page, 0, 1)
            page.get_by_role('button', name='Merge selected cells', exact=True).click()
            self.select_cells(page, 2, 5)
            page.get_by_role('button', name='Merge selected cells', exact=True).click()
            self.assertEqual(page.locator('td[rowspan="2"]').count(), 1)
            page.get_by_role('button', name='Markdown source', exact=True).click()
            self.expect(page.locator('#source')).to_have_text(re.compile(r'^\+'), timeout=10000)
            text = page.locator('#source').inner_text()
            self.assertNotIn('<table', text)
            self.assertIn('**Alpha**', text)
            page.screenshot(path='/tmp/folioforge-editor-desktop.png', full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path='/tmp/folioforge-editor-mobile.png', full_page=True)
            page.get_by_role('button', name='Save and Return', exact=True).click()
            self.assertEqual(process.wait(timeout=20), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            saved = output.read_text()
            self.assertTrue(saved.startswith('+'))
            self.assertNotIn('<table', saved)
            self.assertFalse(errors)
        with self.session(saved) as (page, process, output, _url):
            self.assertEqual(page.locator('th[colspan="2"]').count(), 1)
            self.assertEqual(page.locator('td[rowspan="2"]').count(), 1)
            page.get_by_role('button', name='Cancel', exact=True).click()
            self.assertEqual(process.wait(timeout=10), 2)
            self.assertFalse(output.exists())

    def test_rows_columns_alignment_unicode_and_cancel(self):
        source = SOURCE.replace('| --- | --- | --- |', '| :--- | :---: | ---: |').replace('Gamma', 'שלום')
        with self.session(source) as (page, process, output, _url):
            self.select_cells(page, 3, 3)
            page.get_by_label('Rows', exact=True).select_option('addRowAfter')
            self.assertEqual(page.locator('.tiptap tr').count(), 5)
            page.get_by_role('button', name='Undo', exact=True).click()
            self.assertEqual(page.locator('.tiptap tr').count(), 4)
            page.get_by_label('Columns', exact=True).select_option('addColumnAfter')
            self.assertEqual(page.locator('.tiptap tr').first.locator('th').count(), 4)
            page.get_by_role('button', name='Undo', exact=True).click()
            page.get_by_role('button', name='Markdown source', exact=True).click()
            self.expect(page.locator('#source')).to_contain_text('שלום', timeout=10000)
            self.assertIn(':', page.locator('#source').inner_text())
            page.get_by_role('button', name='Cancel', exact=True).click()
            self.assertEqual(process.wait(timeout=10), 2)
            self.assertFalse(output.exists())

    def test_api_rejects_cross_origin_bad_token_bad_host_and_active_html(self):
        with self.session() as (page, _process, _output, url):
            parts = urlsplit(url)
            origin = f'{parts.scheme}://{parts.netloc}'
            auth = {'Authorization': 'Bearer ' + parts.fragment}
            self.assertEqual(page.request.get(origin + '/api/table').status, 403)
            self.assertEqual(page.request.get(origin + '/api/table', headers={**auth, 'Origin':'https://example.invalid'}).status, 403)
            self.assertEqual(page.request.get(origin + '/api/table', headers={**auth, 'Host':'example.invalid'}).status, 403)
            self.assertEqual(page.request.post(origin + '/api/save', headers=auth, data={'html':'<script>bad()</script>'}).status, 400)
            self.assertEqual(page.request.post(origin + '/api/save', headers=auth, data=['invalid']).status, 400)
            self.assertEqual(page.request.get(origin + '/api/table', headers=auth).status, 200)
