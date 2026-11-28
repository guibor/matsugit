"""Author's task: add a delivery option on the right, leaving pickup alone."""
import json
from pathlib import Path
import runpy
import tempfile

helpers = runpy.run_path(str(Path(__file__).with_name('onboarding-browser.py')))
original = ('## Delivery choices\n\n:::: comparison\n#### Pickup\n- Same day.\n\n'
            '#### Delivery\n- Same day.\n::::\n')
draft = 'matsugitWorkspace.editor.state.doc.toString()'
caret = 'matsugitWorkspace.editor.state.selection.main.head'


def exercise(page, frame):
    for width in (800, 1500):
        page.set_viewport_size({'width': width, 'height': 860})
        helpers['wait'](frame, 'window.matsugitWorkspace?.state.rendered && '
            '!matsugitWorkspace.state.rendering && document.getElementById("preview-stale").hidden')
        preview = frame.locator('#preview').element_handle().content_frame()
        right = preview.locator('.ff-comparison > .ff-region').nth(1)
        right.scroll_into_view_if_needed()
        box = right.bounding_box()
        right.click(position={'x': box['width']-6, 'y': box['height']/2})
        try:
            helpers['wait'](frame, f'{caret} === {original.rindex("Same day.")+9} && matsugitWorkspace.editor.hasFocus', 5)
        except AssertionError:
            print('Width, caret, column:', width, frame.evaluate(caret), right.evaluate('el=>el.outerHTML'))
            raise
        assert 'Same day.' in frame.locator('.ff-active-column').all_text_contents()[-1]
        page.keyboard.press('Enter')
        page.keyboard.insert_text('Evening delivery.')
        assert frame.evaluate(draft) == original.replace('day.\n::::','day.\n- Evening delivery.\n::::')
        pos = frame.evaluate(caret)
        for mode in ('raw','visual'):
            frame.locator(f'[data-editor="{mode}"]').click()
            assert frame.evaluate(caret) == pos
        frame.locator('#undo').click()
        assert frame.evaluate(draft) == original
        # Some first-time authors go straight to the visible Delivery bullet.
        bullet = frame.locator('.cm-line').filter(has_text='Same day.').last
        bullet.click()
        clicked = frame.evaluate(caret)
        page.keyboard.press('End')
        assert frame.evaluate(caret) == original.rindex('Same day.')+9, (width, clicked, frame.evaluate(caret))
        page.keyboard.press('Enter')
        page.keyboard.insert_text('Evening delivery.')
        assert frame.evaluate(draft) == original.replace('day.\n::::','day.\n- Evening delivery.\n::::'), frame.evaluate(draft)
        frame.locator('#undo').click()
        assert frame.evaluate(draft) == original
        assert Path(frame.evaluate('matsugitWorkspace.state.path')).read_text() == original
    # With live preview paused, clicking the old right column must not move
    # an author who is typing into the left one.
    frame.locator('#auto').uncheck()
    left = frame.locator('.cm-line').filter(has_text='Same day.').first
    left.click()
    page.keyboard.insert_text('Local')
    pos = frame.evaluate(caret)
    preview = frame.locator('#preview').element_handle().content_frame()
    right = preview.locator('.ff-comparison > .ff-region').nth(1)
    box = right.bounding_box()
    right.click(position={'x':box['width']-6,'y':box['height']/2})
    # The following message runs after the click's postMessage on the parent.
    frame.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert frame.evaluate(caret) == pos


with tempfile.TemporaryDirectory() as folder:
    source = Path(folder)/'delivery.md'
    source.write_text(original)
    helpers['session']({'MATSUGIT_TEST_SOURCE':str(source),'MATSUGIT_TEST_OPEN_OPTIONS':
        json.dumps({'layout':'split','format':'slides','editor':'visual','autosave':False})}, '', exercise)
print('PASS: right-column entry, append, mode switches and undo at narrow and wide widths.')
