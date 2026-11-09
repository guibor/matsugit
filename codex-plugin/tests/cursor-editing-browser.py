"""Exercise Cursor-style inline sizing and prompt-mutating context updates."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


with tempfile.TemporaryDirectory(prefix='matsugit-cursor-editing-') as temporary:
    env = dict(os.environ, HOME=temporary, XDG_CONFIG_HOME=temporary + '/config',
               MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_HOST='cursor',
               MATSUGIT_TEST_RESULT='summary',
               MATSUGIT_TEST_OPEN_OPTIONS='{"layout":"split","format":"slides","editor":"visual"}')
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                            env=env, text=True, stdout=subprocess.PIPE)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 840, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            deadline = time.monotonic() + 30
            while not frame.evaluate('!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading'):
                if time.monotonic() > deadline:
                    raise AssertionError(frame.locator('body').inner_text())
                page.wait_for_timeout(100)
            frame.locator('#auto').uncheck()
            for mode in ('raw', 'visual'):
                frame.locator(f'[data-editor={mode}]').click()
                frame.evaluate('''()=>{const e=matsugitWorkspace.editor;
                  e.dispatch({selection:{anchor:e.state.doc.length}});e.focus();}''')
                phrase = f'\nTyping stays in the {mode} editor.'
                page.keyboard.type(phrase, delay=25)
                assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()').endswith(phrase)
                assert frame.evaluate('matsugitWorkspace.editor.hasFocus')
                assert page.locator('#chat-prompt').input_value() == ''
            assert page.evaluate('contextUpdates') == 0
            assert 700 <= frame.locator('#app').bounding_box()['height'] <= 800
            frame.locator('[data-layout=story]').click()
            frame.locator('.story-slide .story-title').first.click()
            title = frame.locator('.story-edit')
            title.press('ControlOrMeta+A')
            page.keyboard.type('A clearer automotive story', delay=25)
            assert title.input_value() == 'A clearer automotive story'
            assert title.evaluate('(element) => element === document.activeElement')
            title.press('Enter')
            assert page.evaluate('contextUpdates') == 0
            frame.locator('[data-layout=split]').click()
            for width in (840, 600, 390):
                page.set_viewport_size({'width': width, 'height': 1000})
                page.wait_for_timeout(150)
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert frame.locator('#editor').bounding_box()['height'] >= 150
            assert page.evaluate('displayRequests') == []
            assert frame.locator('#workspace-version').inner_text() == json.loads(
                (ROOT / 'codex-plugin/package.json').read_text())['version']
            assert not errors, errors
            artifacts = os.environ.get('MATSUGIT_TEST_ARTIFACTS')
            if artifacts:
                Path(artifacts).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(artifacts) / 'cursor-inline-narrow.png'))
                page.set_viewport_size({'width': 1000, 'height': 1000})
                page.wait_for_timeout(200)
                page.screenshot(path=str(Path(artifacts) / 'cursor-inline-wide.png'))
            browser.close()
        print('PASS: Cursor inline sizing, Raw/Visual/Story typing, prompt isolation and running version')
    finally:
        host.terminate()
        try:
            host.wait(timeout=15)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
