"""Real plugin UI: plain-language check, one-click fixes and the layout picker."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', tempfile.mkdtemp(prefix='matsugit-check-')))
shots.mkdir(parents=True, exist_ok=True)


def wait(frame, expression, timeout=180):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.15)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1500:])


SETTLED = '!matsugitWorkspace.state.rendering && matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision'
TEXT = 'matsugitWorkspace.editor.state.doc.toString()'
host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                        env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(Path(__file__).with_name('product-review.md')),
                                 MATSUGIT_TEST_CHAT='standard'),
                        stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    source = Path(ready['source'])
    original = source.read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1500, 'height': 950}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        frame.locator('[data-format="slides"]').click()
        wait(frame, '!!matsugitWorkspace.state.rendered?.slides && ' + SETTLED)

        # First screen: formatted text, a labelled Add button and a visible verdict.
        assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'visual'
        assert frame.locator('#insert').inner_text().strip() == 'Add'
        chip = frame.locator('#check-status')
        assert chip.inner_text().strip() == 'No problems' and chip.get_attribute('data-kind') == 'ok'
        assert frame.locator('#check-panel').is_hidden() and frame.locator('#preview-stale').is_hidden()

        def replace(text):
            frame.evaluate('''text => { const e = matsugitWorkspace.editor;
              e.dispatch({changes: {from: 0, to: e.state.doc.length, insert: text}}); }''', text)

        # Beginner mistakes: four columns (the renderer refuses) and a mistyped block.
        broken = (original.replace(':::: rows', ':::: columns')
                  .replace('#### Decision', '#### A\nx\n\n#### B\ny\n\n#### Decision')
                  .replace('::: takeaway\nApprove', '::: takaway\nApprove'))
        assert broken != original
        replace(broken)
        wait(frame, 'document.getElementById("check-label").textContent === "1 to fix"', 20)
        wait(frame, '!!matsugitWorkspace.state.renderError && !matsugitWorkspace.state.rendering', 60)
        notice = frame.locator('#notice-text').inner_text()
        assert "can't update yet" in notice and '4 parts' in notice and '2 or 3' in notice, notice
        assert frame.locator('#preview-stale').is_visible()
        page.screenshot(path=str(shots / 'check-mistake.png'))
        frame.locator('#notice-check').click()
        items = frame.locator('.check-item')
        assert items.count() == 2
        first = items.nth(0).inner_text()
        assert 'Slide 1: Start with a focused pilot, line 12' in first and 'To fix' in first, first
        assert items.nth(1).get_attribute('data-severity') == 'tip'
        # The open list replaces the duplicate banner.
        assert frame.locator('#notice').is_hidden()
        page.screenshot(path=str(shots / 'check-panel.png'))

        # Show moves the cursor to the reported line.
        items.nth(0).get_by_role('button', name='Show').click()
        line = frame.evaluate('matsugitWorkspace.editor.state.doc.lineAt(matsugitWorkspace.editor.state.selection.main.head).text')
        assert line == ':::: columns', line

        # A fix edits the draft as one Undo step and never saves.
        items.nth(1).locator('.check-fix').click()
        assert '::: takeaway\nApprove' in frame.evaluate(TEXT)
        assert frame.locator('.check-item').count() == 1
        assert 'Nothing was saved' in frame.locator('#check-feedback').inner_text()
        frame.locator('#undo').click()
        assert frame.evaluate(TEXT) == broken
        wait(frame, 'document.querySelectorAll(".check-item").length === 2', 10)
        assert source.read_text() == original

        # Ask AI carries the problem in the user's own request box; nothing is sent yet.
        frame.locator('.check-item').nth(0).get_by_role('button', name='Ask AI').click()
        prompt = frame.locator('#slide-agent-prompt').input_value()
        assert '4 parts' in prompt and '`' not in prompt, prompt
        frame.locator('#slide-agent-close').click()
        assert json.loads(page.evaluate('fetch("/test-messages").then(r => r.text())')) == []

        # Repairing the text clears the verdict, the banner and the stale marker.
        replace(original)
        wait(frame, 'document.getElementById("check-label").textContent === "No problems"', 20)
        wait(frame, '!matsugitWorkspace.state.renderError && ' + SETTLED, 120)
        assert frame.locator('#preview-stale').is_hidden() and frame.locator('.check-item').count() == 0
        frame.locator('#check-close').click()
        assert frame.locator('#check-panel').is_hidden()

        # The picker works from the top of the file, where the old menu did nothing.
        frame.evaluate('matsugitWorkspace.editor.dispatch({selection: {anchor: 0}})')
        frame.locator('#insert').click()
        assert frame.locator('#gallery-dialog').is_visible()
        assert frame.locator('.gallery-card').count() >= 30
        assert 'end of the deck' in frame.locator('#gallery-groups').inner_text()
        page.screenshot(path=str(shots / 'gallery.png'))
        frame.locator('#gallery-search').fill('compare')
        assert frame.locator('.gallery-card').count() == 1
        page.keyboard.press('Enter')
        assert frame.locator('#gallery-dialog').is_hidden()
        text = frame.evaluate(TEXT)
        assert text.startswith(original.rstrip('\n')) and text.endswith(':::: comparison\n#### Option A\n- Strength.\n- Constraint.\n\n#### Option B\n- Strength.\n- Constraint.\n::::\n'), text[-300:]
        assert frame.locator('#check-label').inner_text() == 'No problems'

        # A part goes into the slide being edited; a second takeaway is never created.
        frame.evaluate('''() => { const e = matsugitWorkspace.editor, at = e.state.doc.toString().indexOf('Start with one customer');
          e.dispatch({selection: {anchor: at}}); }''')
        frame.locator('#insert').click()
        assert 'slide 1: Start with a focused pilot' in frame.locator('#gallery-groups').inner_text()
        frame.locator('.gallery-card[data-recipe="takeaway"]').click()
        after = frame.evaluate(TEXT)
        assert after == text
        selected = frame.evaluate('matsugitWorkspace.editor.state.sliceDoc(matsugitWorkspace.editor.state.selection.main.from, matsugitWorkspace.editor.state.selection.main.to)')
        assert selected == 'Approve the pilot; expand only when all three gates pass.', selected
        assert 'already has a takeaway' in frame.locator('#notice-text').inner_text()

        # Placeholders are selected for typing, and Tab moves to the next one.
        frame.locator('#insert').click()
        frame.locator('.gallery-card[data-recipe="columns"]').click()
        selected = frame.evaluate('matsugitWorkspace.editor.state.sliceDoc(matsugitWorkspace.editor.state.selection.main.from, matsugitWorkspace.editor.state.selection.main.to)')
        assert selected == 'First column', selected
        wait(frame, 'document.getElementById("check-label").textContent === "No problems"', 10)

        for width, height in [(390, 844), (760, 800)]:
            page.set_viewport_size({'width': width, 'height': height})
            frame.locator('#check-status').click()
            frame.locator('#insert').click()
            page.screenshot(path=str(shots / f'check-gallery-{width}.png'))
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
            frame.locator('#gallery-close').click()
            frame.locator('#check-close').click()
        assert not errors, errors
        assert source.read_text() == original
        print('PASS: verdict chip, located findings, Show, Fix + Undo, Ask AI prefill, stale marker, picker placement; no source save', flush=True)
        page.close(run_before_unload=False)
        browser.close()
finally:
    host.terminate()
    host.wait(timeout=20)
