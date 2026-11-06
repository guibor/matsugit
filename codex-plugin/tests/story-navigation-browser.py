"""Story scrolling, explicit selection and takeaways in the real embedded app."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression):
    deadline = time.monotonic() + 30
    while not frame.evaluate(expression):
        assert time.monotonic() < deadline, expression
        time.sleep(.05)


with tempfile.TemporaryDirectory(prefix='matsugit-story-keys-') as tmp:
    source = '---\ntitle: A narrative\n---\n\n'
    for section in range(3):
        source += f'# Section {section+1}\n\n'
        for slide in range(8):
            source += f'## Slide {section*8+slide+1}\n### A clear claim\n\nEvidence.\n\n'
            source += '::: takeaway\nKeep the decision visible\n:::\n\n'
    source += '## Final\n\n> [!TAKEAWAY]\n> Keep the next step small\n\n'
    source += '::: takeaway\nOne line\nAnother line\n:::\n'
    fixture = Path(tmp)/'narrative.md'
    fixture.write_text(source)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE,
        text=True, env=dict(os.environ,MATSUGIT_SHOWCASE_SOURCE=str(fixture),QUARTO='/missing-editor-test'))
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1440,'height':900})
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.locator('button[data-layout="story"]').click()
            frame.locator('.story-slide').first.wait_for()
            listing = frame.locator('#story-list')
            def selected(): return frame.locator('.story-selected').count()
            def scroll(): return listing.evaluate('(el)=>el.scrollTop')
            def clear():
                listing.click(position={'x':2,'y':2})
                assert selected() == 0
            def current(): return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            def selection(): return frame.locator('.story-selected').get_attribute('data-from')
            def at_top():
                clear(); listing.press('Home'); time.sleep(.1)
                assert scroll() == 0

            assert selected() == 0
            revision = frame.evaluate('matsugitWorkspace.state.revision')
            anchor = frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')
            assert frame.locator('.story-takeaway').count() == 26
            for mode in ('overview','walkthrough'):
                frame.locator(f'button[data-story-mode="{mode}"]').click()
                at_top()
                # No selection: both arrow axes and Vim keys scroll, not select.
                for down,up in [('ArrowDown','ArrowUp'),('ArrowRight','ArrowLeft'),('j','k'),('PageDown','PageUp')]:
                    before = scroll(); listing.press(down); time.sleep(.1)
                    assert scroll() > before, (mode,down,scroll())
                    assert selected() == 0
                    listing.press(up); time.sleep(.1)
                    assert scroll() <= before+1, (mode,up,scroll(),before)
                assert frame.evaluate('matsugitWorkspace.editor.state.selection.main.head') == anchor
                listing.press('End'); assert scroll() > 0 and selected() == 0
                listing.press('Home'); time.sleep(.1)
                listing.press('l'); time.sleep(.1)
                assert selected() == 0 and scroll() > 0
                box = listing.bounding_box()
                second = frame.locator('.story-section').nth(1).bounding_box()
                assert abs(second['y']-box['y']) < 35, (mode,second,box)
                listing.press('h'); time.sleep(.1)
                assert scroll() < 35 and selected() == 0
                # A row click selects. Ordinary scrolling must retain that selection.
                first = frame.locator('.story-slide').first
                first.locator('.story-marker').click()
                assert selected() == 1
                initial = selection()
                listing.evaluate('(el)=>el.scrollTop += 400')
                time.sleep(.15)
                assert selection() == initial
                first.press('ArrowDown')
                assert frame.locator('.story-selected .story-heading .story-title').inner_text() == 'Slide 2'
                frame.locator('.story-selected').press('ArrowLeft')
                assert selection() == initial
                frame.locator('.story-selected').press('j')
                assert frame.locator('.story-selected .story-heading .story-title').inner_text() == 'Slide 2'
                frame.locator('.story-selected').press('k'); assert selection() == initial
                frame.locator('.story-selected').press('Escape'); assert selected() == 0
                assert frame.evaluate('document.activeElement.id') == 'story-list'
                # Background and mode switches do not manufacture a selection.
                first.locator('.story-marker').click(); clear()
                other = 'walkthrough' if mode == 'overview' else 'overview'
                frame.locator(f'button[data-story-mode="{other}"]').click(); assert selected() == 0
                frame.locator(f'button[data-story-mode="{mode}"]').click(); assert selected() == 0
                assert current() == source
                assert frame.evaluate('matsugitWorkspace.state.revision') == revision
                anchor = frame.evaluate('matsugitWorkspace.editor.state.selection.main.head')

            frame.locator('button[data-story-mode="overview"]').click()
            at_top()
            # Title editing, forms, and modifier shortcuts are never speed keys.
            frame.locator('.story-slide .story-heading .story-title').first.click()
            field = frame.get_by_role('textbox',name='Edit slide title')
            field.fill(''); field.press_sequentially('hjkl'); field.press('ArrowLeft'); field.press('ArrowRight')
            assert field.input_value() == 'hjkl'
            field.press('Escape'); assert selected() == 1
            frame.locator('.story-selected').press('Escape'); assert selected() == 0
            frame.locator('#undo').click()
            wait(frame,'matsugitWorkspace.editor.state.doc.toString().includes("## Slide 1\\n")')
            frame.locator('#story-add-slide').click()
            title = frame.locator('#story-new-slide-title')
            title.fill('hjkl'); title.press('ArrowLeft'); assert title.input_value() == 'hjkl'
            frame.locator('#story-new-close').click()
            # Single-line takeaway edits are real source transactions and preserve fences.
            frame.locator('.story-takeaway .story-title').first.click()
            field = frame.get_by_role('textbox',name='Edit takeaway')
            field.fill('A different decision'); field.press('Enter')
            assert '::: takeaway\nA different decision\n:::' in current()
            frame.locator('.story-selected').press('Alt+ArrowDown')
            assert frame.locator('.story-slide').nth(1).locator('.story-takeaway').inner_text().endswith('A different decision')
            frame.locator('#undo').click(); frame.locator('#undo').click()
            wait(frame,'matsugitWorkspace.editor.state.doc.toString().includes("::: takeaway\\nKeep the decision visible\\n:::")')
            frame.locator('.story-takeaway .story-title').nth(24).click()
            field = frame.get_by_role('textbox',name='Edit takeaway')
            field.fill('The next step stays small'); field.press('Enter')
            assert '> [!TAKEAWAY]\n> The next step stays small' in current()
            frame.locator('#undo').click()
            # Multi-paragraph takeaways are visible and open the precise source location.
            frame.locator('.story-takeaway .story-title').last.click()
            assert frame.locator('#editor').is_visible()
            assert frame.evaluate('matsugitWorkspace.editor.state.doc.sliceString(matsugitWorkspace.editor.state.selection.main.head).startsWith("::: takeaway\\nOne line")')
            assert Path(ready['source']).read_text() == source
            frame.locator('button[data-layout="story"]').click()
            for mode in ('overview','walkthrough'):
                frame.locator(f'button[data-story-mode="{mode}"]').click()
                for width in (390,800,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    time.sleep(.1)
                    assert not frame.locator('.story-slide').evaluate_all('(rows)=>rows.some(r=>r.scrollHeight>r.clientHeight+2 || r.scrollWidth>r.clientWidth+2)'), (mode,width)
            assert not errors, errors
            print('PASS: scroll/selection separation, arrows/jk/hl/pages, deselection, editing guards, takeaway display/edit/move/source, no saves')
            browser.close()
    finally:
        host.terminate(); host.wait(timeout=20)
