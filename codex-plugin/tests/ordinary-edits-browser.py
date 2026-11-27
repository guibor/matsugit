"""Drive the three ordinary tasks without saving, using the actual editor controls."""
from pathlib import Path
import json
import os
import runpy
import tempfile

helpers = runpy.run_path(str(Path(__file__).with_name('onboarding-browser.py')))
session, wait = helpers['session'], helpers['wait']
original = ('## Recommendation {#decision}\n\nRun a small pilot.\n\n'
            '| Owner | Measure | Target |\n| --- | --- | --- |\n| | Reach | 10 |\n')


def exercise(page, frame):
    wait(frame, '!!window.matsugitWorkspace?.state.rendered')
    draft = lambda: frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
    disk = Path(frame.evaluate('matsugitWorkspace.state.path'))
    heading = frame.locator('.cm-line.ff-heading-2').first
    heading.click()
    frame.get_by_role('button', name='Rename heading', exact=True).click()
    page.keyboard.type('Proposed pilot',delay=20)
    assert draft().startswith('## Proposed pilot {#decision}\n')
    page.keyboard.press('F2')
    page.keyboard.insert_text('Recommendation')
    assert draft() == original
    for offset,key in [(3,'Backspace'),(3+len('Recommendation'),'Delete')]:
        frame.evaluate('p=>{const e=matsugitWorkspace.editor;e.dispatch({selection:{anchor:p}});e.focus()}',offset)
        page.keyboard.press(key)
        assert draft() == original
    modifier = 'Meta' if os.environ.get('MATSUGIT_TEST_MAC_KEYS') else 'Control'
    for mode, shortcut, marker in [('visual',modifier+'+b','**'),('raw',modifier+'+i','*')]:
        frame.locator('[data-editor="'+mode+'"]').click()
        frame.evaluate("""()=>{const e=matsugitWorkspace.editor, p=e.state.doc.toString().indexOf('small');
            e.dispatch({selection:{anchor:p,head:p+5},scrollIntoView:true});e.focus()}""")
        page.keyboard.press(shortcut)
        assert marker+'small'+marker in draft(), draft()
        page.keyboard.press(shortcut)
        assert draft() == original
    frame.locator('[data-editor="visual"]').click()
    cells = frame.locator('.ff-table-scroll td')
    assert cells.all_text_contents() == ['', 'Reach', '10']
    cells.nth(1).click()
    wait(frame, 'matsugitWorkspace.tables.rich?.isEditable && !document.getElementById("table-apply").disabled')
    assert frame.evaluate('matsugitWorkspace.tables.rich.state.selection.$from.parent.textContent') == 'Reach'
    page.keyboard.insert_text('Weekly ')
    page.keyboard.press(modifier+'+Enter')
    wait(frame, '!document.getElementById("table-dialog").open')
    assert 'Weekly Reach' in draft() and disk.read_text() == original
    frame.locator('#undo').click()
    assert draft() == original
    frame.locator('[data-layout="story"]').click()
    frame.locator('.story-slide .story-heading .story-title').first.click()
    title = frame.get_by_role('textbox',name='Edit slide title',exact=True)
    title.fill('')
    title.press_sequentially('A better plan',delay=20)
    title.press('Enter')
    assert '## A better plan {#decision}' in draft()
    frame.locator('#story-add-slide').click()
    frame.locator('#story-browse-types').click()
    frame.get_by_role('button',name='Compare options',exact=False).click()
    assert 'Compare options against the same criteria' in draft() and disk.read_text() == original


with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp)/'ordinary-edits.md'
    source.write_text(original)
    session({'MATSUGIT_SHOWCASE_SOURCE':str(source), 'MATSUGIT_TEST_OPEN_OPTIONS':
             json.dumps({'layout':'split','format':'document','editor':'visual'})}, '', exercise,
            init_script=("Object.defineProperty(navigator,'platform',{get:()=>'MacIntel'})"
                         if os.environ.get('MATSUGIT_TEST_MAC_KEYS') else None))
print('PASS: rename a linked heading, toggle keyboard formatting, edit the right table cell, undo, add a comparison; disk unchanged.')
