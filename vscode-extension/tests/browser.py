"""Real VS Code smoke test. Requires Playwright, Xvfb and VSCODE_EXECUTABLE.

Uses an isolated profile, synthetic source and the test-only host.cjs bridge.
No real editors, settings, Git remotes or accounts are touched.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RUN = Path(tempfile.mkdtemp(prefix='matsugit-vscode-smoke-'))
print('Test artifacts:', RUN, flush=True)
shutil.copyfile(ROOT / 'tests/fixture.md', RUN / 'deck.md')
(RUN / 'config.json').write_text('{"theme":"default"}')
env = dict(os.environ, MATSUGIT_VSCODE_TEST=str(RUN), MATSUGIT_CONFIG=str(RUN / 'config.json'),
           MATSUGIT_RECOVERY_DIR=str(RUN / 'recovery'), MATSUGIT_PUBLICATION_STATE=str(RUN / 'publication'))
serial = 0

def wait(check, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError('VS Code exited early; inspect ' + str(RUN / 'vscode.log'))
        try:
            value = check()
            if value:
                return value
        except Exception:
            pass
        time.sleep(.2)
    raise AssertionError('Timed out: ' + str(check))

def command(action, **args):
    global serial
    serial += 1
    (RUN / 'command.json').write_text(json.dumps(dict(id=serial, action=action, **args)))
    response = wait(lambda: (RUN / 'response.json').exists()
                    and (value := json.loads((RUN / 'response.json').read_text()))['id'] == serial and value)
    assert not response.get('error'), response
    return response

log = (RUN / 'vscode.log').open('w')
process = subprocess.Popen(['xvfb-run', '-a', os.environ['VSCODE_EXECUTABLE'], '--no-sandbox',
    '--disable-gpu', '--remote-debugging-port=9339', '--skip-welcome', '--skip-release-notes',
    '--disable-workspace-trust', '--disable-extensions', '--disable-updates',
    '--user-data-dir=' + str(RUN / 'user-data'), '--extensions-dir=' + str(RUN / 'extensions'),
    '--extensionDevelopmentPath=' + str(ROOT), '--extensionTestsPath=' + str(ROOT / 'tests/host.cjs'),
    str(RUN)], env=env, stdout=log, stderr=subprocess.STDOUT)
try:
    wait(lambda: (RUN / 'ready').exists())
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9339')
        page = browser.contexts[0].pages[0]
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        frame = wait(lambda: next((f for f in page.frames if f.evaluate('!!window.matsugitWorkspace')), None))
        wait(lambda: frame.evaluate('!!matsugitWorkspace.state.rendered.slides'), 180)
        wait(lambda: frame.locator('#preview').element_handle().content_frame().locator('.reveal.ready').count(), 120)
        page.screenshot(path=str(RUN / 'split-slides.png'))
        print('Native editor and slide preview loaded', flush=True)
        original = (RUN / 'deck.md').read_text()
        assert command('read')['source'] == original
        assert frame.evaluate('matsugitWorkspace.state.editorMode') == 'visual'
        frame.evaluate('''() => {
          const w=matsugitWorkspace, at=w.editor.state.doc.toString().indexOf('Make waiting optional');
          w.editor.dispatch({changes:{from:at,to:at+21,insert:'Make commuting simpler'}});
        }''')
        wait(lambda: 'Make commuting simpler' in command('read')['source'])
        assert command('read')['dirty']
        assert (RUN / 'deck.md').read_text() == original
        assert frame.evaluate('matsugitWorkspace.save()')
        wait(lambda: not command('read')['dirty'])
        assert 'Make commuting simpler' in (RUN / 'deck.md').read_text()
        print('Visual edit, native dirty state and explicit Save verified', flush=True)
        command('replace', before='Keep the baseline visible.', after='Keep the baseline measurable.')
        wait(lambda: frame.evaluate('!!matsugitWorkspace.state.incomingReady'))
        frame.locator('#accept-update').click()
        wait(lambda: frame.evaluate('matsugitWorkspace.editor.state.doc.toString().includes("baseline measurable")'))
        assert not frame.evaluate('matsugitWorkspace.state.conflict')
        assert frame.evaluate('matsugitWorkspace.save()')
        print('Edits from another native buffer are reflected and saved', flush=True)
        frame.locator('[data-editor="raw"]').click()
        frame.evaluate('''() => {
          const w=matsugitWorkspace, at=w.editor.state.doc.toString().indexOf('baseline measurable');
          w.editor.dispatch({selection:{anchor:at,head:at+19}});w.editor.focus();
        }''')
        page.keyboard.type('baseline clear')
        wait(lambda: 'baseline clear' in command('read')['source'])
        page.keyboard.press('Control+z')
        wait(lambda: 'baseline measurable' in command('read')['source'])
        assert 'Make commuting simpler' in command('read')['source']
        command('save')
        wait(lambda: not frame.evaluate('matsugitNativeDocument.dirty'))
        frame.locator('[data-editor="visual"]').click()
        print('Real keyboard input, Undo and native Save verified', flush=True)
        frame.evaluate('''() => { const w=matsugitWorkspace,at=w.editor.state.doc.toString().indexOf('Make commuting simpler');
          w.editor.dispatch({changes:{from:at,to:at+22,insert:'Make the local draft clear'}}); }''')
        wait(lambda: 'Make the local draft clear' in command('read')['source'])
        command('replace', before='baseline measurable', after='baseline updated')
        wait(lambda: frame.evaluate('!!matsugitWorkspace.state.incomingReady'))
        frame.locator('#accept-update').click()
        wait(lambda: frame.evaluate('matsugitWorkspace.editor.state.doc.toString().includes("baseline updated")'))
        assert 'Make the local draft clear' in command('read')['source']
        assert not frame.evaluate('matsugitWorkspace.state.conflict')
        assert frame.evaluate('matsugitWorkspace.save()')
        frame.evaluate('''() => { const w=matsugitWorkspace,at=w.editor.state.doc.toString().indexOf('Make the local draft clear');
          w.editor.dispatch({changes:{from:at,to:at+26,insert:'Author chooses this'}}); }''')
        wait(lambda: 'Author chooses this' in command('read')['source'])
        command('replace', before='Author chooses this', after='Other editor chooses that')
        wait(lambda: frame.evaluate('!!matsugitWorkspace.state.incomingReady'))
        frame.locator('#accept-update').click()
        wait(lambda: frame.evaluate('matsugitWorkspace.state.conflict'))
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString().includes("Author chooses this")')
        assert not frame.evaluate('matsugitWorkspace.save({review:false})')
        assert 'Other editor chooses that' in command('read')['source']
        assert 'Author chooses this' not in (RUN / 'deck.md').read_text()
        frame.locator('#merge-file').click()
        frame.locator('#merge-apply').click()
        wait(lambda: not frame.evaluate('matsugitWorkspace.state.conflict'))
        wait(lambda: not frame.locator('#merge-dialog').evaluate('(d)=>d.open'))
        wait(lambda: not command('read')['dirty'])
        assert 'Other editor chooses that' in (RUN / 'deck.md').read_text()
        print('Separate changes combine; overlapping changes retain both drafts until review', flush=True)
        frame.locator('[data-layout="story"]').click()
        wait(lambda: frame.locator('.story-row').count() > 0)
        page.screenshot(path=str(RUN / 'story.png'))
        frame.locator('[data-layout="split"]').click()
        frame.locator('[data-format="document"]').click()
        wait(lambda: frame.evaluate('!!matsugitWorkspace.state.rendered.document'), 180)
        wait(lambda: frame.locator('#preview').element_handle().content_frame().locator('h1').count(), 120)
        page.screenshot(path=str(RUN / 'split-document.png'))
        assert not errors, errors
        print('Story and document views verified', flush=True)
        browser.close()
finally:
    (RUN / 'command.json').write_text(json.dumps({'id': serial + 1, 'action': 'finish'}))
    try:
        process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)
    log.close()
