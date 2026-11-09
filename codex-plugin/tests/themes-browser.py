"""Installed theme discovery and selection through the real MCP/Chromium host."""
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


with tempfile.TemporaryDirectory(prefix='matsugit-theme-catalog-') as temporary:
    root = Path(temporary)
    def theme(name):
        directory = root / name
        directory.mkdir()
        (directory / 'theme.json').write_text('{"extends":"default"}')
    theme('alpha')
    theme('beta')
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, MATSUGIT_THEMES_DIR=temporary, MATSUGIT_DEFAULT_THEME='alpha'))
    try:
        ready = json.loads(host.stdout.readline())
        source = Path(ready['source'])
        original = source.read_bytes()
        shots = Path(tempfile.mkdtemp(prefix='matsugit-theme-picker-shots-'))
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440, 'height':1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, 'document.querySelectorAll("#theme option").length === 4')
            assert frame.locator('#theme option').all_text_contents() == ['alpha (default)', 'alpha', 'beta', 'default']
            assert frame.locator('#theme').input_value() == ''
            wait(frame, '!!matsugitWorkspace.state.rendered && !matsugitWorkspace.state.rendering')
            frame.locator('#auto').uncheck()
            frame.locator('#theme').select_option('beta')
            frame.locator('#refresh').click()
            wait(frame, 'matsugitWorkspace.state.resolvedTheme === "beta" && !matsugitWorkspace.state.rendering')
            assert frame.locator('#theme').input_value() == 'beta'
            assert frame.locator('#theme option').first.inner_text() == 'alpha (default)'
            theme('gamma')
            frame.locator('#refresh').click()
            wait(frame, 'document.querySelectorAll("#theme option").length === 5 && !matsugitWorkspace.state.refreshing && !matsugitWorkspace.state.rendering')
            assert frame.locator('#theme').input_value() == 'beta'
            frame.locator('#theme').select_option('')
            frame.locator('#refresh').click()
            wait(frame, 'matsugitWorkspace.state.resolvedTheme === "alpha" && !matsugitWorkspace.state.rendering')
            for width in (320, 390, 480, 560, 700, 900, 1440):
                page.set_viewport_size({'width':width, 'height':1000})
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                toolbar = frame.evaluate('''() => {
                  const controls = [...document.querySelectorAll('header button')]
                    .filter(button => button.getClientRects().length)
                    .map(button => ({id:button.id, ...button.getBoundingClientRect().toJSON()}));
                  const overlaps = [];
                  for (let left = 0; left < controls.length; left++)
                    for (let right = left + 1; right < controls.length; right++) {
                      const a = controls[left], b = controls[right];
                      if (Math.min(a.right,b.right) - Math.max(a.left,b.left) > .5 &&
                          Math.min(a.bottom,b.bottom) - Math.max(a.top,b.top) > .5)
                        overlaps.push([a.id,b.id]);
                    }
                  return {controls, overlaps};
                }''')
                assert not toolbar['overlaps'], (width, toolbar['overlaps'])
                assert all(control['left'] >= 0 and control['right'] <= width for control in toolbar['controls']), (width, toolbar)
                theme_box = frame.locator('#theme').bounding_box()
                refresh_box = frame.locator('#refresh').bounding_box()
                assert theme_box['x'] >= 0 and theme_box['x'] + theme_box['width'] <= width
                assert theme_box['x'] + theme_box['width'] <= refresh_box['x']
                if width in (320, 390, 700, 1440):
                    page.screenshot(path=str(shots / f'themes-{width}.png'))
            assert source.read_bytes() == original
            assert not errors, errors
            browser.close()
            print(f'PASS: installed dropdown, explicit theme, configured default, rescan, unchanged source, non-overlapping responsive toolbars; screenshots {shots}', flush=True)
    finally:
        host.terminate()
        try:
            host.wait(timeout=15)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
