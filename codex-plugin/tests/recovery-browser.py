"""Synthetic recovery UI lifecycle, including a real MCP process restart.

Uses the same local MCP/Chromium harness and QUARTO environment as browser.py.
No user files, production recovery directories or live Codex sessions are used.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

def wait(frame, expression, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.2)
    raise AssertionError((expression, frame.locator('body').inner_text()[-1000:]))

def checkpoint(frame):
    frame.evaluate('matsugitWorkspace.flushRecovery()')
    wait(frame, 'document.getElementById("recovery-status").textContent === "Draft backed up"', 20)

shots = Path(tempfile.mkdtemp(prefix='matsugit-recovery-shots-'))
server = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(server.stdout.readline())
    url = f"http://127.0.0.1:{ready['port']}"
    source, storage = Path(ready['source']), Path(ready['recovery'])
    original = source.read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())

        def opened(suffix=''):
            page.goto(url + suffix)
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace && !matsugitWorkspace.state.loading && !!matsugitWorkspace.state.name')
            wait(frame, '!!matsugitWorkspace.state.rendered')
            return frame

        frame = opened()
        frame.locator('#auto').uncheck()
        frame.locator('#sync').uncheck()
        frame.locator('#theme').select_option('default')
        frame.locator('[data-format="slides"]').click()
        wait(frame, '!!matsugitWorkspace.state.rendered?.slides && !matsugitWorkspace.state.rendering')
        preview = frame.locator('#preview').element_handle().content_frame()
        wait(preview, '!!window.Reveal?.isReady()')
        preview.evaluate('Reveal.slide(2)')
        wait(frame, 'matsugitWorkspace.state.positions.slides.h === 2')
        frame.locator('#divider').focus()
        page.keyboard.press('ArrowLeft')
        frame.evaluate('''() => {
          const w = matsugitWorkspace;
          w.editor.dispatch({changes:{from:0,insert:'<!-- Recover שלום -->\\n'}, selection:{anchor:31}});
        }''')
        checkpoint(frame)
        draft = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        width = frame.evaluate('document.documentElement.style.getPropertyValue("--source-size")')
        assert source.read_text() == original
        print('Unsaved Unicode draft and workspace checkpointed without saving source', flush=True)

        # Close the viewer, restart the MCP server, then reopen the same file.
        page.goto('about:blank')
        response = page.request.post(url + '/restart')
        assert response.ok
        frame = opened()
        frame.locator('#recovery-banner').wait_for(state='visible')
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        assert frame.locator('#theme').input_value() == 'default'
        assert frame.evaluate('matsugitWorkspace.state.format') == 'slides'
        assert frame.evaluate('document.documentElement.style.getPropertyValue("--source-size")') == width
        assert not frame.locator('#sync').is_checked()
        assert not frame.locator('#auto').is_checked()
        preview = frame.locator('#preview').element_handle().content_frame()
        wait(preview, '!!window.Reveal?.isReady() && Reveal.getIndices().h === 2')
        frame.locator('#restore-draft').click()
        wait(frame, 'matsugitWorkspace.editor.state.doc.toString().startsWith("<!-- Recover")')
        checkpoint(frame)
        assert frame.evaluate('matsugitWorkspace.editor.state.selection.main.head') == 31
        assert source.read_text() == original
        assert frame.locator('#save').is_enabled()
        print('Real backend restart: draft offer, theme, split width, caret and selected slide restored', flush=True)
        page.screenshot(path=str(shots / 'recovered-desktop.png'))

        # Another viewer must not overwrite the first viewer's recovery file.
        page2 = browser.new_page()
        page2.goto(url)
        frame2 = page2.frames[1]
        wait(frame2, '!!window.matsugitWorkspace?.state.rendered')
        frame2.locator('#dismiss-recovery').click()
        frame2.evaluate("matsugitWorkspace.editor.dispatch({changes:{from:0,insert:'Second viewer\\n'}})")
        checkpoint(frame2)
        copies = [json.loads(f.read_text()) for f in storage.glob('*.json')]
        assert any(r['text'] == draft for r in copies)
        assert any(r['text'].startswith('Second viewer') for r in copies)
        page2.close()
        print('Simultaneous viewers retain independent copies', flush=True)

        # A newer disk version must not be replaced by recovered text.
        page.goto('about:blank')
        source.write_text('# External newer version\n')
        frame = opened()
        frame.locator('#restore-draft').click()
        wait(frame, 'matsugitWorkspace.state.conflict')
        assert frame.locator('#save').get_attribute('aria-label') == 'Review changes before saving'
        assert source.read_text() == '# External newer version\n'
        frame.locator('#reload').click()
        wait(frame, '!matsugitWorkspace.state.conflict && matsugitWorkspace.editor.state.doc.toString() === "# External newer version\\n"')
        assert source.read_text() == '# External newer version\n'
        print('External edit requires review before Save; explicit Reload resolves conflict', flush=True)

        # Unnamed workspaces are recoverable without borrowing the host file path.
        frame = opened('?untitled')
        frame.locator('#auto').uncheck()
        frame.evaluate("matsugitWorkspace.editor.dispatch({changes:{from:0,insert:'Unnamed draft\\n'}})")
        checkpoint(frame)
        page.goto('about:blank')
        frame = opened('?untitled')
        frame.locator('#restore-draft').click()
        wait(frame, 'matsugitWorkspace.editor.state.doc.toString().startsWith("Unnamed draft")')
        checkpoint(frame)
        assert frame.locator('#save').is_disabled()
        assert any(r['owner'] is None and r['text'].startswith('Unnamed draft')
                   for r in (json.loads(f.read_text()) for f in storage.glob('*.json')))
        frame.locator('#recover').click()
        frame.locator('.recovery-entry').first.wait_for()
        count = len(list(storage.glob('*.json')))
        frame.locator('[aria-label="Delete recovery copy"]').last.click()
        wait(frame, f'document.querySelectorAll(".recovery-entry").length === {count - 1}')
        assert len(list(storage.glob('*.json'))) == count - 1
        print('Unnamed drafts and explicitly confirmed recovery deletion verified', flush=True)
        page.screenshot(path=str(shots / 'recovery-picker-desktop.png'))
        for width in (390, 768):
            page.set_viewport_size({'width': width, 'height': 844})
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert frame.locator('#recovery-dialog').bounding_box()['width'] <= width
            page.screenshot(path=str(shots / f'recovery-picker-{width}.png'))
        frame.locator('#close-recovery').click()
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.goto('about:blank')
        source.write_text(original)
        frame = opened('?file')
        if frame.locator('#recovery-banner').is_visible():
            frame.locator('#dismiss-recovery').click()
        frame.locator('#auto').uncheck()
        frame.evaluate("matsugitWorkspace.editor.dispatch({changes:{from:0,insert:'<!-- Host draft -->\\n'}})")
        checkpoint(frame)
        page.goto('about:blank')
        frame = opened('?file')
        frame.locator('#restore-draft').click()
        wait(frame, 'matsugitWorkspace.editor.state.doc.toString().startsWith("<!-- Host draft")')
        assert source.read_text() == original
        frame.locator('#save').click()
        wait(frame, '!matsugitWorkspace.state.saving && matsugitWorkspace.state.base.startsWith("<!-- Host draft")')
        checkpoint(frame)
        assert source.read_text().startswith('<!-- Host draft -->')
        print('Host resource URI recovery and subsequent explicit Save verified', flush=True)
        # Failure is visible, does not discard editing, and retries on the next change.
        storage.chmod(0o755)
        try:
            frame.evaluate("matsugitWorkspace.editor.dispatch({changes:{from:0,insert:'<!-- Still editable -->\\n'}})")
            frame.evaluate('matsugitWorkspace.flushRecovery()')
            wait(frame, 'document.getElementById("recovery-status").textContent === "Recovery unavailable"')
            assert not source.read_text().startswith('<!-- Still editable')
        finally:
            storage.chmod(0o700)
        frame.evaluate("matsugitWorkspace.editor.dispatch({changes:{from:0,insert:'<!-- Retry -->\\n'}})")
        checkpoint(frame)
        print('Checkpoint failure is visible and editing remains available', flush=True)
        assert not errors, errors
        browser.close()
        print('Recovery browser tests passed; screenshots: ' + str(shots), flush=True)
finally:
    server.terminate()
    server.wait(timeout=15)
