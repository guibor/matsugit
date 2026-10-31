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
    def session(self, source=SOURCE, extension='.md'):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            input_path, output = directory / ('table'+extension), directory / ('result'+extension)
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
            page.get_by_role('button', name='Table source', exact=True).click()
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
            page.get_by_role('button', name='Table source', exact=True).click()
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
            client = 'test-client-1234567890'
            self.assertEqual(page.request.post(origin + '/api/open', headers=auth, data={'client': client}).status, 200)
            auth['X-Folioforge-Client'] = client
            self.assertEqual(page.request.post(origin + '/api/save', headers=auth, data={'html':'<script>bad()</script>'}).status, 400)
            self.assertEqual(page.request.post(origin + '/api/save', headers=auth, data=['invalid']).status, 400)
            self.assertEqual(page.request.get(origin + '/api/table', headers=auth).status, 200)

    def control(self, page, url, action):
        parts = urlsplit(url)
        return page.request.post(f'{parts.scheme}://{parts.netloc}/api/control',
                                 headers={'Authorization': 'Bearer ' + parts.fragment},
                                 data={'action': action})

    def edit_first_cell(self, page, value):
        page.evaluate('''value => {
            const editor = window.folioforgeEditor;
            editor.chain().setTextSelection(3).insertContent(value).run();
        }''', value)

    def test_close_tab_reopen_recovers_and_emacs_save_uses_latest_typing(self):
        with self.session() as (page, process, output, url):
            self.edit_first_cell(page, 'Checkpoint ')
            self.expect(page.locator('#status')).to_have_text('Draft saved', timeout=10000)
            self.assertFalse(output.exists())
            page.close()
            other = self.browser.new_page()
            try:
                other.goto(url)
                self.expect(other.locator('#status')).to_have_text('Recovered draft')
                self.expect(other.locator('.tiptap')).to_contain_text('Checkpoint')
                self.edit_first_cell(other, 'Latest ')
                response = self.control(other, url, 'save')
                self.assertEqual(response.status, 200)
                self.expect(other.locator('#status')).to_have_text('Saved', timeout=10000)
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertIn('Latest', output.read_text())
                self.assertIn('Checkpoint', output.read_text())
            finally:
                other.close(run_before_unload=False)

    def test_duplicate_tab_cannot_overwrite_new_owner_and_reload_recovers(self):
        with self.session() as (page, process, output, url):
            self.edit_first_cell(page, 'Initial ')
            self.expect(page.locator('#status')).to_have_text('Draft saved', timeout=10000)
            other = self.browser.new_page()
            try:
                other.goto(url)
                self.expect(other.locator('#status')).to_have_text('Recovered draft')
                self.expect(page.locator('#status')).to_have_text('Replaced by another tab')
                self.assertEqual(page.locator('.tiptap').get_attribute('contenteditable'), 'false')
                self.expect(page.get_by_role('button', name='Save and Return', exact=True)).to_be_disabled()
                self.edit_first_cell(other, 'New owner ')
                self.expect(other.locator('#status')).to_have_text('Draft saved', timeout=10000)
                other.reload()
                self.expect(other.locator('#status')).to_have_text('Recovered draft')
                self.expect(other.locator('.tiptap')).to_contain_text('New owner')
                other.get_by_role('button', name='Save and Return', exact=True).click()
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertIn('New owner', output.read_text())
            finally:
                other.close(run_before_unload=False)

    def test_explicit_checkpoint_commit_and_cancel_disable_open_tabs(self):
        for action, code in [('save-draft', 0), ('cancel', 2)]:
            with self.subTest(action=action), self.session() as (page, process, output, url):
                self.edit_first_cell(page, 'Recoverable ')
                self.expect(page.locator('#status')).to_have_text('Draft saved', timeout=10000)
                self.assertEqual(self.control(page, url, action).status, 200)
                self.assertEqual(process.wait(timeout=10), code)
                self.expect(page.locator('#status')).to_have_text('Session ended', timeout=10000)
                self.assertEqual(page.locator('.tiptap').get_attribute('contenteditable'), 'false')
                self.assertEqual(output.exists(), action == 'save-draft')
                self.assertEqual(Path(str(output) + '.draft.json').exists(), action == 'save-draft')

    def test_backend_restart_recovers_checkpoint_without_new_source(self):
        with self.session() as (page, process, output, _url):
            self.edit_first_cell(page, 'After restart ')
            self.expect(page.locator('#status')).to_have_text('Draft saved', timeout=10000)
            process.terminate()
            process.wait(timeout=10)
            page.close()
            restarted = subprocess.Popen(
                [sys.executable, '-m', 'folioforge', 'edit-table', str(output.parent / 'table.md'),
                 '--output', str(output), '--no-open'], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            other = self.browser.new_page()
            try:
                self.assertTrue(select.select([restarted.stdout], [], [], 20)[0])
                event = json.loads(restarted.stdout.readline())
                other.goto(event['url'])
                self.expect(other.locator('#status')).to_have_text('Recovered draft')
                self.expect(other.locator('.tiptap')).to_contain_text('After restart')
                self.assertFalse(output.exists())
                other.get_by_role('button', name='Save and Return', exact=True).click()
                self.assertEqual(restarted.wait(timeout=10), 0)
                self.assertIn('After restart', output.read_text())
            finally:
                other.close(run_before_unload=False)
                if restarted.poll() is None:
                    restarted.terminate()
                restarted.communicate(timeout=10)

    def test_closing_tab_never_commits_and_checkpoint_is_explicit(self):
        with self.session() as (page, process, output, url):
            self.edit_first_cell(page, 'Closed tab ')
            self.expect(page.locator('#status')).to_have_text('Draft saved', timeout=10000)
            page.close()
            other = self.browser.new_page()
            try:
                response = self.control(other, url, 'save')
                self.assertEqual(response.status, 200)
                state = response.json()
                # Browsers may omit pagehide on forced closure. Never infer a
                # commit from closure or depend on receiving a detach event.
                self.assertTrue(state['has_draft'])
                self.assertFalse(output.exists())
                self.assertEqual(self.control(other, url, 'save-draft').status, 200)
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertIn('Closed tab', output.read_text())
            finally:
                other.close()

    def test_org_merge_save_and_reopen(self):
        source = '| Name | Value |\n|------+-------|\n| *Alpha* | 12 |\n| Beta | 18 |\n'
        with self.session(source, '.org') as (page, process, output, _url):
            self.select_cells(page, 0, 1)
            page.get_by_role('button', name='Merge selected cells', exact=True).click()
            page.get_by_role('button', name='Table source', exact=True).click()
            self.expect(page.locator('#source')).to_contain_text('#+begin_export markdown', timeout=10000)
            page.get_by_role('button', name='Save and Return', exact=True).click()
            self.assertEqual(process.wait(timeout=20), 0)
            saved = output.read_text()
            self.assertIn('#+end_export', saved)
            self.assertNotIn('<table', saved)
        with self.session(saved, '.org') as (page, process, output, _url):
            self.assertEqual(page.locator('th[colspan="2"]').count(), 1)
            page.get_by_role('button', name='Cancel', exact=True).click()
            self.assertEqual(process.wait(timeout=10), 2)
