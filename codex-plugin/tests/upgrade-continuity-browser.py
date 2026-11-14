"""Keep a real 0.34 panel and its draft across a server bundle upgrade."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASELINE = 'fbe1ad13b66474039e2f13ac076718d544b7e3df'
TEXT = 'matsugitWorkspace.editor.state.doc.toString()'

def wait(frame, expression):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-2000:])

with tempfile.TemporaryDirectory(prefix='matsugit-upgrade-test-') as tmp:
    root = Path(tmp)
    old = root/'server.mjs'
    old.write_bytes(subprocess.check_output(['git','show',BASELINE+':codex-plugin/bundle/server.mjs'],cwd=ROOT))
    source = root/'deck.md'
    source.write_text('## First\n\nOriginal claim.\n\n## Second\n\nOriginal evidence.\n')
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE,text=True,env=dict(os.environ,MATSUGIT_STANDARD_MCP='1',
        MATSUGIT_TEST_SOURCE=str(source),MATSUGIT_TEST_INITIAL_SERVER=str(old),
        QUARTO='/missing-for-upgrade-test',
        MATSUGIT_TEST_OPEN_OPTIONS='{"autosave":false,"editor":"raw","layout":"source"}'))
    try:
        ready = json.loads(host.stdout.readline())
        address = f'http://127.0.0.1:{ready["port"]}'
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1200,'height':900})
            page.goto(address)
            frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.evaluate('''()=>{const e=matsugitWorkspace.editor;const from=e.state.doc.toString().indexOf('Original claim.');
                e.dispatch({changes:{from,to:from+15,insert:'My unsaved claim.'}});}''')
            assert 'My unsaved claim.' not in source.read_text()
            assert page.request.post(address+'/restart').ok
            source.write_text(source.read_text().replace('Original evidence.','External evidence.'))
            frame.evaluate('matsugitWorkspace.reload(false,true,null,true)')
            wait(frame,TEXT+'.includes("External evidence.") && !matsugitWorkspace.state.merging')
            assert 'My unsaved claim.' in frame.evaluate(TEXT)
            assert len(page.main_frame.child_frames) == 1
            frame.locator('#save').click()
            wait(frame,'!matsugitWorkspace.state.saving && matsugitWorkspace.state.base.includes("My unsaved claim.")')
            assert 'My unsaved claim.' in source.read_text()
            assert 'External evidence.' in source.read_text()
            page.reload()
            frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            assert frame.evaluate(TEXT) == source.read_text()
            frame.locator('#history-open').click()
            frame.locator('#history-items button').filter(has_text='Saved file').first.wait_for()
            browser.close()
            print('PASS: 0.34 panel retains draft across server upgrade, reconciles, saves, and reopens with history')
    finally:
        host.terminate()
        host.wait(timeout=30)
