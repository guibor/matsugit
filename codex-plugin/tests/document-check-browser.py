"""Reading checks remain independent of failed slide previews and cached views."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
READING = ('---\ntitle: Reading check\nslide-layout: structured\n---\n\n## Concepts\n\nBody.\n\n'
           '::: takeaway\nFirst point.\n:::\n\n::: takeaway\nSecond point.\n:::\n')
SETTLED = '!matsugitWorkspace.state.rendering && matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision && document.getElementById("preview-stale").hidden'


def wait(frame, expression):
    until = time.monotonic() + 120
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1500:])


with tempfile.TemporaryDirectory(prefix='matsugit-document-check-') as folder:
    source = Path(folder) / 'reading.md'
    source.write_text(READING)
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                            env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(source),
                                     MATSUGIT_TEST_CHAT='standard'), stdout=subprocess.PIPE, text=True)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1500, 'height': 950})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace')
            frame.locator('[data-format="document"]').click()
            wait(frame, SETTLED)
            chip = frame.locator('#check-status')
            assert chip.get_attribute('data-kind') == 'ok'
            for _ in range(2):
                frame.locator('[data-format="slides"]').click()
                wait(frame, '!!matsugitWorkspace.state.renderError && !matsugitWorkspace.state.rendering')
                assert 'takeaway' in str(frame.evaluate('matsugitWorkspace.state.renderError')).lower()
                assert chip.get_attribute('data-kind') == 'problem'
                frame.locator('[data-format="document"]').click()
                wait(frame, SETTLED)
                assert chip.inner_text().strip() == 'Check draft'
                assert frame.locator('#notice').is_hidden()
                assert frame.locator('#preview-stale').is_hidden()
            frame.locator('#check-status').click()
            assert frame.locator('#check-panel').get_attribute('aria-label') == 'Document check'
            assert frame.locator('.check-item').count() == 0
            if os.environ.get('MATSUGIT_SCREENSHOTS'):
                shots = Path(os.environ['MATSUGIT_SCREENSHOTS'])
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / 'document-check-clean.png'))
            frame.evaluate('''text => { const e = matsugitWorkspace.editor;
              e.dispatch({changes: {from: 0, to: e.state.doc.length, insert: text}}); }''',
                           READING + '\n![Unavailable](missing-fixture-image.png)\n')
            wait(frame, '!!matsugitWorkspace.state.renderError && !matsugitWorkspace.state.rendering')
            assert frame.locator('.check-item[data-code="renderer"]').count() == 1
            assert chip.get_attribute('data-kind') == 'problem'
            assert not errors, errors
            assert Path(ready['source']).read_text() == READING
            print('PASS: reading checks, failed slides, cached document, genuine reading failure; no source writes', flush=True)
            browser.close()
    finally:
        host.terminate()
        host.wait(timeout=20)
