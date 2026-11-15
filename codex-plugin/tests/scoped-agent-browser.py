"""A verified agent revision combines with unsaved author edits without a warning."""
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
def wait(frame, expression):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError((expression,frame.locator('#notice').inner_text()))

with tempfile.TemporaryDirectory(prefix='matsugit-scoped-agent-') as folder:
    source = Path(folder) / 'deck.md'
    source.write_text('## First\n\nSaved wording.\n\n## Second\n\nAuthor is typing here.\n')
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],stdout=subprocess.PIPE,text=True,
        env=dict(os.environ,MATSUGIT_TEST_SOURCE=str(source),MATSUGIT_STANDARD_MCP='1',
                 MATSUGIT_TEST_OPEN_OPTIONS='{"autosave":false,"editor":"raw"}'))
    try:
        ready=json.loads(host.stdout.readline()); url=f'http://127.0.0.1:{ready["port"]}'
        def tool(name, args):
            data=json.dumps({'method':'tools/call','params':{'name':name,'arguments':args}}).encode()
            with urllib.request.urlopen(urllib.request.Request(url+'/rpc',data=data)) as response:
                result=json.load(response)['result']
            assert not result.get('isError'), result
            return result['structuredContent']
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page=browser.new_page(); page.goto(url); frame=page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            before = frame.evaluate(TEXT)
            source.write_text(source.read_text().replace('Saved wording.','Saved wording, refreshed.'))
            wait(frame,'!!matsugitWorkspace.state.incomingReady')
            assert frame.evaluate(TEXT)==before
            assert frame.locator('#accept-update').inner_text()=='Accept update'
            assert frame.locator('#save-state').inner_text().strip()=='Update ready'
            frame.locator('#accept-update').click()
            wait(frame,TEXT+'.includes("refreshed") && !matsugitWorkspace.state.merging')
            frame.evaluate('''() => { const e=matsugitWorkspace.editor, at=e.state.doc.toString().indexOf('Saved wording, refreshed.');
                e.dispatch({changes:{from:at,to:at+25,insert:'Fresh author wording.'}}); }''')
            frame.locator('#save').click()
            wait(frame,'document.getElementById("save-state").textContent.trim()==="Saved to file"')
            frame.evaluate('''() => { const e=matsugitWorkspace.editor;
                e.dispatch({changes:{from:e.state.doc.length,insert:'Unsaved thought.'},selection:{anchor:e.state.doc.length+16}}); }''')
            selection=frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Fresh author wording.','new':'Clear agent wording.'}]})
            wait(frame,TEXT+'.includes("Clear agent wording.") && !matsugitWorkspace.state.merging')
            assert not frame.evaluate('!!matsugitWorkspace.state.incomingReady')
            assert frame.locator('#notice-title').inner_text()=='Agent changes combined'
            assert frame.evaluate(TEXT).endswith('Unsaved thought.')
            assert not frame.evaluate('matsugitWorkspace.state.conflict')
            assert frame.locator('#save-state').get_attribute('data-kind')=='dirty'
            assert frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')==selection-1
            assert 'Unsaved thought.' not in source.read_text()
            page.wait_for_timeout(1800)
            assert 'Unsaved thought.' not in source.read_text(), 'Autosave off must remain off'
            # Undo is isolated from the author's typing and never writes disk.
            frame.locator('#undo').click()
            assert 'Fresh author wording.' in frame.evaluate(TEXT)
            assert frame.evaluate(TEXT).endswith('Unsaved thought.')
            assert 'Clear agent wording.' in source.read_text()
            frame.locator('#redo').click()
            assert 'Clear agent wording.' in frame.evaluate(TEXT)
            # Typing during an asynchronous merge invalidates its first result.
            raced_typing=[]
            def type_during_merge(route):
                response=route.fetch()
                if not raced_typing and route.request.post_data_json.get('params',{}).get('name')=='matsugit_merge':
                    raced_typing.append(True)
                    frame.evaluate('''() => {const e=matsugitWorkspace.editor;
                      e.dispatch({changes:{from:e.state.doc.length,insert:' More typing during merge.'}});}''')
                route.fulfill(response=response)
            page.route('**/rpc',type_during_merge)
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Clear agent wording.','new':'Second agent wording.'}]})
            wait(frame,TEXT+'.includes("Second agent wording.") && !matsugitWorkspace.state.merging')
            page.unroute_all(behavior='wait')
            assert raced_typing
            assert 'Unsaved thought. More typing during merge.' in frame.evaluate(TEXT)
            assert 'Unsaved thought.' not in source.read_text()
            # Consecutive verified edits still keep the unsaved author text.
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Second agent wording.','new':'Clear agent wording.'}]})
            wait(frame,TEXT+'.includes("Clear agent wording.") && !matsugitWorkspace.state.merging')
            assert 'Unsaved thought. More typing during merge.' in frame.evaluate(TEXT)
            # An unknown stale rewrite after an agent edit never inherits trust.
            known_disk=source.read_text()
            source.write_text(before+'\nStale external rewrite.')
            wait(frame,'!!matsugitWorkspace.state.incomingReady')
            assert 'Clear agent wording.' in frame.evaluate(TEXT)
            assert 'Unsaved thought. More typing during merge.' in frame.evaluate(TEXT)
            assert not frame.evaluate('matsugitWorkspace.state.incomingReady.agent')
            source.write_text(known_disk)
            wait(frame,'!matsugitWorkspace.state.incomingReady')
            # A real overlap still needs review, regardless of attribution.
            frame.evaluate('''() => { const e=matsugitWorkspace.editor, at=e.state.doc.toString().indexOf('Clear agent wording.');
                e.dispatch({changes:{from:at,to:at+20,insert:'My overlapping wording.'}}); }''')
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Clear agent wording.','new':'Other overlapping wording.'}]})
            wait(frame,'matsugitWorkspace.state.conflict && !matsugitWorkspace.state.merging')
            assert frame.locator('#save-state').inner_text().strip()=='Review changes'
            assert frame.locator('#save-state .lucide-triangle-alert').count()==0
            assert 'My overlapping wording.' in frame.evaluate(TEXT)
            assert 'Other overlapping wording.' in source.read_text()
            assert frame.locator('#merge-dialog').is_visible()
            frame.locator('#merge-mine').click()
            frame.locator('#merge-apply').click()
            wait(frame,'!document.getElementById("merge-dialog").open && !matsugitWorkspace.state.saving')
            assert 'My overlapping wording.' in source.read_text()
            assert source.read_text().endswith('Unsaved thought. More typing during merge.')
            # Opted-in autosave persists only the successfully combined draft.
            frame.evaluate('document.getElementById("autosave").checked=true;document.getElementById("autosave").dispatchEvent(new Event("change"))')
            frame.evaluate('''() => {const e=matsugitWorkspace.editor;
              e.dispatch({changes:{from:e.state.doc.length,insert:' Autosaved author addition.'}});}''')
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'My overlapping wording.','new':'Agreed next wording.'}]})
            wait(frame,TEXT+'.includes("Agreed next wording.") && !matsugitWorkspace.state.merging')
            wait(frame,'document.getElementById("save-state").textContent.trim()==="Saved to file"')
            assert 'Agreed next wording.' in source.read_text()
            assert source.read_text().endswith(' Autosaved author addition.')
            frame.evaluate('document.getElementById("autosave").checked=false;document.getElementById("autosave").dispatchEvent(new Event("change"))')
            # A new revision arriving between the prompt and its click is not
            # accepted under the previous revision's consent.
            source.write_text(source.read_text()+'\nNext update.')
            wait(frame,'!!matsugitWorkspace.state.incomingReady')
            unchanged=frame.evaluate(TEXT)
            raced=[]
            def race(route):
                if not raced and route.request.post_data_json.get('params',{}).get('name')=='matsugit_read':
                    raced.append(True)
                    source.write_text(source.read_text()+'\nNewer revision.')
                route.continue_()
            page.route('**/rpc',race)
            frame.locator('#accept-update').click()
            wait(frame,'document.getElementById("notice-text").textContent.includes("changed again")')
            page.unroute('**/rpc',race)
            assert frame.evaluate(TEXT)==unchanged
            frame.locator('#accept-update').click()
            wait(frame,TEXT+'.includes("Newer revision.")')
            for width in (1280,390,320):
                page.set_viewport_size({'width':width,'height':900})
                source.write_text(source.read_text()+'\nMore incoming.')
                wait(frame,'!!matsugitWorkspace.state.incomingReady')
                assert frame.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=f'/tmp/matsugit-update-ready-{os.environ.get("MATSUGIT_TEST_HOST","standard")}-{width}.png')
                frame.locator('#accept-update').click()
                wait(frame,'!matsugitWorkspace.state.incomingReady && !matsugitWorkspace.state.merging')
            # Clean drafts also apply through an undoable merge, not a reset.
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Agreed next wording.','new':'Clean agent update.'}]})
            wait(frame,TEXT+'.includes("Clean agent update.") && !matsugitWorkspace.state.merging')
            frame.locator('#undo').click()
            assert 'Agreed next wording.' in frame.evaluate(TEXT)
            assert 'Clean agent update.' in source.read_text()
            # A new verified update must not consume a pending Redo.
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Clean agent update.','new':'Update after undo.'}]})
            wait(frame,'!!matsugitWorkspace.state.incomingReady')
            assert 'Agreed next wording.' in frame.evaluate(TEXT)
            frame.locator('#redo').click()
            wait(frame,TEXT+'.includes("Update after undo.") && !matsugitWorkspace.state.merging')
            # A pending rich-table edit is a draft too, even outside CodeMirror.
            source.write_text(source.read_text()+'\n\n| Metric | Value |\n| --- | --- |\n| Cost | 10 |\n')
            wait(frame,'!!matsugitWorkspace.state.incomingReady')
            frame.locator('#accept-update').click()
            wait(frame,TEXT+'.includes("| Cost |") && !matsugitWorkspace.state.merging')
            frame.evaluate('''() => {const e=matsugitWorkspace.editor;
              e.dispatch({selection:{anchor:e.state.doc.toString().indexOf('| Cost |')}});
              matsugitWorkspace.tables.atSelection();}''')
            wait(frame,'!!matsugitWorkspace.tables.rich && !document.getElementById("table-apply").disabled')
            frame.evaluate('''() => {const e=matsugitWorkspace.tables.rich;let cell;
              e.state.doc.descendants((n,pos)=>{if(cell===undefined && n.type.name==='tableCell')cell=pos;});
              e.commands.setTextSelection(cell+2);e.commands.insertContent('My pending table ');}''')
            wait(frame,'matsugitWorkspace.tables.pending()')
            pending=frame.evaluate('matsugitWorkspace.tables.rich.getHTML()')
            read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
            tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Update after undo.','new':'Update beside table.'}]})
            wait(frame,'!!matsugitWorkspace.state.incomingReady')
            assert frame.evaluate('matsugitWorkspace.tables.rich.getHTML()')==pending
            assert 'Update after undo.' in frame.evaluate(TEXT)
            frame.locator('#table-apply').click()
            wait(frame,TEXT+'.includes("Update beside table.") && !matsugitWorkspace.state.merging')
            assert 'My pending table' in frame.evaluate(TEXT)
            assert 'My pending table' not in source.read_text()
            # A late save acknowledgement cannot mark newer typing as saved or
            # replace it when an agent has already advanced the saved revision.
            delayed_save=[]
            def edit_before_save_ack(route):
                response=route.fetch()
                if not delayed_save and route.request.post_data_json.get('params',{}).get('name')=='matsugit_save':
                    delayed_save.append(True)
                    frame.evaluate('''() => {const e=matsugitWorkspace.editor;
                      e.dispatch({changes:{from:e.state.doc.length,insert:'\\nTyped after save started.'}});}''')
                    read=tool('matsugit_read_slide',{'path':str(source),'slide':1})
                    tool('matsugit_edit_slide',{'edit_id':read['edit_id'],'edits':[{'old':'Update beside table.','new':'Agent during save.'}]})
                route.fulfill(response=response)
            page.route('**/rpc',edit_before_save_ack)
            frame.locator('#save').click()
            wait(frame,TEXT+'.includes("Agent during save.") && !matsugitWorkspace.state.merging && !matsugitWorkspace.state.saving')
            page.unroute_all(behavior='wait')
            assert delayed_save
            assert frame.evaluate(TEXT).endswith('Typed after save started.')
            assert 'My pending table' in source.read_text()
            assert 'Typed after save started.' not in source.read_text()
            assert frame.locator('#save-state').inner_text().strip()=='Unsaved draft'
            browser.close(); print('PASS: protected automatic agent merges, isolated undo, concurrent typing, stale rewrite review, autosave independence, overlap, Redo, table drafts and delayed save replies')
    finally:
        host.terminate(); host.wait(timeout=20)
