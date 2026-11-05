"""Reproduce agent disk updates + Undo, dirty conflicts and delayed reload races."""
import json
import os
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
host = subprocess.Popen(['node', str(ROOT/'codex-plugin/tests/browser-host.mjs')],
    stdout=subprocess.PIPE, text=True,
    env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(ROOT/'codex-plugin/tests/visual.md')))
try:
    ready=json.loads(host.stdout.readline())
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.add_init_script('''Object.defineProperty(document,'modelContext',{value:{registerTool(tool){
          window.registeredTools ||= {};window.registeredTools[tool.name]=tool;}}});''')
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame=page.frames[1]
        frame.wait_for_function('()=>!!window.matsugitWorkspace?.state.rendered',timeout=180000)
        frame.locator('#auto').uncheck();frame.locator('#sync').uncheck()
        original=Path(ready['source']).read_text()
        # An initial file read must never be an undoable insertion of the whole file.
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==original, 'Undo erased the initial file'
        draft=original+'\nLocal draft\n'
        frame.evaluate('(s)=>matsugitWorkspace.editor.dispatch({changes:{from:0,to:matsugitWorkspace.editor.state.doc.length,insert:s},userEvent:"input.type"})',draft)
        frame.evaluate('registeredTools.matsugit_replace_source.execute({revision:matsugitWorkspace.state.revision,text:matsugitWorkspace.editor.state.doc.toString()+"\\nAgent workspace patch\\n"})')
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==draft, 'Agent patch joined the local typing undo group'
        frame.locator('#save').click()
        frame.wait_for_function('()=>!matsugitWorkspace.state.saving')
        assert Path(ready['source']).read_text()==draft
        incoming=original+'\nAgent disk edit\n'
        Path(ready['source']).write_text(incoming)
        frame.evaluate('matsugitWorkspace.reload()')
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==draft, 'An agent update replaced recently saved local edits without review'
        frame.locator('#reload').click()
        frame.locator('#incoming-dialog').wait_for(state='visible')
        frame.locator('#incoming-use').click()
        frame.wait_for_function('()=>!document.getElementById("incoming-dialog").open')
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==incoming
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==incoming, 'Undo crossed the external baseline'
        frame.evaluate('matsugitWorkspace.editor.dispatch({changes:{from:0,insert:"My unsaved text\\n"},userEvent:"input.type"})')
        edited=frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        Path(ready['source']).write_text(incoming+'\nSecond agent edit\n')
        frame.evaluate('matsugitWorkspace.reload()')
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        assert frame.evaluate('matsugitWorkspace.state.conflict')
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==incoming
        page.wait_for_timeout(3500)
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==incoming, 'Polling replaced an undone draft before Redo'
        frame.locator('#redo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        frame.locator('#refresh').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        # Editing while an explicitly requested reload is in flight must win.
        held=[]
        def delay_read(route):
            request=route.request.post_data_json
            if not held and request.get('method')=='tools/call' and request.get('params',{}).get('name')=='matsugit_read':
                held.append((route,route.fetch()))
            else:route.continue_()
        page.route('**/rpc',delay_read)
        frame.evaluate('void matsugitWorkspace.reload(true,true)')
        for _ in range(100):
            if held:break
            page.wait_for_timeout(50)
        assert held, 'Did not intercept the in-flight reload'
        frame.evaluate('matsugitWorkspace.editor.dispatch({changes:{from:0,insert:"Typed during reload\\n"},userEvent:"input.type"})')
        edited='Typed during reload\n'+edited
        held[0][0].fulfill(response=held[0][1])
        page.wait_for_timeout(100)
        page.unroute('**/rpc',delay_read)
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        frame.locator('#reload').click()
        frame.locator('#incoming-dialog').wait_for(state='visible')
        assert frame.locator('#incoming-local').input_value()==edited
        assert frame.locator('#incoming-file').input_value()==incoming+'\nSecond agent edit\n'
        if os.environ.get('MATSUGIT_SCREENSHOTS'):
            page.screenshot(path=str(Path(os.environ['MATSUGIT_SCREENSHOTS'])/'draft-review.png'))
        frame.locator('#incoming-keep').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        # The reviewed version must still be current when explicitly accepted.
        frame.locator('#reload').click()
        frame.locator('#incoming-dialog').wait_for(state='visible')
        latest=incoming+'\nThird agent edit\n'
        Path(ready['source']).write_text(latest)
        frame.locator('#incoming-use').click()
        frame.wait_for_function('()=>!document.getElementById("incoming-use").disabled')
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        assert frame.locator('#incoming-dialog').is_visible()
        frame.locator('#incoming-keep').click()
        # Repeat open notifications must not prompt or replace a dirty draft.
        dialogs=[]
        page.on('dialog',lambda d:(dialogs.append(d.message),d.dismiss()))
        frame.evaluate('(s)=>matsugitWorkspace.load({name:"visual.md",text:s})',original)
        assert not dialogs, 'Host notifications must not use native confirmation dialogs'
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==edited
        frame.evaluate('matsugitWorkspace.flushRecovery()')
        records=[json.loads(f.read_text()) for f in Path(ready['recovery']).glob('*.json')]
        assert any(r['text']==edited for r in records)
        assert Path(ready['source']).read_text()==latest
        # Explicitly choosing a new source keeps the old draft in a separate record.
        frame.locator('#reload').click()
        frame.locator('#incoming-dialog').wait_for(state='visible')
        frame.locator('#incoming-use').click()
        frame.wait_for_function('()=>!document.getElementById("incoming-dialog").open')
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==original
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==original
        frame.evaluate('matsugitWorkspace.flushRecovery()')
        records=[json.loads(f.read_text()) for f in Path(ready['recovery']).glob('*.json')]
        assert any(r['text']==edited for r in records), 'Safety copy was overwritten after accepting incoming source'
        print('PASS: initial/external baseline Undo, local Undo/Redo after conflicts, Refresh, repeated opens, recovery and disk preservation')
        browser.close()
finally:
    host.terminate()
    try:host.wait(timeout=15)
    except subprocess.TimeoutExpired:host.kill();host.wait()
