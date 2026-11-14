"""Story previews show complete draft slides without navigating or saving."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TEXT = 'matsugitWorkspace.editor.state.doc.toString()'

def wait(frame, expression, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError((expression, frame.locator('body').inner_text()[-1000:]))

with tempfile.TemporaryDirectory(prefix='matsugit-peek-') as folder:
    root = Path(folder)
    source = root / 'deck.md'
    original = ('---\ntitle: Synthetic story\nslide-layout: structured\n---\n\n'
                '# Strategy\n\n## First slide\n\n### First claim\n\nVisible evidence.\n\n'
                '<!-- matsugit:export-end -->\n\n## Working slide\n\n### Still visible here\n\nWORKING_BODY\n')
    source.write_text(original)
    config = root / 'config.json'; config.write_text('{"theme":"default"}')
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, MATSUGIT_TEST_SOURCE=str(source), MATSUGIT_TEST_CONFIG=str(config),
                 MATSUGIT_TEST_OPEN_OPTIONS='{"layout":"story","format":"slides","autosave":false,"editor":"visual"}'))
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1280,'height':900})
            errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{ready["port"]}'); frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.evaluate('document.getElementById("auto").checked=false')
            frame.evaluate('''() => { const e=matsugitWorkspace.editor;
                e.dispatch({changes:{from:e.state.doc.length,insert:'\\nUnsaved working evidence.\\n'}}); }''')
            draft = frame.evaluate(TEXT)
            for mode, width in [('overview',1280),('walkthrough',390),('overview',320)]:
                page.set_viewport_size({'width':width,'height':900})
                frame.locator(f'button[data-story-mode="{mode}"]').click()
                button = frame.locator('button[aria-label="Preview slide"]').last
                button.scroll_into_view_if_needed()
                selection = frame.evaluate('matsugitWorkspace.editor.state.selection.toJSON()')
                scroll = frame.locator('#story-list').evaluate('(e)=>e.scrollTop')
                button.click()
                wait(frame,'!!document.querySelector("#slide-peek iframe")?.getAttribute("src")')
                slide = frame.locator('#slide-peek iframe').element_handle().content_frame()
                wait(slide,'window.Reveal?.getCurrentSlide?.()?.textContent.includes("WORKING_BODY")',20)
                assert not slide.evaluate('Reveal.isScrollView()')
                assert 'Unsaved working evidence.' in slide.locator('section.present').inner_text()
                bounds = frame.locator('#slide-peek').bounding_box()
                assert bounds['width'] <= width and bounds['x'] >= 0, bounds
                page.screenshot(path=f'/tmp/matsugit-story-peek-{os.environ.get("MATSUGIT_TEST_HOST","standard")}-{width}.png')
                # Escape from inside the rendered slide returns to Story.
                slide.locator('body').click(position={'x':5,'y':5})
                page.keyboard.press('Escape')
                wait(frame,'!document.getElementById("slide-peek").open')
                assert frame.evaluate(TEXT) == draft
                assert frame.evaluate('matsugitWorkspace.editor.state.selection.toJSON()') == selection
                assert abs(frame.locator('#story-list').evaluate('(e)=>e.scrollTop') - scroll) < 2
                assert frame.evaluate('document.activeElement?.getAttribute("aria-label")') == 'Preview slide'
            assert source.read_text() == original
            assert not errors, errors
            browser.close()
            print('PASS: full working slide, unsaved draft, Overview/Walkthrough, Escape, focus/selection/scroll, responsive view')
    finally:
        host.terminate(); host.wait(timeout=20)
