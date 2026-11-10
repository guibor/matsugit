"""Real plugin UI: the author types (with autosave) while another writer edits the same file."""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=30):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + '\n' + frame.locator('#save-state').inner_text() + ' | ' + frame.locator('#notice').inner_text()
                         + '\n' + frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')[-400:])


TEXT = 'matsugitWorkspace.editor.state.doc.toString()'
SAVED = 'document.getElementById("save-state").textContent.trim() === "Saved to file" && !matsugitWorkspace.state.merging'
host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                        env=dict(os.environ, MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_HOST=os.environ.get('MATSUGIT_TEST_HOST', ''),
                                 MATSUGIT_TEST_OPEN_OPTIONS='{"autosave":true,"editor":"raw"}'), stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    source = Path(ready['source'])
    original = source.read_text()
    assert original.endswith('\n')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading')
        frame.locator('#auto').uncheck()

        def cursor_to_end():
            frame.evaluate('(() => { const e = matsugitWorkspace.editor; e.dispatch({selection: {anchor: e.state.doc.length}}); e.focus(); })()')

        def typed(text):
            page.keyboard.type(text, delay=15)

        # 1. A targeted agent edit elsewhere in the file while the author keeps typing.
        cursor_to_end()
        typed('Author line one.')
        wait(frame, SAVED, 10)
        first_line = original.split('\n', 1)[0]
        agent = source.read_text()
        source.write_text(agent.replace(first_line, first_line + '\n<!-- agent note one -->', 1))
        typed(' Still typing.')
        wait(frame, TEXT + '.includes("agent note one") && ' + SAVED, 15)
        text = frame.evaluate(TEXT)
        assert text.endswith('Author line one. Still typing.'), text[-120:]
        assert frame.evaluate('matsugitWorkspace.editor.hasFocus')
        # The cursor stayed with the author's sentence: more typing lands there.
        typed(' And more.')
        wait(frame, SAVED, 10)
        assert source.read_text().endswith('Author line one. Still typing. And more.')
        assert 'agent note one' in source.read_text()
        assert not frame.evaluate('matsugitWorkspace.state.conflict')

        # Undo takes back the author's typing, never the accepted agent change.
        typed(' UNDO-ME')
        page.keyboard.press('ControlOrMeta+z')
        assert 'UNDO-ME' not in frame.evaluate(TEXT)
        frame.evaluate('for (let i=0;i<40;i++) document.getElementById("undo").click()')
        assert 'agent note one' in frame.evaluate(TEXT)
        frame.evaluate('for (let i=0;i<60;i++) document.getElementById("redo").click()')
        wait(frame, TEXT + '.includes("And more.")', 5)
        wait(frame, SAVED, 15)

        # A stale whole-file rewrite could also be an intentional deletion. Keep
        # both versions unchanged until the author explicitly accepts a proposal.
        stale = source.read_text()
        cursor_to_end()
        typed('\n\nAuthor paragraph typed after the agent read the file.')
        wait(frame, SAVED, 10)
        assert 'typed after the agent read' in source.read_text()
        source.write_text(stale.replace('agent note one', 'agent note one, revised'))
        wait(frame, 'matsugitWorkspace.state.conflict && !matsugitWorkspace.state.merging', 15)
        page.wait_for_timeout(2200)
        assert 'typed after the agent read the file.' in frame.evaluate(TEXT)
        assert source.read_text() == stale.replace('agent note one', 'agent note one, revised')
        frame.locator('#reload').click()
        frame.locator('#merge-dialog').wait_for(state='visible')
        assert 'typed after the agent read the file.' in frame.locator('#merge-complete').input_value()
        frame.locator('#merge-apply').click()
        wait(frame, '!document.getElementById("merge-dialog").open && ' + SAVED, 15)
        for content in (frame.evaluate(TEXT), source.read_text()):
            assert 'typed after the agent read the file.' in content and 'agent note one, revised' in content, content[-300:]
        assert not frame.evaluate('matsugitWorkspace.state.conflict')

        # A same-line edit AFTER autosave must not be silently loaded on a tie.
        before = source.read_text()
        assert 'And more.' in before
        frame.evaluate('''(() => { const e = matsugitWorkspace.editor, at = e.state.doc.toString().indexOf('And more.');
          e.dispatch({changes: {from: at, to: at + 9, insert: 'Author wording.'}}); })()''')
        wait(frame, SAVED, 10)
        source.write_text(before.replace('And more.', 'Agent wording.'))
        wait(frame, 'matsugitWorkspace.state.conflict', 15)
        page.wait_for_timeout(2500)
        assert source.read_text() == before.replace('And more.', 'Agent wording.')
        assert 'Author wording.' in frame.evaluate(TEXT)
        assert frame.locator('#save-state').inner_text().strip() == 'Changed elsewhere'
        assert frame.locator('#reload').is_visible()
        frame.locator('#reload').click()
        frame.locator('#merge-dialog').wait_for(state='visible')
        assert frame.locator('#merge-apply').is_disabled()
        assert 'Author wording.' in frame.locator('#merge-local').input_value()
        assert 'Agent wording.' in frame.locator('#merge-incoming').input_value()
        frame.locator('#merge-mine').click()
        frame.locator('#merge-apply').click()
        wait(frame, '!document.getElementById("merge-dialog").open && ' + SAVED, 15)
        assert 'Author wording.' in source.read_text()

        # Accepting a targeted external edit must not erase the historical bases
        # needed to protect a later stale writer. This also covers intentional
        # deletion: it must be offered for review, not automatically put back.
        stale = source.read_text()
        cursor_to_end()
        typed('\n\nKEEP-AFTER-EXTERNAL-UPDATE')
        wait(frame, SAVED, 10)
        source.write_text(source.read_text().replace('agent note one', 'agent targeted two'))
        wait(frame, TEXT + '.includes("agent targeted two") && ' + SAVED, 15)
        stale_incoming = stale.replace('agent note one', 'agent stale three')
        source.write_text(stale_incoming)
        wait(frame, 'matsugitWorkspace.state.conflict', 15)
        page.wait_for_timeout(2200)
        assert 'KEEP-AFTER-EXTERNAL-UPDATE' in frame.evaluate(TEXT)
        assert source.read_text() == stale_incoming
        assert not errors, errors
        print('PASS: targeted edit and undo, stale rewrite review, post-autosave conflict, history survives external update', flush=True)
        browser.close()
finally:
    host.terminate()
    host.wait(timeout=20)
