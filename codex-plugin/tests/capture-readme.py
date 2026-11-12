"""Record the public README demo using the real UI and a synthetic source.

Requires Playwright, Chromium and Pillow. No private theme, account or document.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
shrink = __import__('shrink-images').shrink
SOURCE = ROOT / 'examples/automotive-story.md'
OUTPUT = ROOT / 'docs/images/workspace'


def wait(frame, expression, timeout=180):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if frame.evaluate(expression):
            return
        time.sleep(.15)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1800:])


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    frames, durations, steps, errors = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='matsugit-readme-') as home:
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + '/config',
                   XDG_CACHE_HOME=home + '/cache', MATSUGIT_DEFAULT_THEME='default',
                   MATSUGIT_THEMES_DIR=str(ROOT / 'matsugit/themes'),
                   MATSUGIT_SHOWCASE_SOURCE=str(SOURCE),
                   MATSUGIT_TEST_OPEN_OPTIONS='{"layout":"split","format":"slides","editor":"visual"}')
        host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                                env=env, stdout=subprocess.PIPE, text=True)
        try:
            ready = json.loads(host.stdout.readline())
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.route('https://**', lambda route: route.abort())
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{ready["port"]}')
                frame = page.frames[1]
                wait(frame, '!!window.matsugitWorkspace?.state.rendered?.slides && !matsugitWorkspace.state.rendering')
                assert frame.evaluate('matsugitWorkspace.state.autosave') is False
                frame.locator('#auto').uncheck()
                preview = frame.locator('#preview').element_handle().content_frame()
                wait(preview, 'window.Reveal?.isReady()')

                def select_slide(title):
                    frame.evaluate('''title => {const e=matsugitWorkspace.editor;
                      const from=e.state.doc.toString().indexOf('## '+title);
                      if(from < 0) throw Error('Missing demo slide');
                      e.dispatch({selection:{anchor:from},scrollIntoView:true});
                      e.scrollDOM.scrollTop=e.lineBlockAt(from).top; e.contentDOM.blur();}''', title)

                def shot(label, duration=1700, name=None):
                    page.wait_for_timeout(400)
                    assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    data = page.screenshot()
                    frames.append(Image.open(io.BytesIO(data)).convert('RGB'))
                    durations.append(duration); steps.append(label)
                    if name:
                        (OUTPUT / name).write_bytes(data)
                        shrink(OUTPUT / name)
                    print(label, flush=True)

                select_slide('Sell the journey')
                wait(preview, 'Reveal.getCurrentSlide()?.textContent.includes("Sell the journey")')
                shot('Visual Markdown alongside the slide', 2800, 'visual-and-slides.png')
                frame.locator('[data-layout="story"]').click()
                frame.locator('#story-preview').check()
                shot('Story Overview: title, claim and takeaway', 2300, 'story-overview.png')
                frame.locator('.story-slide .story-heading .story-title').first.click()
                field = frame.get_by_role('textbox', name='Edit slide title', exact=True)
                field.fill('')
                for part in ('Build ', 'a better ', 'Tuesday'):
                    field.press_sequentially(part, delay=40)
                    shot('Edit title: ' + field.input_value(), 250)
                field.press('Enter')
                assert '## Build a better Tuesday' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
                shot('The title changed in the source draft', 1300)
                frame.locator('[data-story-mode="walkthrough"]').click()
                frame.locator('[data-story-size="compact"]').click()
                frame.locator('#story-preview').uncheck()
                shot('Compact Walkthrough with section separators', 2400, 'story-walkthrough.png')
                frame.locator('[data-layout="split"]').click()
                frame.locator('#auto').check()
                wait(frame, '!matsugitWorkspace.state.rendering && matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision')
                preview = frame.locator('#preview').element_handle().content_frame()
                wait(preview, 'document.body?.textContent.includes("Build a better Tuesday")')
                select_slide('Build a better Tuesday')
                wait(preview, 'Reveal.getCurrentSlide()?.textContent.includes("Build a better Tuesday")')
                shot('The edited title in the rendered slide', 2000)
                frame.locator('#present').click()
                wait(frame, 'document.body.classList.contains("presenting")')
                shot('Present', 2400)
                preview.locator('body').press('Escape')
                wait(frame, '!document.body.classList.contains("presenting")')
                shot('Return to Visual Markdown', 1600)
                assert Path(ready['source']).read_bytes() == SOURCE.read_bytes()
                for width, height in [(390, 844), (768, 1024)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    page.wait_for_timeout(300)
                    assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, errors
                browser.close()
        finally:
            host.terminate()
            try:
                host.wait(timeout=20)
            except subprocess.TimeoutExpired:
                host.kill(); host.wait()
    gif = OUTPUT / 'visual-story-demo.gif'
    frames = [frame.quantize(colors=256, dither=0) for frame in frames]
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, optimize=True, disposal=2)
    with Image.open(gif) as image:
        assert image.n_frames == len(frames) and image.size == (1440, 900)
    metadata = dict(plugin_version=json.loads((ROOT / 'codex-plugin/package.json').read_text())['version'],
                    theme='default', fixture=str(SOURCE.relative_to(ROOT)), synthetic=True,
                    fixture_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    app_sha256=hashlib.sha256(subprocess.run(['node', str(ROOT / 'codex-plugin/app-html.mjs')], check=True, capture_output=True).stdout).hexdigest(),
                    host='isolated MCP host; real shared plugin UI, not Codex/Cursor desktop chrome',
                    steps=steps, duration_ms=sum(durations), source_unchanged=True,
                    rendering_waits_omitted=True, browser_errors=errors)
    (OUTPUT / 'capture.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Created {gif.name}: {gif.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    main()
