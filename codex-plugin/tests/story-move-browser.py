"""Long-deck destination moves in the real UI, with no saves or publication."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=30):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError(expression)


original = '---\ntitle: Long narrative\nslide-layout: structured\n---\n\n'+''.join(
    f'# Chapter {section+1}\n\nSection introduction {section+1}.\n\n'+''.join(
        f'## Argument {section*10+i+1}\n### Claim {section*10+i+1}\n\nEvidence {section*10+i+1}\n\n'
        f'::: takeaway\nDecision {section*10+i+1}\n:::\n\n::: notes\nNotes {section*10+i+1}\n:::\n\n'
        for i in range(10)) for section in range(12))
with tempfile.TemporaryDirectory(prefix='matsugit-long-move-') as tmp:
    fixture = Path(tmp)/'long.md'; fixture.write_text(original)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE,text=True,env=dict(os.environ,
        MATSUGIT_SHOWCASE_SOURCE=str(fixture),QUARTO='/missing-quarto-for-editor-test'))
    try:
        ready = json.loads(host.stdout.readline()); source = Path(ready['source'])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []; page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{ready["port"]}'); frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck(); frame.locator('#sync').uncheck()
            frame.locator('button[data-layout="story"]').click()
            frame.locator('.story-slide').first.wait_for()
            def text(): return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            def titles(): return frame.locator('.story-slide .story-heading .story-title').all_text_contents()
            def undo(): frame.locator('#undo').click(); time.sleep(.15)
            def open_move(row): row.get_by_role('button',name='Move to...',exact=True).click()
            search = frame.locator('#story-move-search')
            position = frame.locator('#story-move-position')
            apply = frame.locator('#story-move-apply')
            assert len(titles()) == 120
            open_move(frame.locator('.story-slide').first)
            search.fill('118.')
            assert frame.locator('#story-destinations [role=option]').count() == 1
            assert 'Claim 118' in frame.locator('#story-destinations').inner_text()
            position.select_option('after'); apply.click()
            assert titles()[117] == 'Argument 1'
            assert 'Argument 1' in frame.locator('.story-selected .story-heading').inner_text()
            moved = text()
            assert 'Notes 1\n:::' in moved and 'Decision 1\n:::' in moved
            assert source.read_text() == original
            undo(); assert text() == original
            frame.locator('#redo').click(); assert text() == moved
            undo(); assert text() == original

            frame.locator('button[data-story-mode="walkthrough"]').click()
            frame.locator('button[data-story-size="compact"]').click()
            first = frame.locator('.story-slide').first; first.focus(); first.press('Alt+m')
            assert frame.locator('#story-move-dialog').is_visible()
            search.fill('section 12:'); position.select_option('start'); search.press('Enter')
            assert titles()[109:111] == ['Argument 1','Argument 111']
            assert frame.locator('.story-selected .story-context').inner_text() == 'Chapter 12'
            undo(); assert text() == original

            open_move(frame.locator('.story-section').first)
            search.fill('chapter 12'); position.select_option('after'); apply.click()
            assert titles()[-10:] == [f'Argument {i}' for i in range(1,11)]
            undo(); assert text() == original

            # A no-op or an empty search result cannot commit a move.
            open_move(frame.locator('.story-slide').first)
            search.fill('section 1:'); position.select_option('start')
            assert apply.is_disabled()
            search.fill('no-such-destination'); assert apply.is_disabled()
            assert 'No matching' in frame.locator('#story-move-status').inner_text()
            search.fill('Claim 118'); search.press('ArrowDown'); search.press('ArrowUp')
            assert search.get_attribute('aria-activedescendant') == 'story-destination-0'
            search.press('Escape'); assert text() == original
            assert not frame.locator('#story-move-dialog').is_visible()

            # An external edit while the dialog is open invalidates its offsets.
            open_move(frame.locator('.story-slide').first); search.fill('118.')
            frame.evaluate('''() => {const e=matsugitWorkspace.editor, from=e.state.doc.toString().indexOf('Evidence 4');
                e.dispatch({changes:{from,to:from+10,insert:'External evidence'}})}''')
            assert apply.is_disabled()
            assert 'Draft changed' in frame.locator('#story-move-status').inner_text()
            changed = text(); search.press('Enter'); assert text() == changed
            search.press('Escape'); undo(); assert text() == original

            # The dialog remains usable on a narrow screen with full destination labels.
            page.set_viewport_size({'width':390,'height':844})
            open_move(frame.locator('.story-slide').first); search.fill('chapter 12')
            assert frame.locator('#story-destinations [role=option]').first.inner_text().startswith('Section 12: Chapter 12')
            assert frame.locator('#story-move-dialog').evaluate('(e)=>e.scrollWidth <= e.clientWidth+1')
            assert frame.locator('#story-move-dialog').bounding_box()['width'] <= 390
            shots = Path(os.environ.get('MATSUGIT_MOVE_SHOTS','/tmp/matsugit-move-review'))
            shots.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(shots/'move-mobile.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            page.screenshot(path=str(shots/'move-desktop.png'))
            search.press('Escape')

            # Native drag events scroll at the list edge without changing selection/source.
            frame.locator('button[data-story-mode="overview"]').click()
            frame.locator('#story-list').evaluate('(e)=>e.scrollTop=0')
            handle = frame.locator('.story-slide').first.get_by_role('button',name='Drag slide')
            handle.evaluate('''e => {window.moveTestTransfer=new DataTransfer();
                e.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:moveTestTransfer}));}''')
            frame.locator('#story-list').evaluate('''e=> {const b=e.getBoundingClientRect();
                e.dispatchEvent(new DragEvent('dragover',{bubbles:true,clientX:b.left+40,clientY:b.bottom-10,dataTransfer:moveTestTransfer}));}''')
            wait(frame,'document.getElementById("story-list").scrollTop > 100')
            handle.dispatch_event('dragend')
            top = frame.locator('#story-list').evaluate('(e)=>e.scrollTop')
            time.sleep(.2)
            assert frame.locator('#story-list').evaluate('(e)=>e.scrollTop') == top
            assert text() == original and source.read_text() == original
            assert not errors, errors
            browser.close()
        print('PASS: 120-slide moves, sections, search, shortcut, Undo/Redo, stale drafts, mobile and edge scrolling')
    finally:
        host.terminate(); host.wait(timeout=20)
