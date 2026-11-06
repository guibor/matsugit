"""Save/review UX with real version checks and disposable files only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError((expression, frame.locator('body').inner_text()[-2500:]))


with tempfile.TemporaryDirectory(prefix='matsugit-save-ux-') as tmp:
    fixture = Path(tmp) / 'review.md'
    original = '# Plan\n\n## Decision\n\nFirst evidence\n\n## Delivery\n\nLast evidence\n'
    if os.environ.get('MATSUGIT_SAVE_UX_SOURCE'):
        original = Path(os.environ['MATSUGIT_SAVE_UX_SOURCE']).read_text() + '\n\n' + original
    fixture.write_text(original)
    host = subprocess.Popen(['node', str(ROOT/'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(fixture), QUARTO='/missing-quarto-for-editor-test'))
    try:
        ready = json.loads(host.stdout.readline()); source = Path(ready['source'])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440, 'height':1000})
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.locator('[data-layout="story"]' if os.environ.get('MATSUGIT_SAVE_UX_SOURCE') else '[data-layout="source"]').click()
            def current(): return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            def edit(value): frame.evaluate('(text)=>matsugitWorkspace.editor.dispatch({changes:{from:0,to:matsugitWorkspace.editor.state.doc.length,insert:text}})', value)
            def reread():
                frame.evaluate('matsugitWorkspace.reload()')
                wait(frame, '!matsugitWorkspace.state.merging')

            clean_update = original.replace('Last evidence', 'Updated evidence')
            source.write_text(clean_update); reread()
            assert current() == clean_update
            assert frame.locator('#notice-title').inner_text() == 'Loaded the updated file'
            assert frame.locator('#save-state').inner_text() == 'Saved to file'
            frame.locator('#notice-dismiss').click()
            assert frame.locator('#notice').is_hidden()

            mine = clean_update.replace('First evidence', 'My first evidence')
            incoming = clean_update.replace('Updated evidence', 'Agent final evidence')
            edit(mine); source.write_text(incoming); reread()
            merged = mine.replace('Updated evidence', 'Agent final evidence')
            assert current() == merged and source.read_text() == incoming
            assert frame.locator('#notice-title').inner_text() == 'Changes combined in your draft'
            assert 'Not saved to the file yet' in frame.locator('#notice-text').inner_text()
            frame.evaluate('matsugitWorkspace.flushRecovery()')
            wait(frame, 'document.getElementById("recovery-status").textContent === "Draft backed up"')
            assert frame.locator('#save-state').inner_text() == 'Unsaved draft'
            frame.evaluate('matsugitWorkspace.reload()')
            assert frame.locator('#notice-title').inner_text() == 'Changes combined in your draft'
            frame.locator('#notice-save').click()
            wait(frame, '!matsugitWorkspace.state.saving')
            assert source.read_text() == merged
            assert frame.locator('#save-state').inner_text() == 'Saved to file'
            assert frame.locator('#notice').is_hidden()

            local = merged.replace('My first evidence', 'My revised evidence')
            remote = merged.replace('My first evidence', 'Agent revised evidence')
            edit(local); source.write_text(remote); reread()
            assert current() == local and source.read_text() == remote
            assert frame.locator('#save').is_enabled()
            assert frame.locator('#save').get_attribute('aria-label') == 'Review changes before saving'
            frame.locator('#save').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            assert frame.locator('#incoming-dialog').is_hidden()
            assert frame.locator('#merge-apply').inner_text() == 'Save reviewed file'
            assert frame.locator('#merge-apply').is_disabled()
            assert source.read_text() == remote
            frame.locator('#merge-cancel').click()
            assert current() == local and source.read_text() == remote
            frame.locator('#reload').click()
            frame.locator('#merge-mine').click()
            assert frame.locator('#merge-apply').is_enabled()
            shots = Path(tempfile.mkdtemp(prefix='matsugit-save-experience-shots-'))
            for width in (1440,390):
                page.set_viewport_size({'width':width, 'height':1000})
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                box = frame.locator('#merge-dialog').bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= width
                page.screenshot(path=str(shots/f'review-save-{width}.png'))
            page.set_viewport_size({'width':1440, 'height':1000})

            failed = []
            def fail_one_write(route):
                if not failed and route.request.post_data_json.get('params',{}).get('name') == 'matsugit_save':
                    failed.append(True)
                    route.fulfill(json={'result':{'isError':True,'content':[{'type':'text','text':'Synthetic disk full'}]}})
                else: route.continue_()
            page.route('**/rpc', fail_one_write)
            frame.locator('#merge-apply').click()
            wait(frame, 'document.getElementById("merge-status").textContent.includes("disk full")')
            assert current() == local and source.read_text() == remote
            assert frame.locator('#merge-dialog').is_visible()
            assert frame.locator('#save-state').inner_text() == 'Not saved'
            frame.locator('#merge-apply').click()
            wait(frame, '!document.getElementById("merge-dialog").open')
            assert source.read_text() == local
            assert frame.locator('#save-state').inner_text() == 'Saved to file'
            page.unroute('**/rpc', fail_one_write)

            mine2 = local.replace('My revised evidence', 'My latest evidence')
            remote2 = local.replace('My revised evidence', 'Agent latest evidence')
            edit(mine2); source.write_text(remote2); reread()
            frame.locator('#save').click(); frame.locator('#merge-mine').click()
            latest = remote2 + '\nA newer file edit\n'
            def race_write(route):
                if route.request.post_data_json.get('params',{}).get('name') == 'matsugit_save': source.write_text(latest)
                route.continue_()
            page.route('**/rpc', race_write)
            frame.locator('#merge-apply').click()
            wait(frame, 'document.getElementById("merge-status").textContent.includes("changed again before saving")')
            assert source.read_text() == latest and current() == mine2
            page.unroute('**/rpc', race_write)
            assert frame.locator('#merge-recheck').is_visible()
            frame.locator('#merge-recheck').click()
            wait(frame, '!matsugitWorkspace.state.merging && document.getElementById("merge-dialog").open')
            # Latest independent edit is now in the reviewed result; no forced overwrite.
            assert 'A newer file edit' in frame.locator('#merge-complete').input_value()
            frame.locator('#merge-apply').click()
            wait(frame, '!document.getElementById("merge-dialog").open')
            assert source.read_text() == mine2 + '\nA newer file edit\n'
            records = [json.loads(f.read_text()) for f in Path(ready['recovery']).glob('*.json')]
            assert any(item['text'] == mine for item in records)
            assert not errors, errors
            print(f'PASS: clear file/backup states, persistent update receipts, Save-to-review, cancel, reviewed save, failed-write retry, concurrent-write refusal and re-review; screenshots {shots}', flush=True)
            browser.close()
    finally:
        host.terminate(); host.wait(timeout=30)
