"""Capture the real workspace on synthetic data, never the user's desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.2)
    raise AssertionError(frame.evaluate('document.getElementById("notice-text")?.textContent') or expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--theme', default='default')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, FOLIOFORGE_SHOWCASE_SOURCE=str(Path(__file__).with_name('product-review.md')),
               FOLIOFORGE_DEFAULT_THEME=args.theme)
    host = subprocess.Popen(['node', str(Path(__file__).with_name('browser-host.mjs'))], env=env,
                            stdout=subprocess.PIPE, text=True)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1600, 'height': 1000}, device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            ui = page.frame_locator('#app')
            frame = page.frames[1]
            wait(frame, '!!window.folioforgeWorkspace?.state.rendered')
            ui.frame_locator('#preview').locator('h1').first.wait_for()
            ui.locator('#auto').uncheck()

            def shot(name):
                page.wait_for_timeout(600)
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#app').screenshot(path=str(args.output / (name + '.png')))
                print('Captured ' + name, flush=True)

            shot('01-document-and-source')
            ui.locator('[data-format="slides"]').click()
            ui.frame_locator('#preview').locator('.reveal.ready').wait_for(timeout=120000)

            def heading(title):
                frame.evaluate('''title => {
                  const w = folioforgeWorkspace;
                  const from = w.editor.state.doc.toString().indexOf('## ' + title);
                  w.editor.focus(); w.editor.dispatch({selection:{anchor:from}});
                }''', title)
                preview = ui.locator('#preview').element_handle().content_frame()
                wait(preview, f'Reveal.getCurrentSlide()?.textContent.includes({json.dumps(title)})', 20)
                return preview

            heading('Start with a focused pilot')
            shot('02-evidence-and-takeaway')
            heading('Compare the rollout options')
            shot('03-options-comparison')
            preview = heading('Make the decision repeatable')
            preview.locator('svg.mermaid-js').wait_for(timeout=30000)
            assert 'Before the next review' not in preview.locator('body').inner_text()
            shot('04-diagram-and-source')
            ui.locator('[data-layout="render"]').click()
            shot('05-presentation-view')
            ui.locator('[data-layout="split"]').click()
            frame.evaluate('''() => {
              const w = folioforgeWorkspace;
              const from = w.editor.state.doc.toString().indexOf(':::: {.agent-comment');
              w.editor.focus(); w.editor.dispatch({selection:{anchor:from}});
            }''')
            ui.locator('.cm-content').focus()
            page.keyboard.press('Control+End')
            shot('06-agent-review-in-source')
            frame.evaluate('''() => {
              const w = folioforgeWorkspace, end = w.editor.state.doc.length;
              w.editor.dispatch({changes:{from:end,insert:'\\n\\n'},selection:{anchor:end+2}});
              w.editor.focus();
            }''')
            page.keyboard.type('/take')
            ui.locator('.cm-tooltip-autocomplete').wait_for()
            shot('07-insert-menu')
            assert not errors, errors
            (args.output / 'capture.json').write_text(json.dumps({
                'theme': args.theme, 'fixture': 'codex-plugin/tests/product-review.md',
                'host': 'isolated MCP host, actual plugin UI; not Codex desktop chrome',
                'screenshots': sorted(p.name for p in args.output.glob('*.png')),
                'synthetic': True, 'browser_errors': errors}, indent=2) + '\n')
            page.close(run_before_unload=False)
            browser.close()
    finally:
        host.terminate()
        try:
            host.wait(timeout=15)
        except subprocess.TimeoutExpired:
            host.kill(); host.wait()


if __name__ == '__main__':
    main()
