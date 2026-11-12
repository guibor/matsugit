"""Real plugin UI on a first run.

- Opened from the app launcher (no file): the guided sample deck appears as
  slides beside formatted text, not an empty template, and editing its first
  title updates the slide.
- On a computer without Quarto: the workspace says what to install. It is not
  shown as a problem in the deck: Check stays clear and there is no
  "Show problems" button.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', tempfile.mkdtemp(prefix='matsugit-onboarding-')))
shots.mkdir(parents=True, exist_ok=True)


def wait(frame, expression, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if frame.evaluate(expression):
            return
        time.sleep(.15)
    raise AssertionError(expression + '\n' + frame.locator('#notice').inner_text())


def session(extra_env, query, body):
    env = dict(os.environ, **extra_env)
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], env=env, stdout=subprocess.PIPE, text=True)
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}{query}')
            body(page, page.frames[1])
            assert not errors, errors
            browser.close()
    finally:
        host.terminate()
        host.wait(timeout=20)


def launcher(page, frame):
    wait(frame, '!!window.matsugitWorkspace?.state.rendered?.slides && !matsugitWorkspace.state.rendering')
    text = frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
    assert 'Change this title and watch the slide' in text
    assert frame.evaluate('matsugitWorkspace.state.format') == 'slides'
    assert frame.evaluate('matsugitWorkspace.state.layout') == 'split'
    assert frame.locator('#check-label').inner_text() == 'No problems'
    # A scratch copy says so, and how to get one that is kept.
    assert 'scratch copy' in frame.locator('#notice-text').inner_text()
    assert 'Show me how matsugit works' in frame.locator('#notice-text').inner_text()
    # The storyline strip already shows the whole sample.
    assert frame.locator('.rail-slide').count() == 7
    page.screenshot(path=str(shots / 'first-run-launcher.png'))
    # The first instruction works: edit the title, the slide follows.
    frame.evaluate('''(() => { const e = matsugitWorkspace.editor, t = e.state.doc.toString(), at = t.indexOf('Change this title and watch the slide');
      e.dispatch({changes: {from: at, to: at + 'Change this title and watch the slide'.length, insert: 'My first matsugit slide'}}); })()''')
    preview = lambda: frame.locator('#preview').element_handle().content_frame()
    wait(frame, '!matsugitWorkspace.state.rendering && matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision', 60)
    deadline = time.monotonic() + 30
    while 'My first matsugit slide' not in preview().locator('body').inner_text() and time.monotonic() < deadline:
        time.sleep(.3)
    assert 'My first matsugit slide' in preview().locator('body').inner_text()


def no_quarto(page, frame):
    wait(frame, '!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading')
    wait(frame, '!matsugitWorkspace.state.rendering && /Quarto/.test(document.getElementById("notice-text").textContent)', 60)
    notice = frame.locator('#notice-text').inner_text()
    assert 'Slides need Quarto' in notice and 'brew install --cask quarto' in notice and 'ask the agent' in notice, notice
    assert 'Executable not found' not in notice
    assert frame.locator('#notice-check').is_hidden()
    assert frame.locator('#check-label').inner_text() == 'No problems'
    assert frame.locator('#empty-label').inner_text() == 'Needs Quarto'
    # Check has no setup finding, so opening it must not hide the only guidance.
    frame.locator('#check-status').click()
    assert frame.locator('#notice').is_visible()
    assert 'Slides need Quarto' in frame.locator('#notice-text').inner_text()
    frame.locator('#check-close').click()
    page.screenshot(path=str(shots / 'first-run-no-quarto.png'))


if __name__ == '__main__':
    session({'MATSUGIT_TEST_OPEN_OPTIONS': '{}'}, '?untitled', launcher)
    session({'QUARTO': '/nonexistent/quarto', 'MATSUGIT_SHOWCASE_SOURCE': str(ROOT / 'matsugit/templates/tour.md'),
             'MATSUGIT_TEST_OPEN_OPTIONS': json.dumps({'layout': 'split', 'format': 'slides', 'editor': 'visual'})}, '', no_quarto)
    print(f'PASS: launcher opens the guided sample, its first instruction works, missing Quarto is setup guidance; screenshots {shots}', flush=True)
