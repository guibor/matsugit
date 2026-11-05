"""Check source hierarchy, role help and non-destructive slide guides."""
import json
import os
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
    env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(ROOT / 'codex-plugin/tests/visual.md')),
    stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        frame.wait_for_function('()=>!!window.matsugitWorkspace?.state.rendered', timeout=180000)
        frame.locator('#auto').uncheck()
        frame.locator('#sync').uncheck()
        frame.locator('[data-editor="visual"]').click()
        frame.locator('[data-layout="source"]').click()
        original = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        for level, size in [(1,18), (2,17), (3,14)]:
            heading = frame.locator(f'.ff-heading-{level}').first
            assert heading.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)') == size
            assert heading.evaluate('(e)=>[...e.children].every(c=>getComputedStyle(c).fontSize===getComputedStyle(e).fontSize)')
        frame.locator('#slide-separators').check()
        assert frame.locator('.ff-slide-boundary').count() >= 2
        marker = frame.locator('.ff-gutter-marker[title="Slide"]').first
        popup = frame.locator('#role-help')
        marker.hover()
        assert popup.is_visible() and 'Slide title / H2' in popup.inner_text()
        marker.click()
        frame.locator('#slide-separators').hover()
        assert popup.is_visible()
        marker.press('Escape')
        assert not popup.is_visible()
        marker.focus()
        # Refocus from outside the marker to exercise the focus handler.
        frame.locator('#slide-separators').focus()
        marker.focus()
        assert popup.is_visible()
        marker.press('Enter')
        assert popup.is_visible()
        for width in (390, 768, 1440):
            page.set_viewport_size({'width':width, 'height':1000})
            marker.click()
            assert popup.is_visible()
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
            bounds = popup.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            marker.press('Escape')
        directory = os.environ.get('MATSUGIT_SCREENSHOTS')
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(directory)/'editor-after.png'))
            marker.click()
            page.screenshot(path=str(Path(directory)/'editor-help.png'))
            marker.press('Escape')
        for mode in ('raw', 'visual'):
            frame.locator(f'[data-editor="{mode}"]').click()
            assert frame.locator('.ff-slide-boundary').count() >= 2
            frame.locator('#slide-separators').uncheck()
            assert frame.locator('.ff-slide-boundary').count() == 0
            frame.locator('#slide-separators').check()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        assert Path(ready['source']).read_text() == original
        assert not errors, errors
        print('PASS: compact hierarchy, hover/click/keyboard help, optional guides, source unchanged, 390/768/1440 widths')
        browser.close()
finally:
    host.terminate()
    try:
        host.wait(timeout=15)
    except subprocess.TimeoutExpired:
        host.kill()
        host.wait()
