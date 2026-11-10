"""A sandboxed host with no download API can explicitly save the prepared PDF."""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.2)
    raise AssertionError(frame.locator('body').inner_text()[-3000:])


server = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                          env=dict(os.environ, MATSUGIT_TEST_DOWNLOAD='blocked'),
                          stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(server.stdout.readline())
    source = Path(ready['source'])
    original = source.read_bytes()
    downloads = Path(ready['downloads'])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width':1440,'height':1000}, accept_downloads=True)
        received, errors = [], []
        page.on('download', lambda download: received.append(download))
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{ready['port']}")
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        frame.locator('#auto').uncheck()
        frame.locator('#download').click()
        wait(frame, '!document.getElementById("export-run").disabled')
        frame.locator('#export-format').select_option('pdf')
        frame.locator('#export-run').click()
        wait(frame, 'document.getElementById("export-ready").hidden === false && !document.getElementById("export-run").disabled')
        assert 'Receipt cannot be confirmed' in frame.locator('#export-progress').inner_text()
        assert not received, 'Sandboxed browser download should be blocked in this fixture'
        assert not downloads.exists(), 'No filesystem save before the explicit user action'
        assert str(downloads) in frame.locator('#export-local-target').inner_text()
        assert frame.locator('#export-save-local').is_visible()
        page.screenshot(path='/tmp/matsugit-export-blocked-desktop.png')
        frame.locator('#export-save-local').click()
        wait(frame, '!document.getElementById("export-saved-path").hidden')
        saved = Path(frame.locator('#export-saved-path').input_value())
        assert saved.parent == downloads
        assert saved.read_bytes().startswith(b'%PDF-') and saved.stat().st_size > 1024
        assert (saved.stat().st_mode & 0o777) == 0o600
        assert 'Saved on' in frame.locator('#export-progress').inner_text()
        assert frame.locator('#export-save-local').is_disabled()
        assert page.evaluate('exportRequests') == 1, 'Saving the prepared PDF must not render it again'
        assert not received
        for width, height in ((1440,1000),(390,844)):
            page.set_viewport_size({'width':width, 'height':height})
            box = frame.locator('#export-dialog').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert box['y'] >= 0 and box['y'] + box['height'] <= height
            for selector in ('#export-save-local','#export-saved-path'):
                item = frame.locator(selector).bounding_box()
                assert item['x'] >= box['x'] and item['x']+item['width'] <= box['x']+box['width']
            page.screenshot(path=f'/tmp/matsugit-export-local-{width}.png')
        assert source.read_bytes() == original
        assert not errors, errors
        browser.close()
        print('Blocked download -> explicit local PDF save, verified bytes/path, no re-render, desktop/mobile layout passed')
finally:
    server.terminate()
    server.wait(timeout=20)
