"""Real plugin UI: autosave writes the file after a pause and never overwrites a newer one."""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=30):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('#save-state').inner_text() + ' | ' + frame.locator('#notice-text').inner_text())


host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                        env=dict(os.environ, MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_HOST=os.environ.get('MATSUGIT_TEST_HOST', ''),
                                 MATSUGIT_TEST_DEFAULT_SAVE='1', MATSUGIT_TEST_OPEN_OPTIONS='{}'), stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    source = Path(ready['source'])
    original = source.read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading')
        frame.locator('#auto').uncheck()
        saved = 'document.getElementById("save-state").textContent.trim() === "Saved to file"'

        def type_at_end(text):
            frame.evaluate('(() => { const e = matsugitWorkspace.editor; e.dispatch({selection: {anchor: e.state.doc.length}}); e.focus(); })()')
            page.keyboard.type(text, delay=20)

        # Explicit Save remains the default. Autosave requires an intentional opt-in.
        assert frame.evaluate('matsugitWorkspace.state.autosave') is False
        type_at_end('\nFirst autosaved line.')
        page.wait_for_timeout(2200)
        assert source.read_text() == original
        assert frame.locator('#save-state').inner_text().strip() == 'Unsaved draft'
        frame.locator('#more').click()
        frame.locator('#autosave').check()
        page.keyboard.press('Escape')
        frame.evaluate('matsugitWorkspace.editor.focus()')
        assert frame.evaluate('matsugitWorkspace.state.autosave') is True
        assert frame.locator('#save-state').inner_text().strip() == 'Saving soon'
        assert source.read_text() == original
        wait(frame, saved, 10)
        assert source.read_text() == original + '\nFirst autosaved line.'
        assert frame.evaluate('matsugitWorkspace.editor.hasFocus')

        # A file changed by someone else is never overwritten: the draft is kept for review.
        source.write_text(source.read_text().replace('First autosaved line.', 'Changed by another program.'))
        frame.evaluate('(() => { const e = matsugitWorkspace.editor; e.dispatch({changes: {from: 0, insert: " "}}); })()')
        wait(frame, 'matsugitWorkspace.state.conflict || ' + saved, 15)
        page.wait_for_timeout(2500)
        on_disk = source.read_text()
        assert 'Changed by another program.' in on_disk, on_disk[-200:]

        # The choice is one click away, and turning it off restores explicit Save.
        if frame.evaluate('matsugitWorkspace.state.conflict'):
            frame.evaluate('matsugitWorkspace.state.conflict = false; matsugitWorkspace.reload(true, true)')
            wait(frame, saved, 15)
        frame.locator('#more').click()
        assert frame.locator('#more-panel').is_visible()
        frame.locator('#autosave').uncheck()
        page.keyboard.press('Escape')
        assert frame.locator('#more-panel').is_hidden()
        before = source.read_text()
        type_at_end('\nNot saved until asked.')
        page.wait_for_timeout(3000)
        assert source.read_text() == before
        assert frame.locator('#save-state').inner_text().strip() == 'Unsaved draft'
        frame.locator('#save').click()
        wait(frame, saved, 10)
        assert source.read_text().endswith('\nNot saved until asked.')
        assert not errors, errors
        print('PASS: explicit Save by default, opt-in autosave, focus kept, external changes protected, opt-out', flush=True)
        browser.close()
finally:
    host.terminate()
    host.wait(timeout=20)
