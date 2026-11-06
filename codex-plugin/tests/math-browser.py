"""Real plugin math with browser networking blocked; never edits a real deck."""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright, Error as BrowserError

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            target = frame() if callable(frame) else frame
            if target and target.evaluate(expression): return
        except BrowserError as error:
            if not any(reason in str(error) for reason in ('context was destroyed', 'detached')):
                raise
        time.sleep(.1)
    raise AssertionError(expression)


host = subprocess.Popen(['node', str(ROOT/'codex-plugin/tests/browser-host.mjs')],
    stdout=subprocess.PIPE, text=True, env=dict(os.environ,
    MATSUGIT_SHOWCASE_SOURCE=str(ROOT/'codex-plugin/tests/math.md'),
    QUARTO=os.environ.get('QUARTO', 'quarto')))
try:
    ready = json.loads(host.stdout.readline())
    source = Path(ready['source']); original = source.read_bytes()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        remote, errors, math_errors = [], [], []
        def request(route):
            if route.request.url.startswith(f'http://127.0.0.1:{ready["port"]}/'):
                route.continue_()
            else:
                remote.append(route.request.url); route.abort()
        page.route('http**://**', request)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: math_errors.append(m.text) if m.type=='error'
                and any(x in m.text.lower() for x in ['mathjax', 'math processing', 'content security']) else None)
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered?.document && !matsugitWorkspace.state.rendering')
        frame.locator('#auto').uncheck(); frame.locator('#sync').uncheck()
        frame.locator('button[data-layout="render"]').click()

        def inspect():
            current = lambda: frame.locator('#preview').element_handle().content_frame()
            wait(current, 'document.querySelectorAll(".matsugit-math mjx-container svg").length === 8')
            preview = current()
            assert preview.locator('[data-mml-node="merror"],.MathJax_Error,mjx-merror').count() == 0
            assert preview.locator('code mjx-container').count() == 0
            assert preview.evaluate('MathJax.version') == '3.2.2'
            assert preview.locator('.matsugit-math svg path').count() > 50
            assert preview.locator('.matsugit-math svg use').count() == 0
            assert preview.locator('.matsugit-math mjx-assistive-mml math').count() == 8
            assert 'Revenue is $10M and the cost is $2M.' in preview.locator('body').text_content()
            assert not remote, remote
            assert not math_errors, math_errors
            assert not errors, errors
            return preview

        for fmt in ('document', 'slides'):
            print('Checking', fmt, flush=True)
            frame.locator(f'button[data-format="{fmt}"]').click()
            wait(frame, f'!!matsugitWorkspace.state.rendered?.{fmt} && !matsugitWorkspace.state.rendering')
            preview = inspect()
            if fmt == 'slides':
                preview.evaluate('Reveal.slide(3)')
                wait(preview, 'Reveal.getCurrentSlide().id === "recovery-calculation"')
            # Inert prose updates preserve the existing equation DOM and iframe.
            preview.evaluate('window.mathSentinel = document.querySelector(".matsugit-math svg")')
            frame.evaluate('''() => {const e=matsugitWorkspace.editor, s=e.state.doc.toString();
                const from=s.indexOf('Editable prose'); e.dispatch({changes:{from,to:from+14,insert:'Updated prose'}})}''')
            frame.evaluate('matsugitWorkspace.render()')
            wait(frame, 'matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision && !matsugitWorkspace.state.rendering')
            assert frame.evaluate('matsugitWorkspace.state.lastRefresh.kind') == 'patch'
            assert inspect().evaluate('mathSentinel === document.querySelector(".matsugit-math svg")')
            print(fmt, 'cold render and warm patch passed', flush=True)
            # Undo, then change real TeX: full typesetting is required.
            frame.locator('#undo').click()
            frame.evaluate('''() => {const e=matsugitWorkspace.editor,s=e.state.doc.toString();
                const from=s.indexOf('1-d');e.dispatch({changes:{from,to:from+3,insert:'1+d'}})}''')
            frame.evaluate('matsugitWorkspace.render()')
            wait(frame, 'matsugitWorkspace.state.renderedRevision === matsugitWorkspace.state.revision && !matsugitWorkspace.state.rendering')
            assert frame.evaluate('matsugitWorkspace.state.lastRefresh.kind') == 'full'
            inspect()
            frame.locator('#undo').click()
            print(fmt, 'math rebuild passed', flush=True)
        assert source.read_bytes() == original
        browser.close()
    print('PASS: offline document/slides math, currency/code, warm patch, math rebuild, Undo, source unchanged')
finally:
    host.terminate(); host.wait(timeout=20)
