"""Synthetic concurrent editor/file changes through the real built MCP plugin."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError((expression, frame.locator('body').inner_text()[-1500:]))


with tempfile.TemporaryDirectory(prefix='matsugit-merge-test-') as tmp:
    fixture = Path(tmp) / 'merge.md'
    original = '# Review\n\nAlpha original\n\n## Detail\n\nBeta original\n\n## Close\n\nGamma original\n'
    fixture.write_text(original)
    host = subprocess.Popen(['node', str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(fixture), QUARTO='/missing-quarto-for-editor-only-test'))
    try:
        ready = json.loads(host.stdout.readline())
        source = Path(ready['source'])
        shots = Path(tempfile.mkdtemp(prefix='matsugit-merge-shots-'))
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.locator('#sync').uncheck()
            frame.locator('[data-layout="source"]').click()

            def current():
                return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')

            def edit(text):
                frame.evaluate('(text)=>matsugitWorkspace.editor.dispatch({changes:{from:0,to:matsugitWorkspace.editor.state.doc.length,insert:text},userEvent:"input.type"})', text)

            def reread():
                wait(frame, '!matsugitWorkspace.state.merging')
                frame.evaluate('matsugitWorkspace.reload()')
                wait(frame, '!matsugitWorkspace.state.merging')

            mine = original.replace('Alpha original','Alpha mine')
            incoming = original.replace('Gamma original','Gamma agent')
            edit(mine)
            source.write_text(incoming)
            reread()
            merged = mine.replace('Gamma original','Gamma agent')
            assert current() == merged, (current(), frame.locator('#notice-text').inner_text())
            assert source.read_text() == incoming
            assert not frame.evaluate('matsugitWorkspace.state.conflict')
            records = [json.loads(f.read_text()) for f in Path(ready['recovery']).glob('*.json')]
            assert any(r['text'] == mine for r in records)
            frame.locator('#undo').click()
            assert current() == incoming, 'Undo must not erase the incoming edit'
            frame.locator('#redo').click()
            assert current() == merged
            frame.locator('#save').click()
            wait(frame, '!matsugitWorkspace.state.saving')
            assert source.read_text() == merged
            print('PASS: non-overlapping auto merge, safety copy, rebased Undo/Redo, explicit Save', flush=True)

            local = merged.replace('Alpha mine', 'Alpha local choice').replace('Beta original', 'Beta local choice')
            remote = merged.replace('Alpha mine', 'Alpha agent choice').replace('Beta original', 'Beta agent choice')
            edit(local)
            source.write_text(remote)
            reread()
            assert current() == local
            assert frame.evaluate('matsugitWorkspace.state.conflict')
            frame.locator('#reload').click()
            frame.locator('#incoming-merge').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            assert frame.locator('#merge-apply').is_disabled()
            assert frame.locator('#merge-local').input_value() == 'Alpha local choice\n'
            frame.locator('#merge-mine').click()
            frame.locator('#merge-next').click()
            frame.locator('#merge-result').fill('Beta jointly edited\n')
            assert frame.locator('#merge-apply').is_enabled()
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                box = frame.locator('#merge-dialog').bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= width
                assert frame.evaluate('document.getElementById("merge-dialog").scrollWidth <= document.getElementById("merge-dialog").clientWidth')
                page.screenshot(path=str(shots/f'merge-{width}.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            newer = remote + '\nAnother external edit\n'
            source.write_text(newer)
            frame.locator('#merge-apply').click()
            wait(frame, '!matsugitWorkspace.state.merging && document.getElementById("merge-status").textContent.includes("changed again")')
            assert current() == local and source.read_text() == newer
            frame.locator('#merge-cancel').click()
            frame.locator('#reload').click()
            frame.locator('#incoming-merge').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            frame.locator('#merge-mine').click()
            frame.locator('#merge-next').click()
            frame.locator('#merge-both').click()

            def fail_backup(route):
                request = route.request.post_data_json
                if request.get('params',{}).get('name') == 'matsugit_recovery_checkpoint':
                    route.fulfill(json={'result':{'isError':True,'content':[{'type':'text','text':'Synthetic backup unavailable'}]}})
                else:
                    route.continue_()
            page.route('**/rpc', fail_backup)
            frame.locator('#merge-apply').click()
            wait(frame, '!matsugitWorkspace.state.merging && document.getElementById("merge-status").textContent.includes("backup unavailable")')
            assert current() == local and source.read_text() == newer
            page.unroute('**/rpc', fail_backup)
            frame.locator('#merge-apply').click()
            wait(frame, '!document.getElementById("merge-dialog").open')
            result = local.replace('Beta local choice\n','Beta local choice\nBeta agent choice\n') + '\nAnother external edit\n'
            assert current() == result
            assert source.read_text() == newer
            frame.locator('#undo').click()
            assert current() == newer
            frame.locator('#redo').click()
            assert current() == result
            frame.locator('#save').click()
            wait(frame, '!matsugitWorkspace.state.saving')
            assert source.read_text() == result
            # A model-context edit may arrive while a review backup is in flight.
            edit(result.replace('Gamma agent','Gamma local again'))
            source.write_text(result.replace('Gamma agent','Gamma agent again'))
            reread()
            frame.locator('#reload').click()
            frame.locator('#incoming-merge').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            frame.locator('#merge-mine').click()
            held = []
            def delay_backup(route):
                request = route.request.post_data_json
                if not held and request.get('params',{}).get('name') == 'matsugit_recovery_checkpoint':
                    held.append((route,route.fetch()))
                else:
                    route.continue_()
            page.route('**/rpc', delay_backup)
            frame.locator('#merge-apply').click()
            deadline = time.monotonic() + 10
            while not held and time.monotonic() < deadline:
                page.wait_for_timeout(50)
            assert held
            changed_again = current() + '\nTyped during backup\n'
            edit(changed_again)
            held[0][0].fulfill(response=held[0][1])
            page.unroute('**/rpc', delay_backup)
            wait(frame, '!matsugitWorkspace.state.merging && document.getElementById("merge-status").textContent.includes("draft changed")')
            assert current() == changed_again
            assert source.read_text() == result.replace('Gamma agent','Gamma agent again')
            frame.locator('#merge-cancel').click()
            assert not errors, errors
            print(f'PASS: per-conflict choices, editable result, stale disk refusal, failed backup refusal, mobile review, explicit Save; screenshots {shots}', flush=True)
            browser.close()
    finally:
        host.terminate()
        try:
            host.wait(timeout=15)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
