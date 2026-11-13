"""Scoped agent tools cooperate with unsaved typing in the shared workspace."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TEXT = 'matsugitWorkspace.editor.state.doc.toString()'


def wait(frame, expression, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-2000:])


with tempfile.TemporaryDirectory(prefix='matsugit-agent-browser-') as tmp:
    fixture = Path(tmp) / 'deck.md'
    original = '# Decision\n\n## Evidence\n### A measurable change\n\nOriginal evidence.\n\n## Delivery\n### Start small\n\nOriginal delivery.\n'
    fixture.write_text(original)
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE, text=True, env=dict(os.environ, MATSUGIT_STANDARD_MCP='1',
        MATSUGIT_SHOWCASE_SOURCE=str(fixture), QUARTO='/missing-quarto-for-editor-test',
        MATSUGIT_TEST_OPEN_OPTIONS='{"autosave":false,"editor":"raw","layout":"source"}'))
    try:
        ready = json.loads(host.stdout.readline())
        source = Path(ready['source'])
        address = f'http://127.0.0.1:{ready["port"]}'

        def tool(name, **args):
            request = urllib.request.Request(address + '/rpc', method='POST', data=json.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}
            }).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)['result']
            assert not data.get('isError'), data
            return data['structuredContent']

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1200, 'height': 850})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(address)
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()

            def type_passage(old, new):
                frame.evaluate('''old => { const e=matsugitWorkspace.editor;
                  const from=e.state.doc.toString().indexOf(old);
                  e.dispatch({selection:{anchor:from,head:from+old.length}});e.focus(); }''', old)
                page.keyboard.type(new)

            # A real tool edit on slide 2 combines with unsaved typing on slide 1.
            first = tool('matsugit_read_slide', path=str(source), slide=2)
            type_passage('Original evidence.', 'My evidence.')
            assert source.read_text() == original
            result = tool('matsugit_edit_slide', edit_id=first['edit_id'],
                          edits=[{'old': 'Original delivery.', 'new': 'Agent delivery.'}])
            assert result['outcome'] == 'saved'
            frame.evaluate('matsugitWorkspace.reload()')
            wait(frame, TEXT + '.includes("Agent delivery.") && !matsugitWorkspace.state.merging')
            assert 'My evidence.' in frame.evaluate(TEXT)
            assert 'My evidence.' not in source.read_text()
            assert not frame.evaluate('matsugitWorkspace.state.conflict')
            frame.locator('#save').click()
            wait(frame, '!matsugitWorkspace.state.saving && document.getElementById("save-state").textContent === "Saved to file"')
            assert 'My evidence.' in source.read_text() and 'Agent delivery.' in source.read_text()

            # A new saved version invalidates a previously read agent snapshot.
            stale = tool('matsugit_read_slide', path=str(source), slide=1)
            type_passage('My evidence.', 'Saved human revision.')
            frame.locator('#save').click()
            wait(frame, '!matsugitWorkspace.state.saving && document.getElementById("save-state").textContent === "Saved to file"')
            assert tool('matsugit_edit_slide', edit_id=stale['edit_id'],
                        edits=[{'old': 'My evidence.', 'new': 'Stale replacement.'}])['outcome'] == 'conflict'
            assert 'Saved human revision.' in source.read_text()

            # Overlap with a draft is still a choice, never a silent replacement.
            snapshot = tool('matsugit_read_slide', path=str(source), slide=1)
            type_passage('Saved human revision.', 'My unsaved choice.')
            assert tool('matsugit_edit_slide', edit_id=snapshot['edit_id'],
                        edits=[{'old': 'Saved human revision.', 'new': 'Agent alternative.'}])['outcome'] == 'saved'
            frame.evaluate('matsugitWorkspace.reload()')
            wait(frame, 'matsugitWorkspace.state.conflict && !matsugitWorkspace.state.merging')
            assert 'My unsaved choice.' in frame.evaluate(TEXT)
            assert 'Agent alternative.' in source.read_text()
            frame.locator('#save').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            assert frame.locator('#merge-apply').is_disabled()
            assert 'My unsaved choice.' in frame.locator('#merge-local').input_value()
            assert 'Agent alternative.' in frame.locator('#merge-incoming').input_value()
            frame.locator('#merge-mine').click()
            frame.locator('#merge-apply').click()
            wait(frame, '!document.getElementById("merge-dialog").open && !matsugitWorkspace.state.saving')
            assert 'My unsaved choice.' in source.read_text()
            assert 'Agent delivery.' in source.read_text()
            assert not errors, errors
            browser.close()
            print('PASS: scoped tool edit merges with draft; stale edit rejected; same-line conflict reviewed')
    finally:
        host.terminate()
        host.wait(timeout=20)
