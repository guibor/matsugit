"""Real built workspace: source fidelity, tables, recovery, clipboard and responsive UI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', tempfile.mkdtemp(prefix='matsugit-visual-shots-')))
shots.mkdir(parents=True, exist_ok=True)

def wait(frame, expression, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.15)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-2000:])

host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
    env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(Path(__file__).with_name('visual.md'))), stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    source = Path(ready['source']); original = source.read_text()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        context = browser.new_context(viewport={'width':1600,'height':1000}, permissions=['clipboard-read','clipboard-write'])
        page = context.new_page(); errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        frame.locator('#auto').uncheck(); frame.locator('#sync').uncheck()
        frame.locator('#copy-path').click()
        print('Clipboard and first render ready', flush=True)
        assert page.evaluate('navigator.clipboard.readText()') == str(source.resolve())
        assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'raw'
        frame.locator('[data-editor="visual"]').click()
        wait(frame, 'document.querySelectorAll(".ff-visual-table table").length===1')
        assert frame.locator('.ff-visual-heading').count() >= 3
        assert frame.locator('.ff-visual-table').inner_text().count('Cycle time') == 1
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        assert not frame.locator('.cm-content').inner_text().count('https://example.com/a-long-report-address')
        page.screenshot(path=str(shots/'01-visual-document.png'))
        frame.locator('[data-editor="raw"]').click()
        assert frame.locator('.ff-visual-table').count() == 0
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        frame.locator('[data-editor="visual"]').click()
        frame.locator('.ff-visual-table button').click()
        wait(frame, '!document.getElementById("table-apply").disabled')
        frame.evaluate('''() => {
          const e=matsugitWorkspace.tables.rich; let cells=[];
          e.state.doc.descendants((n,pos)=>{if(n.type.name==='tableCell')cells.push(pos);});
          e.commands.setTextSelection(cells[1]+2); e.commands.insertContent('Faster ');
        }''')
        wait(frame, 'matsugitWorkspace.tables.pending()')
        frame.evaluate('matsugitWorkspace.flushRecovery()')
        records = [json.loads(f.read_text()) for f in Path(ready['recovery']).glob('*.json')]
        assert any('Faster' in (r['view'].get('tableDraft') or {}).get('html','') for r in records)
        assert source.read_text() == original
        page.screenshot(path=str(shots/'02-table-editor.png'))
        frame.locator('#table-apply').click()
        wait(frame, '!document.getElementById("table-dialog").open')
        applied = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        assert 'Faster' in applied and '```markdown' in applied
        assert source.read_text() == original
        frame.locator('#undo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == original
        frame.locator('#redo').click()
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == applied
        print('Pipe table edit and unified undo/redo passed', flush=True)
        frame.locator('.ff-visual-table button').click()
        wait(frame, '!document.getElementById("table-apply").disabled')
        frame.evaluate('''() => {
          const e=matsugitWorkspace.tables.rich;let cells=[];
          e.state.doc.descendants((n,pos)=>{if(n.type.name==='tableHeader')cells.push(pos);});
          e.commands.setCellSelection({anchorCell:cells[0],headCell:cells[1]});
        }''')
        frame.locator('[aria-label="Merge selected cells"]').click()
        frame.locator('#table-apply').click()
        wait(frame, '!document.getElementById("table-dialog").open')
        merged = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
        assert '+---' in merged and '<table' not in merged
        wait(frame, r'!!document.querySelector(".ff-visual-table th[colspan=\"2\"]")', 20)
        print('Grid table visible', flush=True)
        frame.locator('#save').click()
        wait(frame, '!matsugitWorkspace.state.saving && matsugitWorkspace.state.base===matsugitWorkspace.editor.state.doc.toString()')
        assert source.read_text() == merged
        print('Explicit save passed', flush=True)
        # An agent or external refresh must not be overwritten by an old table dialog.
        frame.locator('.ff-visual-table button').click()
        wait(frame, '!document.getElementById("table-apply").disabled')
        frame.evaluate("matsugitWorkspace.editor.dispatch({changes:{from:0,insert:'<!-- another edit -->\\n'}})")
        frame.locator('#table-apply').click()
        wait(frame, 'document.getElementById("table-status").textContent.includes("Document changed")', 20)
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString().startsWith("<!-- another edit -->")')
        frame.locator('#table-close').click()
        print('Concurrent-edit guard passed', flush=True)
        # Open a new unapplied draft and verify restoration, not only serialization.
        frame.locator('.ff-visual-table button').click()
        wait(frame, '!document.getElementById("table-apply").disabled')
        frame.evaluate('matsugitWorkspace.tables.rich.commands.insertContent("RECOVER-ME ")')
        frame.evaluate('matsugitWorkspace.flushRecovery()')
        page.reload()
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered && !document.getElementById("recovery-banner").hidden')
        frame.locator('#restore-draft').click()
        wait(frame, 'document.getElementById("table-dialog").open && !document.getElementById("table-apply").disabled')
        assert 'RECOVER-ME' in frame.locator('#table-content').inner_text()
        assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'visual'
        print('Unapplied table recovery passed', flush=True)
        frame.locator('#table-close').click()
        for width,height in [(390,844),(768,1024)]:
            page.set_viewport_size({'width':width,'height':height})
            page.screenshot(path=str(shots/f'visual-{width}.png'))
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not frame.locator('.ff-visual-table button').is_disabled()
        frame.locator('#auto').uncheck()
        timing = frame.evaluate('''() => {
          const e=matsugitWorkspace.editor;
          const head='| Area | A | B | C | D | E | F |\\n| --- | --- | --- | --- | --- | --- | --- |\\n';
          const rows=Array.from({length:20},(_,i)=>'| Row '+i+' | '+Array.from({length:4},(_,j)=>
            '[Evidence '+j+'](https://example.com/'+('long-path-'.repeat(10))+i+')').join(' | ')+' | Text | More |').join('\\n');
          const source=Array.from({length:3},(_,i)=>'## Section '+i+'\\n\\n'+head+rows).join('\\n\\n')+'\\n\\nEnd';
          const start=performance.now(); e.dispatch({changes:{from:0,to:e.state.doc.length,insert:source}});
          const opened=performance.now()-start, edit=performance.now();
          for(let i=0;i<20;i++)e.dispatch({changes:{from:e.state.doc.length,insert:'x'}});
          return {bytes:source.length,opened,edits:performance.now()-edit};
        }''')
        assert timing['opened'] < 5000 and timing['edits'] < 5000, timing
        print('Dense-link visual smoke timings (ms): '+json.dumps(timing), flush=True)
        assert not errors, errors
        page.close(run_before_unload=False); browser.close()
        print('PASS: raw/visual fidelity, pipe/grid editing, undo/redo, save, conflict guard, draft recovery, clipboard, mobile layout')
finally:
    host.terminate()
    try: host.wait(timeout=15)
    except subprocess.TimeoutExpired: host.kill(); host.wait()
