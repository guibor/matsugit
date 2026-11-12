"""The browser fallback: `matsugit open` serves the same workspace in a normal tab.

Runs the real CLI in the background mode an agent uses, then edits, saves, takes
an outside (agent) edit, and checks that the address is private and that the
server stops by itself after the tab closes.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if frame.evaluate(expression):
            return
        time.sleep(0.2)
    state = frame.evaluate('JSON.stringify((({session, uri, loading, saving, merging, refreshing, conflict, etag}) => ({session, uri, loading, saving, merging, refreshing, conflict, etag}))(matsugitWorkspace.state))')
    raise AssertionError(expression + '\n' + state + '\n' + frame.locator('#notice-text').inner_text())


def status(url, method='GET', headers=None, data=None):
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        return urllib.request.urlopen(request, timeout=10).status
    except urllib.error.HTTPError as error:
        return error.code


with tempfile.TemporaryDirectory() as directory:
    deck = Path(directory) / 'pilot.md'
    deck.write_text('---\ntitle: Pilot\nslide-layout: structured\n---\n\n## First slide\n### A claim\n\nSome text.\n')
    env = dict(os.environ, MATSUGIT_BROWSER_IDLE_MS='4000', MATSUGIT_RECOVERY_DIR=str(Path(directory) / 'recovery'),
               MATSUGIT_CONFIG=str(Path(directory) / 'absent.json'))
    opened = subprocess.run([sys.executable, '-m', 'matsugit', 'open', str(deck), '--no-browser', '--json'],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
    assert opened.returncode == 0, opened.stderr
    info = json.loads(opened.stdout)
    url = info['url']
    assert url.startswith('http://127.0.0.1:') and info['path'] == str(deck.resolve())
    base = url.rsplit('/', 2)[0] + '/'

    # Private: no token, a wrong token, another host name or another origin get nothing.
    assert status(base) == 404
    assert status(base + 'x' * 32 + '/') == 404
    assert status(url, headers={'Host': 'attacker.example'}) == 403
    assert status(url + 'rpc', 'POST', {'Origin': 'http://attacker.example', 'Content-Type': 'application/json'}, b'{}') == 403
    assert status(url + 'rpc', 'POST', {'Content-Type': 'text/plain'}, b'{}') == 415

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        assert page.title() == 'pilot.md · matsugit'
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered && !matsugitWorkspace.state.rendering')
        assert frame.evaluate('matsugitWorkspace.state.layout') == 'split'
        assert frame.locator('#check-label').inner_text() == 'No problems'

        # Edit and save: the file on disk changes only on Save.
        frame.evaluate('''() => { const e = matsugitWorkspace.editor, at = e.state.doc.toString().indexOf('Some text.');
          e.dispatch({changes: {from: at, to: at + 10, insert: 'Edited in the browser.'}}); }''')
        assert 'Some text.' in deck.read_text()
        frame.locator('#save').click()
        end = time.time() + 20
        while 'Edited in the browser.' not in deck.read_text() and time.time() < end:
            time.sleep(0.2)
        assert 'Edited in the browser.' in deck.read_text()

        # An agent edits the file on disk: the open tab takes it in.
        time.sleep(1)
        deck.write_text(deck.read_text().replace('### A claim', '### A claim the agent sharpened'))
        wait(frame, 'matsugitWorkspace.editor.state.doc.toString().includes("the agent sharpened")', 30)

        page.screenshot(path=str(Path(tempfile.gettempdir()) / 'matsugit-browser-fallback.png'))
        assert not errors, errors
        browser.close()

    # The tab is gone: the server stops by itself.
    def alive():
        try:
            urllib.request.urlopen(url, timeout=2)
        except urllib.error.HTTPError:
            return True
        except OSError:
            return False
        return True
    end = time.time() + 30
    while alive() and time.time() < end:
        time.sleep(1)
    assert not alive(), 'The browser server kept running after the tab closed'

print('PASS: matsugit open serves the workspace privately in a browser tab, saves, takes agent edits and stops when closed')
