"""Real MCP export/download and publish-error UI; never publishes a document."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.25)
    raise AssertionError(frame.locator('body').inner_text()[-3000:])


server = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(server.stdout.readline())
    source = Path(ready['source']); original = source.read_text()
    with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width':1440,'height':900}, accept_downloads=True)
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{ready['port']}")
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        frame.locator('#auto').uncheck()
        frame.locator('#download').click()
        wait(frame, '!document.getElementById("export-run").disabled')
        frame.locator('#export-format').select_option('pptx')
        assert frame.locator('#pptx-warning').is_visible()
        with page.expect_download(timeout=180000) as download:
            frame.locator('#export-run').click()
        dest = Path(directory) / 'download.pptx'; download.value.save_as(dest)
        with zipfile.ZipFile(dest) as archive:
            assert 'ppt/presentation.xml' in archive.namelist()
        wait(frame, '!document.getElementById("export-run").disabled')
        assert frame.locator('#export-ready').is_visible()
        if os.environ.get('MATSUGIT_TEST_DOWNLOAD') in ('standard','legacy'):
            assert 'Sent to host downloads' in frame.locator('#export-progress').inner_text()
            assert page.evaluate('downloadRequests[0].type') == 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            # A cancelled host download retains the bytes; retry must not render again.
            page.evaluate('rejectDownload=true')
            frame.locator('#export-download-retry').click()
            wait(frame,'!document.getElementById("export-download-retry").disabled')
            assert 'cancelled or declined' in frame.locator('#export-progress').inner_text()
            with page.expect_download() as retry:
                frame.locator('#export-download-retry').click()
            retried = Path(directory)/'retried.pptx'; retry.value.save_as(retried)
            assert retried.read_bytes() == dest.read_bytes()
            assert page.evaluate('exportRequests') == 1
            assert len(page.evaluate('downloadRequests')) == 3
        else:
            assert 'Receipt cannot be confirmed' in frame.locator('#export-progress').inner_text()
        wait(frame,'!document.getElementById("export-download-retry").disabled')
        # Source export carries the unsaved draft, including Unicode, without saving.
        frame.evaluate('''() => {const e=matsugitWorkspace.editor;e.dispatch({changes:{from:e.state.doc.length,insert:'\\n\\nUnsaved \\u05e9\\u05dc\\u05d5\\u05dd\\n'}})}''')
        draft = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        frame.locator('#export-format').select_option('source')
        with page.expect_download() as raw:
            frame.locator('#export-run').click()
        raw_file = Path(directory)/'source.md'; raw.value.save_as(raw_file)
        assert raw_file.read_text() == draft
        wait(frame,'!document.getElementById("export-run").disabled')
        assert frame.locator('#export-dialog').is_visible()
        frame.locator('#close-export').click()
        frame.evaluate('''()=>{const e=matsugitWorkspace.editor;e.dispatch({selection:{anchor:e.state.doc.toString().indexOf('12 days')}});e.focus();}''')
        page.keyboard.press('Alt+.')
        wait(frame,'document.getElementById("table-dialog").open && !document.getElementById("table-apply").disabled')
        with page.expect_download() as table:
            frame.locator('#table-download').click()
        table_file = Path(directory)/'table.html'; table.value.save_as(table_file)
        assert '<table' in table_file.read_text() and '12 days' in table_file.read_text()
        wait(frame,'!document.getElementById("table-download").disabled')
        frame.locator('#table-close').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == draft
        frame.locator('#publish').dispatch_event('click')
        wait(frame, '!document.getElementById("publish-review").disabled')
        frame.locator('#repository-toggle').click()
        frame.locator('#repository-host').fill('not/a/host')
        frame.locator('#repository-list').click()
        wait(frame, '!document.getElementById("repository-list").disabled')
        assert 'hostname' in frame.locator('#publish-progress').inner_text()
        frame.locator('#repository-toggle').click()
        frame.locator('#publish-build').select_option('ci')
        frame.locator('#publish-review').click()
        wait(frame, '!document.getElementById("publish-review").disabled')
        assert frame.locator('#publish-confirmation').is_hidden()
        assert frame.locator('#publish-progress').inner_text()
        frame.locator('#close-publish').click()
        for width, height in ((1440,900),(390,844)):
            page.set_viewport_size({'width':width, 'height':height})
            frame.locator('#download').click()
            wait(frame, '!document.getElementById("export-run").disabled')
            bounds = frame.locator('#export-dialog').bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height
            page.screenshot(path=f'/tmp/matsugit-export-ui-{width}.png')
            frame.locator('#close-export').click()
            frame.locator('#publish').dispatch_event('click')
            wait(frame, '!document.getElementById("publish-review").disabled')
            frame.locator('#repository-toggle').click()
            bounds = frame.locator('#publish-dialog').bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height
            frame.locator('#close-publish').click()
        assert source.read_text() == original
        assert not errors, errors
        browser.close()
        print('PowerPoint bytes, prepared retry/cancel, unsaved Unicode source, table download, publish refusal and responsive dialogs passed: '+os.environ.get('MATSUGIT_TEST_DOWNLOAD','browser'))
finally:
    server.terminate(); server.wait(timeout=20)
