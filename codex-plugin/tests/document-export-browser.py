"""A document with invalid slide headings still exports as reading HTML and PDF."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SOURCE = '''---
title: Reading export
document-collapsible: true
---

## Priority concepts

Opening paragraph before any subheading.

### Phases

Reading evidence must not be lost.

### More detail

Additional evidence survives PDF printing.
'''

def wait(frame, expression):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if frame.evaluate(expression):
            return
        time.sleep(.2)
    raise AssertionError(frame.locator('body').inner_text()[-3000:])

with tempfile.TemporaryDirectory(prefix='matsugit-document-export-') as tmp, sync_playwright() as p:
    source = Path(tmp) / 'document.md'
    source.write_text(SOURCE)
    chrome = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE', p.chromium.executable_path)
    host = subprocess.Popen(['node', str(ROOT/'codex-plugin/tests/browser-host.mjs')],
        stdout=subprocess.PIPE, text=True, env=dict(os.environ,
            MATSUGIT_TEST_SOURCE=str(source), MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_DOWNLOAD='blocked',
            MATSUGIT_TEST_OPEN_OPTIONS='{"format":"document","autosave":false}',
            MATSUGIT_EXPORT_PYTHON=sys.executable, MATSUGIT_CHROME=chrome))
    try:
        ready = json.loads(host.stdout.readline())
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page(viewport={'width':1200,'height':900})
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered?.document')
        frame.locator('#download').click()
        wait(frame, '!document.getElementById("export-run").disabled')
        assert frame.locator('#export-format').input_value() == 'pdf-document'
        for selection in ('pdf-document', 'html-document'):
            frame.locator('#export-format').select_option(selection)
            frame.locator('#export-destination').select_option('local')
            frame.locator('#export-run').click()
            wait(frame, '!document.getElementById("export-saved-path").hidden && !document.getElementById("export-run").disabled')
            saved = Path(frame.locator('#export-saved-path').input_value())
            assert saved.parent == Path(ready['downloads'])
            assert '-document.' in saved.name
            if selection.startswith('pdf'):
                assert saved.read_bytes().startswith(b'%PDF-')
                if shutil.which('pdftotext'):
                    text = subprocess.check_output(['pdftotext', str(saved), '-'], text=True)
                    assert 'Reading evidence must not be lost.' in text
                    assert 'Additional evidence survives PDF printing.' in text
            else:
                html = saved.read_text()
                assert 'Reading evidence must not be lost.' in html
                assert 'ff-fold-toggle' in html
                assert '<div class="reveal">' not in html
                reading = browser.new_page()
                reading.goto(saved.as_uri())
                assert reading.locator('.ff-fold-toggle').count() >= 1
                assert reading.get_by_text('Reading evidence must not be lost.', exact=True).is_hidden()
                reading.close()
            assert source.read_text() == SOURCE
        browser.close()
        print('PASS: document PDF/HTML from slide-invalid source, current-view default, collapsed HTML, visible PDF text, original unchanged')
    finally:
        host.terminate()
        host.wait(timeout=20)
