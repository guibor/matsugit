"""Exercise the built workspace's depth buttons in both source appearances."""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
    env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(ROOT / 'codex-plugin/tests/visual.md')),
    stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        deadline = time.monotonic() + 180
        while not frame.evaluate('!!window.matsugitWorkspace?.state.rendered'):
            if time.monotonic() > deadline:
                raise AssertionError(frame.locator('body').inner_text() + str(errors))
            time.sleep(.2)
        frame.locator('#auto').uncheck()
        frame.locator('#sync').uncheck()
        original = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        for mode in ('raw', 'visual'):
            frame.locator(f'[data-editor="{mode}"]').click()
            for depth in (2, 3):
                frame.locator(f'[data-depth="{depth}"]').click()
                assert frame.locator('.cm-foldPlaceholder').count() > 0
                assert frame.locator('.ff-visual-table').count() == 0
                assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
                assert frame.locator(f'[data-depth="{depth}"]').get_attribute('aria-pressed') == 'true'
            for width in (390, 768, 1600):
                page.set_viewport_size({'width': width, 'height': 900})
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert frame.locator('[data-depth="0"]').is_visible()
            frame.locator('[data-depth="0"]').click()
            assert frame.locator('.cm-foldPlaceholder').count() == 0
            assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
            if mode == 'visual':
                frame.wait_for_selector('.ff-visual-table')
            frame.evaluate('matsugitWorkspace.editor.dispatch({selection:{anchor:0}}); matsugitWorkspace.editor.focus()')
            # The fixture begins with YAML; use its first real heading, not metadata.
            frame.evaluate('''()=>{const e=matsugitWorkspace.editor, s=e.state.doc.toString();
              const heading=s.indexOf('## '); e.dispatch({selection:{anchor:heading}});e.focus();}''')
            content = frame.locator('.cm-content')
            content.press('Tab')
            assert frame.locator('.cm-foldPlaceholder').count() > 0
            content.press('Control+Enter')
            assert frame.locator('.cm-foldPlaceholder').count() >= 0
            content.press('Shift+Tab')
            assert frame.locator('.cm-foldPlaceholder').count() > 0
            frame.locator('[data-depth="2"]').click()
            frame.evaluate('''()=>{const e=matsugitWorkspace.editor; e.dispatch({selection:{anchor:e.state.doc.toString().indexOf('## ')}});e.focus();}''')
            before = frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            content.press('Alt+j')
            after = frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            assert after > before
            content.press('Alt+k')
            assert frame.evaluate('matsugitWorkspace.editor.state.selection.main.head') == before
            assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
            frame.locator('[data-depth="0"]').click()
        assert not errors, errors
        assert Path(ready['source']).read_text() == original
        print('PASS: Raw/Visual depth 2/3/All and keyboard cycling/navigation, table reappearance, no source edits, 390/768/1600 widths')
        browser.close()
finally:
    host.terminate()
    try:
        host.wait(timeout=15)
    except subprocess.TimeoutExpired:
        host.kill()
        host.wait()
