"""Real plugin UI when the file or the plugin misbehaves under an open workspace.

- The plugin restarts: the workspace reconnects to the same file and saves.
- The file is made read-only: it is not overwritten; saving resumes once writable.
- The file is deleted: the text stays, and "Save it there again" restores it.
- The file is moved: nothing is written to the new place; the old place can be restored.
- Two windows edit the same file: both sets of typing end up in it.
"""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression + ' | ' + frame.locator('#notice').inner_text() + ' | ' + frame.locator('#save-state').inner_text())


def session(autosave, body):
    env = dict(os.environ, MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_HOST=os.environ.get('MATSUGIT_TEST_HOST', ''),
               MATSUGIT_TEST_OPEN_OPTIONS=json.dumps({'autosave': autosave}))
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], env=env, stdout=subprocess.PIPE, text=True)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            errors = []

            def open_page():
                page = browser.new_page(viewport={'width': 1200, 'height': 800})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{ready["port"]}')
                frame = page.frames[1]
                wait(frame, '!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading')
                frame.locator('#auto').uncheck()
                return page, frame
            body(Path(ready['source']), open_page)
            assert not errors, errors
            browser.close()
    finally:
        host.terminate()
        host.wait(timeout=20)


def type_at_end(page, frame, words):
    frame.evaluate('(() => { const e = matsugitWorkspace.editor; e.dispatch({selection: {anchor: e.state.doc.length}}); e.focus(); })()')
    page.keyboard.type(words, delay=4)


SAVED = 'document.getElementById("save-state").textContent.trim() === "Saved to file" && !matsugitWorkspace.state.saving'


def restart(source, open_page):
    page, frame = open_page()
    type_at_end(page, frame, '\nTyped before the plugin restarted.')
    page.evaluate('fetch("/restart", {method: "POST"})')
    page.wait_for_timeout(1500)
    type_at_end(page, frame, '\nTyped after the restart.')
    frame.locator('#save').click()
    wait(frame, SAVED)
    text = source.read_text()
    assert 'before the plugin restarted' in text and 'after the restart' in text
    assert 'Workspace expired' not in frame.locator('#notice').inner_text()
    assert frame.locator('#recovery-status').inner_text() != 'Draft backup unavailable'


def read_only(source, open_page):
    page, frame = open_page()
    original = source.read_text()
    source.chmod(0o444)
    try:
        type_at_end(page, frame, '\nTyped into a read-only file.')
        wait(frame, 'document.getElementById("save-state").textContent.includes("Read-only") || /read-only on disk/.test(document.getElementById("notice-text").textContent)', 10)
        assert source.read_text() == original, 'a read-only file was overwritten'
        assert 'read-only file' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
    finally:
        source.chmod(0o644)
    # Autosave picks up again once the file is writable.
    wait(frame, SAVED, 15)
    assert source.read_text().endswith('Typed into a read-only file.')


def deleted(source, open_page):
    page, frame = open_page()
    type_at_end(page, frame, '\nSaved before the file vanished.')
    frame.locator('#save').click(); wait(frame, SAVED)
    source.unlink()
    wait(frame, '!document.getElementById("notice-recreate").hidden', 10)
    assert 'Your text is safe' in frame.locator('#notice-text').inner_text()
    assert 'ENOENT' not in frame.locator('#notice').inner_text()
    type_at_end(page, frame, '\nTyped after it vanished.')
    frame.locator('#notice-recreate').click()
    wait(frame, '!matsugitWorkspace.state.saving && matsugitWorkspace.editor.state.doc.toString() === matsugitWorkspace.state.base', 10)
    assert source.read_text().endswith('Typed after it vanished.')
    # Back to normal: the next edit saves to the same place.
    type_at_end(page, frame, '\nAnd normal saving resumes.')
    frame.locator('#save').click(); wait(frame, SAVED)
    assert source.read_text().endswith('And normal saving resumes.')


def moved(source, open_page):
    page, frame = open_page()
    elsewhere = source.with_name('renamed.md')
    source.rename(elsewhere)
    moved_text = elsewhere.read_text()
    wait(frame, '!document.getElementById("notice-recreate").hidden', 10)
    type_at_end(page, frame, '\nTyped after the move.')
    frame.locator('#save').click()
    page.wait_for_timeout(1500)
    assert elsewhere.read_text() == moved_text, 'the moved file was changed'
    assert not source.exists()
    assert 'after the move' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
    # Something new appears at the old place: "Save it there again" must not replace it.
    source.write_text('Somebody else put a file here.\n')
    frame.locator('#notice-recreate').click()
    page.wait_for_timeout(1500)
    assert source.read_text() == 'Somebody else put a file here.\n'


def two_windows(source, open_page):
    first_page, first = open_page()
    second_page, second = open_page()
    # Separate places in the file; typing at the same place is a real conflict.
    def type_after_title(page, frame, words):
        frame.evaluate('''(() => { const e = matsugitWorkspace.editor, t = e.state.doc.toString(), at = t.indexOf('\\n', t.indexOf('\\n# ') + 1);
          e.dispatch({selection: {anchor: at}}); e.focus(); })()''')
        page.keyboard.type(words, delay=4)
    for round_ in range(3):
        type_at_end(first_page, first, f'\nFirst window line {round_}.')
        type_after_title(second_page, second, f'\nSecond window line {round_}.')
        second_page.wait_for_timeout(700)
    for frame in (first, second):
        frame.evaluate('matsugitWorkspace.reload()')
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        text = source.read_text()
        if all(f'{name} window line {n}' in text for name in ('First', 'Second') for n in range(3)) \
                and all(frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == text for frame in (first, second)):
            break
        for frame in (first, second):
            if frame.evaluate('matsugitWorkspace.state.conflict'):
                raise AssertionError('two windows typing on separate lines needed a review')
        time.sleep(.5)
    else:
        raise AssertionError('the two windows did not converge: ' + repr(source.read_text()[-400:]))


if __name__ == '__main__':
    session(False, restart)
    session(True, restart)
    session(True, read_only)
    session(False, deleted)
    session(True, moved)
    session(True, two_windows)
    print('PASS: plugin restart, read-only file, deleted file, moved file, two windows', flush=True)
