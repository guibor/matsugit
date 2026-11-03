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
        frame.locator('#close-export').click()
        frame.locator('#publish').click()
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
            frame.locator('#publish').click()
            wait(frame, '!document.getElementById("publish-review").disabled')
            frame.locator('#repository-toggle').click()
            bounds = frame.locator('#publish-dialog').bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= height
            frame.locator('#close-publish').click()
        assert source.read_text() == original
        assert not errors, errors
        browser.close()
        print('Real PowerPoint download, publish refusal and desktop/mobile dialogs passed.')
finally:
    server.terminate(); server.wait(timeout=20)
