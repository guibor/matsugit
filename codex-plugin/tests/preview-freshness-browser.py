"""A narrow Reveal scroll view must not restore pre-edit bullets when widened."""
import json
import os
from pathlib import Path
import runpy
import tempfile

helpers = runpy.run_path(str(Path(__file__).with_name('onboarding-browser.py')))
original = ('## Delivery choices\n\n:::: comparison\n#### Pickup\n- Original pickup.\n\n'
            '#### Delivery\n- Original delivery.\n::::\n')


def exercise(page, frame):
    page.set_viewport_size({'width': 800, 'height': 860})
    banner = frame.locator('#preview-stale')
    def settled():
        helpers['wait'](frame, """window.matsugitWorkspace?.state.rendered &&
            matsugitWorkspace.state.revision===matsugitWorkspace.state.renderedRevision &&
            !matsugitWorkspace.state.rendering && document.getElementById('preview-stale').hidden""")
    def preview():
        return frame.locator('#preview').element_handle().content_frame()
    def expect_bullets(values):
        assert preview().locator('.ff-comparison li').all_text_contents() == values
    def write(source):
        frame.evaluate("""s=>{const e=matsugitWorkspace.editor;
            e.dispatch({changes:{from:0,to:e.state.doc.length,insert:s}})}""",source)
    def capture(name):
        if folder := os.environ.get('MATSUGIT_SCREENSHOTS'):
            Path(folder).mkdir(exist_ok=True, parents=True)
            page.screenshot(path=str(Path(folder)/(name+'.png')))
    settled()
    assert preview().evaluate('Reveal.isScrollView()')
    expect_bullets(['Original pickup.', 'Original delivery.'])
    frame.locator('#auto').uncheck()
    edited = original.replace('Original pickup.', 'Collect at the counter.').replace(
        'Original delivery.', 'Choose a delivery window.')
    write(edited)
    assert banner.is_visible() and 'off' in banner.inner_text()
    assert frame.locator('#check-label').inner_text() == 'Check draft'
    capture('paused')
    frame.get_by_role('button', name='Update preview', exact=True).click()
    settled()
    assert frame.evaluate('matsugitWorkspace.state.lastRefresh.kind') == 'patch'
    expect_bullets(['Collect at the counter.', 'Choose a delivery window.'])
    frame.locator('button[data-layout="render"]').click()
    helpers['wait'](preview(), '!Reveal.isScrollView()')
    expect_bullets(['Collect at the counter.', 'Choose a delivery window.'])
    capture('current')
    # Auto-update, a burst of edits and both format switches, without saving.
    frame.locator('#auto').check()
    write(edited.replace('counter', 'front desk'))
    write(edited.replace('counter', 'pickup desk'))
    assert banner.is_visible()
    frame.locator('button[data-format="document"]').click()
    settled()
    assert 'Collect at the pickup desk.' in preview().locator('main').inner_text()
    frame.locator('button[data-format="slides"]').click()
    settled()
    expect_bullets(['Collect at the pickup desk.', 'Choose a delivery window.'])
    disk = Path(frame.evaluate('matsugitWorkspace.state.path'))
    assert disk.read_text() == original


with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp)/'delivery.md'
    source.write_text(original)
    helpers['session']({'MATSUGIT_TEST_SOURCE':str(source),'MATSUGIT_TEST_OPEN_OPTIONS':
        json.dumps({'layout':'split','format':'slides','editor':'visual','autosave':False})}, '', exercise)
print('PASS: visible bullets survive resizing and format switches; paused preview updates without saving.')
