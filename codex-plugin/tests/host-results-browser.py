"""Open a real file when the host forwards ordinary MCP results without _meta."""
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
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1000:])


with tempfile.TemporaryDirectory(prefix='matsugit-host-results-') as temporary:
    fixture = Path(temporary) / 'car.md'
    fixture.write_text('---\ntitle: The next car\nslide-layout: structured\n---\n\n'
                       '# The journey\n\n## Fewer chores\n### A better everyday trip\n\n'
                       '| Need | Response |\n| --- | --- |\n| Charging | Plan ahead |\n')
    for mode in os.environ.get('MATSUGIT_RESULT_MODES', 'summary text-only full').split():
        env = dict(os.environ, HOME=temporary, XDG_CONFIG_HOME=temporary + '/config',
                   MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_RESULT=mode,
                   MATSUGIT_TEST_OPEN_OPTIONS='{"layout":"split","format":"slides","editor":"visual"}',
                   MATSUGIT_SHOWCASE_SOURCE=str(fixture))
        host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                                env=env, text=True, stdout=subprocess.PIPE)
        try:
            ready = json.loads(host.stdout.readline())
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
                page = browser.new_page(viewport={'width': 1000, 'height': 600}, color_scheme='dark')
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{ready["port"]}')
                frame = page.frames[1]
                wait(frame, '!!window.matsugitWorkspace?.state.session', timeout=15)
                wait(frame, '!!matsugitWorkspace.state.rendered?.slides && !matsugitWorkspace.state.rendering')
                assert frame.evaluate('matsugitWorkspace.state.layout') == 'split'
                assert frame.evaluate('matsugitWorkspace.state.format') == 'slides'
                assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'visual'
                assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == fixture.read_text()
                assert frame.evaluate('matsugitWorkspace.state.writable')
                assert frame.locator('#save-state').inner_text() == 'Saved to file'
                for width, height in ((1000, 600), (740, 600), (390, 844), (1440, 900)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.wait_for_timeout(200)
                    assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    identity = frame.locator('.identity').bounding_box()
                    actions = frame.locator('.actions').bounding_box()
                    assert (identity['x'] + identity['width'] <= actions['x'] + 1
                            or identity['y'] + identity['height'] <= actions['y'] + 1), (width, identity, actions)
                assert frame.locator('.ff-visual-table').count() == 1
                frame.locator('#auto').uncheck()
                frame.evaluate('''()=>{const w=matsugitWorkspace;
                  w.editor.dispatch({changes:{from:w.editor.state.doc.length,insert:'\\nLocal draft\\n'}});}''')
                draft = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
                # Duplicate host delivery cannot erase an unsaved draft.
                page.evaluate('''async()=>{const result=await(await fetch('/result')).json();
                  document.querySelector('#app').contentWindow.postMessage({jsonrpc:'2.0',
                    method:'ui/notifications/tool-result',params:result},'*');}''')
                page.wait_for_timeout(600)
                assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == draft
                assert Path(ready['source']).read_text() == fixture.read_text()
                assert not errors, errors
                browser.close()
            print('PASS:', mode, 'open, slides, Visual, narrow toolbar, draft preserved', flush=True)
        finally:
            host.terminate()
            try:
                host.wait(timeout=15)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
