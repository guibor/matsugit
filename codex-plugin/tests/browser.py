"""Exercise the built app through a local MCP host, with the real renderer.

QUARTO=/path/to/quarto /path/to/playwright-python tests/browser.py
Optional FOLIOFORGE_SCREENSHOTS writes synthetic UI review screenshots.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
def wait_until(frame, expression, timeout=180):
    # Poll through DevTools; Playwright's in-page wait_for_function uses eval,
    # which the intentionally restrictive app CSP must refuse.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.25)
    diagnostic = frame.evaluate('({status:document.getElementById("status")?.textContent,notice:document.getElementById("notice-text")?.textContent})')
    raise AssertionError(f'{expression}: {diagnostic}')

shots = Path(os.environ.get('FOLIOFORGE_SCREENSHOTS', tempfile.mkdtemp(prefix='folioforge-ui-shots-')))
shots.mkdir(parents=True, exist_ok=True)
server = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(server.stdout.readline())
    source = Path(ready['source'])
    original = source.read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{ready['port']}")
        print('Connected to test host', flush=True)
        ui = page.frame_locator('#app')
        frame = page.frames[1]
        wait_until(frame, '!!window.folioforgeWorkspace?.state.rendered')
        assert source.read_text() == original
        print('Initial preview rendered', flush=True)
        ui.frame_locator('#preview').locator('h1').first.wait_for()
        assert ui.frame_locator('#preview').locator('table').count() >= 1
        assert 'createHTML' not in ui.frame_locator('#preview').locator('body').inner_text()
        page.screenshot(path=str(shots / 'split-document.png'))
        rendered = frame.evaluate('folioforgeWorkspace.state.rendered')
        for format, html in rendered.items():
            (shots / ('index.html' if format == 'document' else 'slides.html')).write_text(html)
        print('Browser errors: ' + str(errors)[:1000], flush=True)
        ui.frame_locator('#preview').locator('svg.mermaid-js').first.wait_for(timeout=30000)
        ui.locator('[data-format="slides"]').click()
        ui.frame_locator('#preview').locator('.reveal.ready').wait_for(timeout=30000)
        assert 'createHTML' not in ui.frame_locator('#preview').locator('body').inner_text()
        preview = ui.locator('#preview').element_handle().content_frame()
        preview.evaluate('Reveal.slide(1)')
        wait_until(frame, 'folioforgeWorkspace.state.positions.slides.h === 1', 15)
        page.screenshot(path=str(shots / 'split-slides.png'))
        print('Document and slides verified', flush=True)
        ui.locator('[data-layout="render"]').click()
        assert not ui.locator('#source-pane').is_visible()
        ui.locator('[data-layout="source"]').click()
        assert not ui.locator('#preview-pane').is_visible()
        ui.locator('[data-layout="split"]').click()
        # Edit and preview without changing the selected file.
        frame.evaluate("folioforgeWorkspace.editor.dispatch({changes:{from:0,to:0,insert:'<!-- unsaved edit -->\\n'}})")
        print('Draft changed; waiting for preview', flush=True)
        for attempt in range(90):
            current = frame.evaluate('({revision:folioforgeWorkspace.state.revision, rendered:folioforgeWorkspace.state.renderedRevision, rendering:folioforgeWorkspace.state.rendering, notice:document.getElementById("notice-text").textContent})')
            if current['rendered'] == current['revision']:
                break
            if attempt % 10 == 0:
                print(current, flush=True)
            page.wait_for_timeout(1000)
        else:
            raise AssertionError(current)
        print('Unsaved draft rendered', flush=True)
        ui.frame_locator('#preview').locator('section.present h2').filter(has_text='Prove the process').wait_for()
        assert source.read_text() == original
        ui.locator('#save').click()
        wait_until(frame, '!folioforgeWorkspace.state.saving && folioforgeWorkspace.state.base.startsWith("<!-- unsaved edit -->")', 15)
        assert source.read_text().startswith('<!-- unsaved edit -->')
        print('Explicit save verified', flush=True)
        ui.locator('#auto').uncheck()
        frame.evaluate("folioforgeWorkspace.editor.dispatch({changes:{from:0,to:0,insert:'Local draft\\n'}})")
        source.write_text('# External agent edit\n')
        frame.evaluate('folioforgeWorkspace.reload()')
        assert ui.locator('#save').is_disabled()
        assert frame.evaluate('folioforgeWorkspace.editor.state.doc.toString().startsWith("Local draft")')
        assert source.read_text() == '# External agent edit\n'
        print('External edit conflict retained', flush=True)
        for width, height in [(390, 844), (768, 1024)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.screenshot(path=str(shots / f'workspace-{width}.png'))
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
            overlaps = frame.evaluate('''() => {
              const boxes = [...document.querySelectorAll('nav button, #theme, nav label[for=theme], .auto')].map(e => ({name:e.textContent || e.id, r:e.getBoundingClientRect()}));
              return boxes.flatMap((a,i) => boxes.slice(i+1).filter(b => Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left)>1 && Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top)>1).map(b => [a.name,b.name]));
            }''')
            assert not overlaps, overlaps
            for selector in ['#source-pane', '#preview-pane']:
                box = ui.locator(selector).bounding_box()
                assert box['width'] > 50 and box['height'] > 50, box
        # File handler uses host-managed resources and etags, not arbitrary paths.
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(f"http://127.0.0.1:{ready['port']}/?file")
        print('Testing host file handler', flush=True)
        frame = page.frames[1]
        wait_until(frame, '!!window.folioforgeWorkspace?.state.etag', 30)
        ui = page.frame_locator('#app')
        ui.locator('#auto').uncheck()
        assert frame.evaluate('folioforgeWorkspace.state.uri') == 'host://selected/pilot'
        frame.evaluate("folioforgeWorkspace.editor.dispatch({changes:{from:0,to:0,insert:'Host draft\\n'}})")
        frame.evaluate('folioforgeWorkspace.save()')
        assert source.read_text().startswith('Host draft\n')
        assert not errors, errors
        page.close(run_before_unload=False)
        browser.close()
    print(json.dumps({'passed': True, 'screenshots': str(shots)}))
finally:
    server.terminate()
    try:
        server.wait(timeout=15)
    except subprocess.TimeoutExpired:
        server.kill(); server.wait()
