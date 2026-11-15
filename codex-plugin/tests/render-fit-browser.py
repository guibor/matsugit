"""Rendered fit warnings, manual boundaries, safe patches and one source file."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright, Error

ROOT = Path(__file__).resolve().parents[2]
SETTLED = '!matsugitWorkspace.state.rendering && matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision'
TEXT = 'matsugitWorkspace.editor.state.doc.toString()'


def wait(frame, expression, timeout=120):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            if frame.evaluate(expression):
                return
        except Error as error:
            if 'Execution context was destroyed' not in str(error):
                raise
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1800:])


with tempfile.TemporaryDirectory(prefix='matsugit-fit-test-') as tmp:
    source = Path(tmp) / 'deck.md'
    original = ('---\ntitle: Fit test\nslide-layout: structured\nslide-title-page: false\n'
                'slide-section-dividers: false\n---\n\n## Small {#small}\n### A plain claim\n\nShort body.\n'
                '\n::: notes\n' + 'Private notes are not visible slide content. ' * 150 + '\n:::\n')
    source.write_text(original)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE,text=True,env=dict(os.environ,MATSUGIT_STANDARD_MCP='1',
        MATSUGIT_TEST_SOURCE=str(source),
        MATSUGIT_TEST_OPEN_OPTIONS='{"autosave":false,"layout":"split","format":"slides","editor":"raw"}'))
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440,'height':950})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace?.state.rendered?.slides && '+SETTLED)
            preview = frame.child_frames[0]
            wait(preview, '!!window.Reveal?.isReady() && !!window.matsugitFit')
            measure = 'matsugitFit.measure(Reveal.getCurrentSlide())'
            assert not preview.evaluate(measure)['overflow']
            font = preview.locator('.ff-body').evaluate('e=>getComputedStyle(e).fontSize')
            assert source.read_text() == original
            print('PASS: first slide and private notes fit',flush=True)

            def edit(text):
                frame.evaluate('''value=>{const e=matsugitWorkspace.editor;
                    e.dispatch({changes:{from:0,to:e.state.doc.length,insert:value}});}''',text)
                wait(frame, SETTLED)
                target = frame.locator('#preview').get_attribute('src').split('#')[0]
                wait(frame.child_frames[0], 'location.href.split("#")[0] === ' + json.dumps(target)
                     + ' && document.readyState === "complete" && !!window.Reveal?.isReady()')

            renamed = original.replace('## Small', '## Renamed').replace('A plain claim','An updated claim')
            preview.evaluate('window.fitPatchSentinel=42')
            edit(renamed)
            assert frame.evaluate('matsugitWorkspace.state.lastRefresh.kind') == 'patch'
            assert preview.evaluate('window.fitPatchSentinel') == 42
            assert preview.locator('#small h2').inner_text() == 'Renamed'
            assert 'Renamed' in preview.locator('.slide-menu-item-title').all_text_contents()
            assert preview.locator('.ff-claim').inner_text() == 'An updated claim'
            print('PASS: in-place title and claim, menu label',flush=True)

            bullets = ''.join(f'- Evidence item {i}: keep this authored text.\n' for i in range(24))
            crowded = renamed.replace('Short body.', bullets)
            edit(crowded)
            frame.locator('#check-status').click()
            wait(frame, '!!document.querySelector(".check-item[data-code=rendered-fit]")')
            finding = frame.locator('.check-item[data-code="rendered-fit"]')
            assert "Content doesn't fit" in finding.inner_text()
            finding.get_by_role('button',name='Show',exact=True).click()
            assert frame.evaluate('matsugitWorkspace.editor.state.doc.lineAt(matsugitWorkspace.editor.state.selection.main.head).text') == '## Renamed {#small}'
            assert frame.evaluate(TEXT) == crowded
            assert source.read_text() == original
            preview = frame.child_frames[0]
            assert preview.locator('.ff-body').evaluate('e=>getComputedStyle(e).fontSize') == font
            assert preview.locator('.ff-body li').count() == 24
            shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', '/tmp/matsugit-focused-shots'))
            shots.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(shots/'overflow.png'))
            assert preview.locator('.ff-body li').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)') >= 20
            print('PASS: unresolved crowding warns, source retained and type bounded',flush=True)

            # The author supplies boundaries; the renderer only respects them.
            split = crowded.replace('- Evidence item 8:', '\n---\n\n- Evidence item 8:').replace('- Evidence item 16:', '\n---\n\n- Evidence item 16:')
            edit(split)
            preview = frame.child_frames[0]
            wait(preview, '!!window.Reveal?.isReady() && !!window.matsugitFit')
            assert preview.evaluate('Reveal.getSlides().length') == 3
            for i in range(3):
                preview.evaluate('i=>Reveal.slide(i)',i)
                page.wait_for_timeout(500)
                measured = preview.evaluate(measure)
                assert not measured['overflow'] and not measured['overlap'], measured
            wait(frame, '!document.querySelector(".check-item[data-code=rendered-fit]")')
            assert frame.evaluate(TEXT) == split
            assert source.read_text() == original

            # A narrow host scales the same slide canvas; it does not shrink its type.
            frame.locator('#check-close').click()
            frame.locator('[data-layout="render"]').click()
            for width in (390, 760):
                page.set_viewport_size({'width':width,'height':850})
                wait(preview, '!!'+measure)
                assert not preview.evaluate(measure)['overflow']
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(shots/f'fit-{width}.png'))
            frame.locator('[data-format="document"]').click()
            wait(frame, SETTLED)
            reading = frame.child_frames[0]
            target = frame.locator('#preview').get_attribute('src').split('#')[0]
            wait(reading, 'location.href.split("#")[0] === ' + json.dumps(target)
                 + ' && document.readyState === "complete" && !!document.querySelector(".ff-fold-toggle")')
            assert reading.locator('main .ff-document-claim').inner_text() == 'An updated claim'
            assert 'Private notes' not in reading.locator('main').inner_text()
            assert reading.locator('main li').count() == 24
            toggle = reading.locator('.ff-fold-toggle').first
            assert toggle.get_attribute('aria-expanded') == 'true'
            toggle.click()
            assert toggle.get_attribute('aria-expanded') == 'false'
            assert reading.locator('main .ff-document-claim').is_hidden()
            page.emulate_media(media='print')
            assert reading.locator('main .ff-document-claim').is_visible()
            assert toggle.is_hidden()
            page.emulate_media(media='screen')
            toggle.focus()
            page.keyboard.press('Enter')
            assert reading.locator('main .ff-document-claim').is_visible()
            assert not frame.locator('.check-item[data-code=rendered-fit]').count()
            page.screenshot(path=str(shots/'document-disclosures.png'))
            assert source.read_text() == original
            assert not errors, errors
            print('PASS: fit warning, Show, unchanged source, bounded type, manual splits, title/claim patch, reading projection, narrow hosts',flush=True)
            page.close(run_before_unload=False)
            browser.close()
    finally:
        host.terminate()
        host.wait(timeout=20)
