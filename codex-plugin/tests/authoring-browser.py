"""Real plugin UI: compact labels, ratio edits, wrapping, snippets and safety."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', tempfile.mkdtemp(prefix='ff-authoring-')))
shots.mkdir(parents=True, exist_ok=True)


def wait(frame, expression, timeout=180):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.15)
    raise AssertionError(frame.locator('body').inner_text()[-1500:])


host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                        env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(Path(__file__).with_name('authoring-sugar.md'))),
                        stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    source = Path(ready['source'])
    original = source.read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1600, 'height': 980}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        frame.locator('[data-format="slides"]').click()
        wait(frame, '!!matsugitWorkspace.state.rendered?.slides && !matsugitWorkspace.state.rendering')
        frame.locator('#auto').uncheck()
        frame.locator('#compact-markup').click()
        assert frame.locator('.ff-block-label').count() >= 3
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        frame.locator('select[aria-label="Column proportions"]').select_option('1:2')
        assert ':::: columns 1:2' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        page.screenshot(path=str(shots / 'compact-labels.png'))
        frame.locator('#compact-markup').click()
        assert frame.locator('.ff-block-label').count() == 0
        frame.evaluate(r'''() => {
          const e=matsugitWorkspace.editor, at=e.state.doc.length;
          e.dispatch({changes:{from:at,insert:'\n\n'},selection:{anchor:at+2}});e.focus();
        }''')
        page.keyboard.type('/columns-evidence')
        frame.locator('.cm-completionLabel').filter(has_text='/columns-evidence').click()
        selected = frame.evaluate('matsugitWorkspace.editor.state.sliceDoc(matsugitWorkspace.editor.state.selection.main.from,matsugitWorkspace.editor.state.selection.main.to)')
        assert selected == 'Supporting evidence.', selected
        page.keyboard.press('Tab')
        selected = frame.evaluate('matsugitWorkspace.editor.state.sliceDoc(matsugitWorkspace.editor.state.selection.main.from,matsugitWorkspace.editor.state.selection.main.to)')
        assert selected == 'What the evidence means.', selected
        frame.evaluate(r'''() => {
          const e=matsugitWorkspace.editor, text=e.state.doc.toString();
          const from=text.indexOf('| Experience'), to=text.indexOf('\n\n#### Implication');
          e.dispatch({selection:{anchor:from,head:to}});e.focus();
        }''')
        frame.locator('#insert').click()
        frame.locator('.cm-completionLabel').filter(has_text='/chart-barh').click()
        text = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        assert text.count('| Baseline | 12 |') == 1
        assert 'type="barh" unit="units"' in text
        assert source.read_text() == original
        # Org completion must not escape an example through an unrelated end.
        frame.evaluate(r'''() => {
          const w=matsugitWorkspace;w.state.name='example.org';
          const text='#+begin_src text\n#+end_columns\n\n/take';
          w.editor.dispatch({changes:{from:0,to:w.editor.state.doc.length,insert:text},selection:{anchor:text.length}});
        }''')
        frame.locator('#insert').click()
        page.wait_for_timeout(500)
        assert frame.locator('.cm-completionLabel').count() == 0
        for width,height in [(390,844),(768,1024)]:
            page.set_viewport_size({'width':width,'height':height})
            page.screenshot(path=str(shots / f'authoring-{width}.png'))
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        assert source.read_text() == original
        print('PASS: labels, ratio + undo, Tab fields, selected-table chart, Org guard, responsive layout; no source save', flush=True)
        page.close(run_before_unload=False)
        browser.close()
finally:
    host.terminate()
    host.wait(timeout=20)
