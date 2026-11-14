"""Real MCP history: external edits, restore, undo, restart and stale review."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TEXT = 'matsugitWorkspace.editor.state.doc.toString()'


def wait(frame, expression, timeout=25):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-2500:])


with tempfile.TemporaryDirectory(prefix='matsugit-history-browser-') as tmp:
    source = Path(tmp) / 'deck.md'
    original = '# Plan\n\n## First\n### Claim\n\nOriginal content.\n\n## Second\n\nOther content.\n'
    source.write_text(original)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE,text=True,env=dict(os.environ,MATSUGIT_STANDARD_MCP='1',
        MATSUGIT_TEST_SOURCE=str(source),QUARTO='/missing-for-history-test',
        MATSUGIT_TEST_OPEN_OPTIONS='{"autosave":false,"editor":"raw","layout":"source"}'))
    try:
        ready = json.loads(host.stdout.readline())
        address = f'http://127.0.0.1:{ready["port"]}'
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1200,'height':900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(address)
            frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()

            def replace(old,new):
                frame.evaluate('''([old,value])=>{const e=matsugitWorkspace.editor;const from=e.state.doc.toString().indexOf(old);
                  e.dispatch({changes:{from,to:from+old.length,insert:value}});}''',[old,new])

            replace('Original content.','My new content.')
            frame.locator('#save').click()
            wait(frame,'!matsugitWorkspace.state.saving && matsugitWorkspace.state.base.includes("My new content.")')
            source.write_text(source.read_text().replace('Other content.','External content.'))
            frame.evaluate('matsugitWorkspace.reload(false,true,null,true)')
            wait(frame,TEXT+'.includes("External content.") && !matsugitWorkspace.state.merging')
            after = source.read_text()
            # Real MCP restart. The existing panel reconnects, with history intact.
            assert page.request.post(address+'/restart').ok
            frame.locator('#history-open').click()
            frame.locator('#history-items button').filter(has_text='Opened file').first.click()
            wait(frame,'!document.getElementById("history-restore-slide").disabled')
            frame.locator('#history-slide').select_option('0')
            frame.locator('#history-destination').select_option('0')
            frame.locator('#history-restore-slide').click()
            wait(frame,'!document.getElementById("history-dialog").open')
            assert 'Original content.' in frame.evaluate(TEXT)
            assert 'External content.' in frame.evaluate(TEXT)
            assert source.read_text() == after
            # Restores stay drafts even if automatic saving was selected.
            frame.evaluate('matsugitWorkspace.state.autosave=true')
            replace('Original content.','Restored draft typing.')
            time.sleep(2)
            assert source.read_text() == after
            frame.locator('#undo').click()
            frame.locator('#undo').click()
            assert frame.evaluate(TEXT) == after
            frame.evaluate('matsugitWorkspace.state.autosave=false')
            frame.locator('#history-open').click()
            frame.locator('#history-items button').filter(has_text='Opened file').first.click()
            wait(frame,'!document.getElementById("history-restore-document").disabled')
            # Edits during the comparison invalidate it; no silent draft loss.
            replace('My new content.','Typing while history is open.')
            frame.locator('#history-restore-document').click()
            wait(frame,'document.getElementById("history-status").textContent.includes("draft changed")')
            assert 'Typing while history is open.' in frame.evaluate(TEXT)
            frame.locator('#history-close').click()
            frame.locator('#history-open').click()
            frame.locator('#history-items button').filter(has_text='Opened file').first.click()
            wait(frame,'!document.getElementById("history-restore-document").disabled')
            frame.locator('#history-restore-document').click()
            wait(frame,'!document.getElementById("history-dialog").open')
            assert frame.evaluate(TEXT) == original
            assert source.read_text() == after
            frame.locator('#save').click()
            wait(frame,'!matsugitWorkspace.state.saving && !matsugitWorkspace.state.restorePending')
            assert source.read_text() == original
            for width in (1200,390):
                page.set_viewport_size({'width':width,'height':900})
                frame.locator('#history-open').click()
                frame.locator('#history-items button').first.wait_for()
                assert frame.evaluate('document.getElementById("history-dialog").scrollWidth <= document.getElementById("history-dialog").clientWidth + 2')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'matsugit-history-{os.environ.get("MATSUGIT_TEST_HOST","standard")}-{width}.png'))
                frame.locator('#history-close').click()

            other = Path(tmp)/'other.md'
            other.write_text('## Other document\n\nUnrelated content.\n')
            opened = page.request.post(address+'/rpc',data=json.dumps({'method':'tools/call','params':{
                'name':'matsugit_open','arguments':{'path':str(other),'layout':'source','autosave':False}}})).json()['result']['structuredContent']
            pending = []
            def hold_history(route):
                params = json.loads(route.request.post_data).get('params',{})
                if params.get('name') == 'matsugit_history_read' and not pending:
                    pending.append((route,route.fetch()))
                else:
                    route.continue_()
            page.route('**/rpc',hold_history)
            frame.locator('#history-open').click()
            frame.locator('#history-items button').first.click()
            deadline = time.monotonic()+20
            while not pending and time.monotonic()<deadline:
                page.wait_for_timeout(50)
            assert pending, 'History read was not intercepted'
            frame.evaluate('(data)=>{void matsugitWorkspace.load(data,{acceptRevision:matsugitWorkspace.state.revision});}',opened)
            wait(frame,'matsugitWorkspace.state.name === "other.md" && !matsugitWorkspace.state.loading')
            pending[0][0].fulfill(response=pending[0][1])
            page.unroute_all(behavior='wait')
            wait(frame,'document.getElementById("history-status").textContent.includes("document changed")')
            assert frame.locator('#history-restore-document').is_disabled()
            assert frame.evaluate(TEXT) == other.read_text()
            frame.locator('#history-close').click()

            # A late open checkpoint must not reapply the previous file's view.
            first = page.request.get(address+'/result').json()['structuredContent']
            first.update(layout='story',autosave=True)
            pending.clear()
            def hold_open(route):
                params = json.loads(route.request.post_data).get('params',{})
                if params.get('name') == 'matsugit_history_record' and params.get('arguments',{}).get('reason') == 'opened' and not pending:
                    pending.append((route,route.fetch()))
                else:
                    route.continue_()
            page.route('**/rpc',hold_open)
            frame.evaluate('(data)=>{void matsugitWorkspace.load(data,{acceptRevision:matsugitWorkspace.state.revision});}',first)
            deadline = time.monotonic()+20
            while not pending and time.monotonic()<deadline:
                page.wait_for_timeout(50)
            assert pending, 'Open checkpoint was not intercepted'
            frame.evaluate('(data)=>{void matsugitWorkspace.load(data,{acceptRevision:matsugitWorkspace.state.revision});}',opened)
            wait(frame,'matsugitWorkspace.state.name === "other.md" && !matsugitWorkspace.state.loading')
            pending[0][0].fulfill(response=pending[0][1])
            page.unroute_all(behavior='wait')
            page.wait_for_timeout(200)
            assert frame.evaluate('matsugitWorkspace.state.layout') == 'source'
            assert not frame.evaluate('matsugitWorkspace.state.autosave')
            assert frame.evaluate(TEXT) == other.read_text()
            assert source.read_text() == original
            assert not errors, errors
            browser.close()
            print('PASS: history survives restart; restore, Undo, autosave pause, stale review and delayed document-switch protection')
    finally:
        host.terminate()
        host.wait(timeout=30)
