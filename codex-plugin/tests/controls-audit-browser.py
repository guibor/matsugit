"""Every visible, enabled control must do something, in every main state.

An enabled button that does nothing is a broken button, whatever the reason.
For each state (a saved file, an unsaved draft, Story, an untitled workspace,
the narrow Cursor panel) this clicks each visible enabled control outside
dialogs, records what changed, then puts things back. A disabled control must
say why in its tooltip. Nothing may be written to the file except by Save.
"""
import json
import os
from pathlib import Path
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = r'''() => {
  const w = matsugitWorkspace, s = w.state, $ = id => document.getElementById(id);
  const open = [...document.querySelectorAll('dialog')].filter(d => d.open).map(d => d.id);
  const pressed = [...document.querySelectorAll('[aria-pressed],[aria-expanded]')].map(b => (b.id || b.dataset.layout || b.dataset.format || b.dataset.editor || b.dataset.storyMode || b.dataset.storySize || b.dataset.depth || '') + '=' + (b.getAttribute('aria-pressed') ?? b.getAttribute('aria-expanded')));
  const visible = id => $(id) && !$(id).hidden && getComputedStyle($(id)).display !== 'none';
  return JSON.stringify({open, pressed, layout: s.layout, format: s.format, mode: s.editorMode, theme: $('theme').value, presenting: document.body.classList.contains('presenting'),
    text: w.editor.state.doc.toString(), selection: w.editor.state.selection.main.head, scroll: Math.round(w.editor.scrollDOM.scrollTop),
    notice: $('notice-text').textContent, feedback: visible('action-feedback') ? $('action-feedback').textContent : '', status: $('status').textContent,
    panels: ['check-panel', 'more-panel', 'role-help', 'story-preview', 'recovery-banner'].map(id => id + ':' + visible(id)).join(','),
    feedbackAttr: [...document.querySelectorAll('[data-feedback]')].map(b => b.id + b.dataset.feedback).join(','),
    story: $('story-list')?.innerText.length, storyFocus: document.activeElement?.closest('#story-list') ? document.activeElement.className : '',
    rail: [...document.querySelectorAll('.rail-slide[aria-current=true]')].map(b => b.dataset.index).join(','), storyScroll: Math.round($('story-list')?.scrollTop || 0),
    storyCurrent: document.querySelector('#story-list [aria-current=true], #story-list .story-current')?.textContent?.slice(0, 40) || '', position: $('story-position')?.textContent || '',
    downloads: window.parent.downloadRequests?.length || 0, preview: $('preview').src.slice(0, 40), checked: [...document.querySelectorAll('input[type=checkbox]')].map(i => i.checked ? 1 : 0).join('')});
}'''
CANDIDATES = r'''() => [...document.querySelectorAll('button, input[type=checkbox], select')]
  .filter(el => !el.closest('dialog') && !el.closest('.cm-editor') && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden')
  .map((el, index) => { el.dataset.auditIndex = index; return {index, id: el.id, label: (el.getAttribute('aria-label') || el.title || el.textContent || '').trim().slice(0, 60),
    disabled: el.disabled, title: el.title, tag: el.tagName, inStory: !!el.closest('#story-list'), inRail: !!el.closest('#slide-rail'),
    selected: el.getAttribute('aria-pressed') === 'true' && !!el.closest('.segmented, [role=group]')}; })'''
# Controls whose effect is outside the page (or deliberately nothing to observe here).
OUTSIDE = {'copy-path'}


def wait(frame, expression, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if frame.evaluate(expression):
            return
        time.sleep(.1)
    raise AssertionError(expression)


def audit(label, query='', host_mode='', options=None, prepare=None):
    env = dict(os.environ, MATSUGIT_TEST_OPEN_OPTIONS=json.dumps(options or {}), MATSUGIT_TEST_DOWNLOAD='standard')
    if host_mode == 'cursor':
        env.update(MATSUGIT_TEST_HOST='cursor', MATSUGIT_STANDARD_MCP='1')
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], env=env, stdout=subprocess.PIPE, text=True)
    problems, clicked = [], []
    try:
        ready = json.loads(host.stdout.readline())
        source = Path(ready['source']); original = source.read_text()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 760 if host_mode == 'cursor' else 1440, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('download', lambda download: download.cancel())
            page.goto(f'http://127.0.0.1:{ready["port"]}{query}')
            frame = page.frames[1]
            wait(frame, '!!window.matsugitWorkspace && !matsugitWorkspace.state.loading && (matsugitWorkspace.state.session || matsugitWorkspace.state.name)')
            page.wait_for_timeout(1500)
            if prepare:
                prepare(frame, page)
            seen = set()
            for _ in range(80):
                controls = frame.evaluate(CANDIDATES)
                pending = [c for c in controls if (c['id'] or c['label'], c['inStory'], c['inRail']) not in seen]
                if not pending:
                    break
                control = pending[0]
                key = (control['id'] or control['label'], control['inStory'], control['inRail'])
                seen.add(key)
                name = control['id'] or control['label']
                if control['disabled']:
                    if not control['title']:
                        problems.append(f'{name}: disabled with no explanation')
                    continue
                if control['id'] in OUTSIDE or control['selected']:
                    # Choosing the option that is already chosen is meant to do nothing.
                    continue
                before = frame.evaluate(SNAPSHOT)
                # Story repaints its rows; find the control again just before using it.
                fresh = [c for c in frame.evaluate(CANDIDATES) if (c['id'] or c['label'], c['inStory'], c['inRail']) == key]
                if fresh:
                    control = fresh[0]
                element = frame.locator(f'[data-audit-index="{control["index"]}"]')
                try:
                    if control['tag'] == 'SELECT':
                        options_list = element.evaluate('e => [...e.options].map(o => o.value)')
                        current = element.input_value()
                        others = [value for value in options_list if value != current]
                        if not others:
                            continue
                        element.select_option(others[0])
                    else:
                        # Row actions in Story appear on hover, as they do for a person.
                        element.evaluate('e => e.closest(".story-row, .story-slide, .story-section, li")?.dispatchEvent(new PointerEvent("pointerover", {bubbles: true}))')
                        element.hover(timeout=4000)
                        element.click(timeout=4000)
                except Exception as error:
                    problems.append(f'{name}: could not be clicked ({str(error).splitlines()[0][:120]})')
                    continue
                page.wait_for_timeout(700)
                after = frame.evaluate(SNAPSHOT)
                clicked.append(name)
                if after == before:
                    problems.append(f'{name}: enabled but nothing happened')
                restore(frame, page, before)
                if errors:
                    problems.append(f'{name}: page error {errors[-1][:160]}')
                    errors.clear()
            on_disk = source.read_text()
            if on_disk != original and not frame.evaluate('matsugitWorkspace.editor.state.doc.toString()') == on_disk:
                problems.append('the file changed without a matching Save')
            browser.close()
    finally:
        host.terminate()
        host.wait(timeout=20)
    return label, clicked, problems


def restore(frame, page, before):
    """Close what opened and undo what changed, so the next control starts clean."""
    for _ in range(4):
        open_dialogs = frame.evaluate('[...document.querySelectorAll("dialog")].filter(d => d.open).map(d => d.id)')
        if not open_dialogs:
            break
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        for dialog in frame.evaluate('[...document.querySelectorAll("dialog")].filter(d => d.open).map(d => d.id)'):
            frame.evaluate('id => { try { document.getElementById(id).close(); } catch {} }', dialog)
    if frame.evaluate('document.body.classList.contains("presenting")'):
        frame.locator('#present-exit').click()
    for panel, closer in (('more-panel', '#more'), ('check-panel', '#check-close')):
        if frame.evaluate(f'!document.getElementById("{panel}").hidden'):
            frame.locator(closer).click()
    state = json.loads(before)
    frame.evaluate('''([layout, format, mode]) => {
      document.querySelector(`button[data-layout="${layout}"]`)?.click();
      document.querySelector(`button[data-format="${format}"]`)?.click();
      document.querySelector(`button[data-editor="${mode}"]`)?.click(); }''', [state['layout'], state['format'], state['mode']])


SAVED = {'layout': 'split', 'format': 'slides', 'editor': 'visual'}


def dirty(frame, page):
    frame.evaluate('(() => { const e = matsugitWorkspace.editor; e.dispatch({changes: {from: e.state.doc.length, insert: "\\nAn unsaved line."}}); })()')


if __name__ == '__main__':
    runs = [
        audit('saved file', options=SAVED),
        audit('unsaved draft', options=SAVED, prepare=dirty),
        audit('Story', options={'layout': 'story', 'format': 'slides'}),
        audit('untitled workspace', query='?untitled', options=SAVED),
        audit('Cursor panel', host_mode='cursor', options=SAVED),
    ]
    failed = False
    for label, clicked, problems in runs:
        print(f'{label}: {len(clicked)} controls exercised', flush=True)
        for problem in problems:
            failed = True
            print('  PROBLEM', problem, flush=True)
    if failed:
        raise SystemExit(1)
    print('PASS: every visible enabled control does something; disabled ones say why; no stray writes', flush=True)
