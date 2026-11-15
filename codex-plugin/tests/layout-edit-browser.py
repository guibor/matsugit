"""Boundary protection, view continuity and explicit fit controls in the built app."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
def wait(frame, expression):
    end = time.monotonic() + 120
    while time.monotonic() < end:
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError(expression)

with tempfile.TemporaryDirectory(prefix='matsugit-layout-edit-') as tmp:
    source = Path(tmp) / 'deck.md'
    deck = '---\ntitle: Layout review\n---\n\n' + ''.join(
        f'## Slide {i} {{#slide-{i}}}\n\n### The claim\n\n:::: columns 1:1\n\n#### Left\n\n'
        + ('A **formatted** paragraph with a [link](https://example.invalid/long/path).\n\n' * 3)
        + '#### Right\n\nOther words\n\n::::\n\n' for i in range(1,16))
    source.write_text(deck)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        env=dict(os.environ,MATSUGIT_SHOWCASE_SOURCE=str(source)),stdout=subprocess.PIPE,text=True)
    try:
        ready=json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]; page.on('pageerror',lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame=page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck(); frame.locator('#sync').uncheck()
            assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'visual'
            # A partial fence deletion is rejected without an Undo entry.
            assert frame.evaluate('''() => {
              const e=matsugitWorkspace.editor, before=e.state.doc.toString(), p=before.indexOf('::::');
              e.dispatch({changes:{from:p,to:p+1,insert:''},userEvent:'delete.backward'});
              return e.state.doc.toString()===before;
            }''')
            wait(frame,"document.getElementById('notice-text').textContent.includes('Layout boundary protected')")
            # Prose remains editable, and the safe ratio control can alter its fence.
            frame.evaluate('''() => { const e=matsugitWorkspace.editor,p=e.state.doc.toString().indexOf('Other words');
              e.dispatch({changes:{from:p,to:p+5,insert:'Better'},selection:{anchor:p},userEvent:'input.type',scrollIntoView:true}); }''')
            assert 'Better words' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            frame.locator('select[aria-label="Column proportions"]').first.select_option('2:1')
            assert ':::: columns 2:1' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            # Choose a passage halfway through the file, then toggle repeatedly.
            frame.evaluate('''() => { const e=matsugitWorkspace.editor,p=e.state.doc.toString().indexOf('Other words',e.state.doc.toString().indexOf('## Slide 8 '));
              e.dispatch({selection:{anchor:p},scrollIntoView:true}); }''')
            time.sleep(.3)
            position=frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            def caret_y():
                return frame.evaluate('''() => { const e=matsugitWorkspace.editor;
                  return e.coordsAtPos(e.state.selection.main.head).top-e.scrollDOM.getBoundingClientRect().top; }''')
            before=caret_y()
            for mode in ['raw','visual','raw','visual']:
                frame.locator(f'[data-editor="{mode}"]').click(); time.sleep(.3)
                assert frame.evaluate('matsugitWorkspace.editor.state.selection.main.head') == position
                assert abs(caret_y()-before)<35,(mode,before,caret_y())
            # With the caret offscreen, preserve the passage being read instead.
            frame.evaluate('''() => { const e=matsugitWorkspace.editor; e.dispatch({selection:{anchor:0}});
              e.scrollDOM.scrollTop+=300; }''')
            time.sleep(.2)
            anchor=frame.evaluate('''() => { const e=matsugitWorkspace.editor,b=e.scrollDOM.getBoundingClientRect();
              const pos=e.posAtCoords({x:b.left+100,y:b.top+8},false); return {pos,y:e.coordsAtPos(pos).top-b.top}; }''')
            frame.locator('[data-editor="raw"]').click(); time.sleep(.3)
            actual=frame.evaluate('''pos => {const e=matsugitWorkspace.editor;return e.coordsAtPos(pos).top-e.scrollDOM.getBoundingClientRect().top;}''',anchor['pos'])
            assert abs(actual-anchor['y'])<35,(anchor,actual)
            # Raw remains the explicit escape hatch for structural edits.
            frame.evaluate('''() => {const e=matsugitWorkspace.editor,p=e.state.doc.toString().indexOf('::::');e.dispatch({changes:{from:p,to:p+1,insert:''},userEvent:'delete.backward'});}''')
            assert '::: columns 2:1' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            frame.evaluate('''() => {const e=matsugitWorkspace.editor,p=e.state.doc.toString().indexOf('Other words');e.dispatch({selection:{anchor:p},scrollIntoView:true});}''')
            frame.locator('[data-editor="visual"]').click()
            frame.locator('#slide-spacing').select_option('compact')
            assert '{#slide-2 .tight}' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            frame.locator('#slide-spacing').select_option('normal')
            assert '.tight' not in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':900}); time.sleep(.3)
                assert frame.locator('#slide-spacing').is_visible()
                frame.locator('body').screenshot(path=f'/tmp/matsugit-layout-editor-{width}.png')
            assert not errors,errors
            browser.close()
            print('PASS: structural protection, prose/ratio edits, Raw escape, passage continuity and spacing controls')
    finally:
        host.terminate(); host.wait(timeout=10)
