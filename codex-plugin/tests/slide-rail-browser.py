"""Exercise explicit storyline navigation in the real bundled workspace."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=180):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if frame.evaluate(expression):
            return
        time.sleep(.15)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1800:])


with tempfile.TemporaryDirectory(prefix='matsugit-rail-') as temporary:
    source = Path(temporary) / 'story.md'
    original = ('---\ntitle: Storyline test\nslide-layout: structured\n'
                'slide-section-dividers: false\n---\n\n# A bounded decision\n\n'
                + '\n'.join(f'## Decision {number:02d}\n### Claim {number:02d}\n\n'
                            f'Evidence for decision {number:02d} stays editable.\n'
                            for number in range(1, 25)))
    source.write_text(original)
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                            env=dict(os.environ, MATSUGIT_TEST_SOURCE=str(source),
                                     MATSUGIT_TEST_OPEN_OPTIONS='{"layout":"split","format":"slides","editor":"visual"}'),
                            stdout=subprocess.PIPE, text=True)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('https://**', lambda route: route.abort())
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace?.state.rendered?.slides && !matsugitWorkspace.state.rendering')
            preview = frame.locator('#preview').element_handle().content_frame()
            wait(preview, 'window.Reveal?.isReady()')
            assert frame.locator('#slide-rail .rail-slide').count() == 24
            assert frame.evaluate('matsugitWorkspace.state.autosave') is False
            frame.locator('#sync').uncheck()
            frame.locator('[data-layout="render"]').click()

            # Explicit navigation works in Preview, independently of Follow.
            frame.locator('.rail-slide[data-index="23"]').click()
            wait(preview, 'Reveal.getCurrentSlide()?.textContent.includes("Decision 24")')
            assert frame.evaluate('matsugitWorkspace.state.layout') == 'render'
            assert not frame.locator('#sync').is_checked()
            selected = frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            assert selected == original.index('## Decision 24')
            assert frame.locator('.rail-slide[aria-current="true"]').get_attribute('data-index') == '23'

            # Manual preview navigation highlights the strip, but leaves an
            # independent editor selection alone when Follow is disabled.
            preview.locator('.navigate-left').click()
            wait(preview, 'Reveal.getCurrentSlide()?.textContent.includes("Decision 23")')
            wait(frame, 'document.querySelector(".rail-slide[aria-current=true]")?.dataset.index === "22"')
            assert frame.evaluate('matsugitWorkspace.editor.state.selection.main.head') == selected

            # Double-clicking real rendered words opens the editor at those
            # words, not at a matching phrase on a different slide.
            preview.locator('section.present p').filter(has_text='Evidence for decision 23').dblclick()
            wait(frame, 'matsugitWorkspace.state.layout === "split"')
            at = frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            assert original[at:].startswith('Evidence for decision 23'), original[at:at + 100]
            assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'visual'

            # Draft titles and checks stay current without saving or requiring
            # a successful render. Check owns the delayed strip repaint.
            frame.locator('#auto').uncheck()
            frame.evaluate('''() => {
              const e = matsugitWorkspace.editor, old = 'Decision 24';
              const from = e.state.doc.toString().indexOf('## ' + old) + 3;
              e.dispatch({changes: {from, to: from + old.length, insert: 'An intentionally long final decision title for a compact storyline'}});
              e.dispatch({changes: {from: e.state.doc.length, insert: '\\n:::: columns\\n#### Only one part\\nEvidence.\\n::::\\n'}});
            }''')
            wait(frame, 'document.querySelector(".rail-slide[data-index=\\"23\\"]")?.dataset.mark === "problem"')
            last = frame.locator('.rail-slide[data-index="23"]')
            assert 'An intentionally long final decision' in last.inner_text()
            for width, height in [(390, 844), (768, 1024)]:
                page.set_viewport_size({'width': width, 'height': height})
                last.scroll_into_view_if_needed()
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert frame.locator('#slide-rail').is_visible()
            frame.locator('[data-layout="story"]').click()
            assert frame.locator('#slide-rail').is_hidden()
            assert source.read_text() == original
            assert not errors, errors
            browser.close()
        print('PASS: long storyline, Follow-off navigation, preview highlight, double-click edit, draft/check updates, narrow layout; no source save', flush=True)
    finally:
        host.terminate()
        try:
            host.wait(timeout=20)
        except subprocess.TimeoutExpired:
            host.kill(); host.wait()
