"""Handoff opens the real browser editor, with explicit draft saving and no copies."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1800:])


with tempfile.TemporaryDirectory(prefix='matsugit-browser-button-') as folder:
    source = Path(folder) / 'deck.md'
    original = '# Synthetic\n\n## One\n\nOriginal sentence.\n'
    source.write_text(original)
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
        env=dict(os.environ, MATSUGIT_TEST_SOURCE=str(source), MATSUGIT_BROWSER_OPEN='0',
                 MATSUGIT_BROWSER_IDLE_MS='2000', MATSUGIT_BROWSER_UNUSED_MS='10000'),
        stdout=subprocess.PIPE, text=True)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440, 'height':950})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.evaluate('''()=>{const e=matsugitWorkspace.editor;
                e.dispatch({changes:{from:e.state.doc.length,insert:'\\nMy unsaved typing.\\n'}});}''')
            draft = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            frame.locator('#browser-open').click()
            assert frame.locator('#browser-confirm').inner_text() == 'Save and open'
            assert source.read_text() == original
            frame.locator('#browser-cancel').click()
            assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == draft
            assert source.read_text() == original
            frame.locator('#browser-open').click()
            frame.locator('#browser-confirm').click()
            frame.locator('#browser-link').wait_for(state='visible', timeout=60000)
            url = frame.locator('#browser-link').get_attribute('href')
            assert source.read_text() == draft
            assert 'computer only' in frame.locator('#browser-status').inner_text()
            frame.locator('#browser-link').click()
            page.wait_for_function('url => window.openedLinks?.at(-1) === url', arg=url)
            if os.environ.get('MATSUGIT_SCREENSHOTS'):
                shots = Path(os.environ['MATSUGIT_SCREENSHOTS'])
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / 'browser-handoff.png'))
            page.set_viewport_size({'width':390, 'height':844})
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert frame.locator('#browser-link').is_visible()
            if os.environ.get('MATSUGIT_SCREENSHOTS'):
                page.screenshot(path=str(shots / 'browser-handoff-narrow.png'))
            page.set_viewport_size({'width':1440, 'height':950})
            other = browser.new_page(viewport={'width':1440, 'height':950})
            other.on('pageerror', lambda error: errors.append(str(error)))
            other.goto(url)
            editor = other.frames[1]
            wait(editor, '!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            assert editor.evaluate('matsugitWorkspace.editor.state.doc.toString()') == draft
            assert editor.evaluate('matsugitWorkspace.state.path') == str(source.resolve())
            assert not editor.evaluate('matsugitWorkspace.state.autosave')
            assert editor.locator('#browser-open').is_hidden()
            editor.locator('#auto').uncheck()
            editor.evaluate('''()=>{const e=matsugitWorkspace.editor;
                e.dispatch({changes:{from:e.state.doc.length,insert:'\\nEdited in browser.\\n'}});}''')
            editor.locator('#save').click()
            wait(editor, '!matsugitWorkspace.state.saving && matsugitWorkspace.state.base.includes("Edited in browser.")')
            assert source.read_text() == draft + '\nEdited in browser.\n'
            frame.locator('#browser-cancel').click()
            # A clean handoff never calls Save; unknown writers still get review.
            wait(frame, '!!matsugitWorkspace.state.incomingReady')
            frame.locator('#browser-open').click()
            assert 'review' in frame.locator('#browser-status').inner_text()
            assert frame.locator('#browser-link').is_hidden()
            frame.locator('#browser-cancel').click()
            frame.locator('#accept-update').click()
            wait(frame, '!matsugitWorkspace.state.incomingReady')
            before = source.stat().st_mtime_ns
            frame.locator('#browser-open').click()
            frame.locator('#browser-link').wait_for(state='visible', timeout=60000)
            assert source.stat().st_mtime_ns == before
            assert not errors, errors
            browser.close()
            print('PASS: cancel retains draft; save and open; same-file browser editing; incoming review; clean open is read-only')
    finally:
        host.terminate()
        host.wait(timeout=20)
