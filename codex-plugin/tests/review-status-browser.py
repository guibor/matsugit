"""Real plugin review/status UI with synthetic files, no provider requests."""
import hashlib
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
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError((expression, frame.locator('body').inner_text()[-2500:]))


with tempfile.TemporaryDirectory(prefix='matsugit-review-status-') as tmp:
    root = Path(tmp)
    fixture = root/'deck.md'
    original = '# Review\n\n## First\n\nAlpha original\n\n## Second\n\nBeta original\n\n## Third\n\nGamma original\n'
    fixture.write_text(original)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],stdout=subprocess.PIPE,text=True,
        env=dict(os.environ,MATSUGIT_SHOWCASE_SOURCE=str(fixture),QUARTO='/missing-quarto-for-editor-test'))
    try:
        ready = json.loads(host.stdout.readline()); source = Path(ready['source'])
        receipts = Path(ready['publication']); receipts.mkdir(exist_ok=True)
        receipt_file = receipts/(hashlib.sha256(str(source.resolve()).encode()).hexdigest()+'.json')
        receipt_file.write_text(json.dumps(dict(version=1,stage='pushed',revision='a'*40,pushed_at='2026-01-01T00:00:00Z',
            source_sha256=hashlib.sha256(original.encode()).hexdigest(),detail='Pushed; deployment not verified.',
            project_url='https://example.invalid/test/docs',pipeline_url='https://example.invalid/test/pipeline/1')))
        shots = Path(tempfile.mkdtemp(prefix='matsugit-review-status-shots-'))
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []; page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{ready["port"]}'); frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck(); frame.locator('#sync').uncheck()
            frame.locator('[data-layout="source"]').click()
            wait(frame,'document.getElementById("publication-state").textContent === "Pushed" && !document.getElementById("publication-state").disabled')
            frame.locator('#publication-state').click()
            assert 'a'*40 in frame.locator('#publication-details').inner_text()
            assert frame.locator('#publication-pipeline').get_attribute('href').endswith('/pipeline/1')
            frame.locator('#publication-close').click()
            def current(): return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            def edit(value): frame.evaluate('(text)=>matsugitWorkspace.editor.dispatch({changes:{from:0,to:matsugitWorkspace.editor.state.doc.length,insert:text}})',value)
            mine = original.replace('Alpha original','Alpha mine')
            incoming = original.replace('Beta original','Beta agent').replace('Gamma original','Gamma agent')
            edit(mine); source.write_text(incoming)
            frame.evaluate('matsugitWorkspace.reload()')
            wait(frame,'!matsugitWorkspace.state.merging')
            assert current() == mine.replace('Beta original','Beta agent').replace('Gamma original','Gamma agent')
            assert frame.locator('#publication-state').inner_text() == 'Changes not pushed'
            edit(current().replace('Alpha mine','Alpha later typing'))
            disk_before_review = current()
            frame.locator('#save').click(); wait(frame,'!matsugitWorkspace.state.saving')
            assert source.read_text() == disk_before_review
            frame.locator('#external-review').click()
            frame.locator('#changes-dialog').wait_for(state='visible')
            assert frame.locator('#changes-list h3').all_text_contents() == ['Second','Third']
            frame.locator('#changes-list input').first.uncheck()
            frame.locator('#changes-preview').click()
            wait(frame,'!document.getElementById("changes-apply").disabled')
            expected = original.replace('Alpha original','Alpha later typing').replace('Gamma original','Gamma agent')
            assert frame.locator('#changes-result').input_value() == expected
            assert current() != expected and source.read_text() == disk_before_review
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                bounds = frame.locator('#changes-dialog').bounding_box()
                assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
                assert frame.evaluate('document.getElementById("changes-dialog").scrollWidth <= document.getElementById("changes-dialog").clientWidth')
                page.screenshot(path=str(shots/f'review-{width}.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            frame.locator('#changes-apply').click()
            frame.locator('#changes-dialog').wait_for(state='hidden')
            assert current() == expected and source.read_text() == disk_before_review
            frame.locator('#save').click(); wait(frame,'!matsugitWorkspace.state.saving')
            assert source.read_text() == expected
            assert frame.locator('#publication-state').inner_text() == 'Changes not pushed'
            print('PASS: grouped review, selective rejection after auto-merge and Save, later typing retained, preview before apply, no implicit save',flush=True)

            # Overlap plus clean edit: use the conflict resolver inside review.
            edit(expected.replace('Alpha later typing','Alpha local overlap'))
            remote = expected.replace('Alpha later typing','Alpha external overlap').replace('Beta original','Beta second agent')
            source.write_text(remote); frame.evaluate('matsugitWorkspace.reload()')
            frame.locator('#external-review').click()
            frame.locator('#changes-dialog').wait_for(state='visible')
            frame.locator('#changes-preview').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            frame.locator('#merge-mine').click(); frame.locator('#merge-apply').click()
            wait(frame,'!document.getElementById("changes-apply").disabled')
            before = current()
            source.write_text(remote+'\nNew external line\n')
            frame.locator('#changes-apply').click()
            wait(frame,'document.getElementById("changes-status").textContent.includes("changed again")')
            assert current() == before
            frame.locator('#changes-cancel').click()
            assert not errors, errors
            page.close(); browser.close()
            print(f'PASS: nested conflict resolution, stale disk refused, publication status; screenshots {shots}',flush=True)
    finally:
        host.terminate(); host.wait(timeout=20)
