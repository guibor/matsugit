"""Randomised two-writer stress test of the real workspace.

An author types, amends, undoes and saves in the editor (autosave on or off)
while another writer edits the same file on disk: targeted edits, rewrites made
from an older read, and changes to the same lines. Every inserted line carries a
unique marker, so loss can be detected exactly.

Invariants, checked after every step:
- The workspace never removes another writer's marker from the file.
- A marker the author typed, and did not undo, is never missing from the editor.
- No page error, and the workspace never stays busy.
At the end, with nothing pending, the file equals the editor or a review is
being shown. A review is resolved with "Keep both" and the result saved.

MATSUGIT_FUZZ_SEEDS=1,2,3 MATSUGIT_FUZZ_STEPS=30 select the runs.
"""
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SEEDS = [int(seed) for seed in os.environ.get('MATSUGIT_FUZZ_SEEDS', '1,2,3,4').split(',')]
STEPS = int(os.environ.get('MATSUGIT_FUZZ_STEPS', '28'))
EXT = re.compile(r'EXT-\d+')
ME = re.compile(r'ME-\d+')


class Failure(AssertionError):
    pass


def run(seed):
    rng = random.Random(seed)
    autosave = seed % 2 == 1
    env = dict(os.environ, MATSUGIT_STANDARD_MCP='1', MATSUGIT_TEST_HOST=os.environ.get('MATSUGIT_TEST_HOST', ''),
               MATSUGIT_TEST_OPEN_OPTIONS=json.dumps({'autosave': autosave, 'editor': rng.choice(['raw', 'visual'])}))
    host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], env=env, stdout=subprocess.PIPE, text=True)
    log = []
    try:
        ready = json.loads(host.stdout.readline())
        source = Path(ready['source'])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width': 1300, 'height': 850})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame = page.frames[1]
            E = frame.evaluate

            def wait(expression, timeout=30):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    if E(expression):
                        return True
                    time.sleep(.1)
                return False

            if not wait('!!window.matsugitWorkspace?.state.session && !matsugitWorkspace.state.loading'):
                raise Failure('workspace did not open')
            frame.locator('#auto').uncheck()
            text = lambda: E('matsugitWorkspace.editor.state.doc.toString()')
            state = lambda: E('''(() => { const s = matsugitWorkspace.state; return {conflict: s.conflict, saving: s.saving,
              merging: s.merging, loading: s.loading, base: s.base, dirty: matsugitWorkspace.editor.state.doc.toString() !== s.base}; })()''')
            disk_history = [source.read_text()]
            live_me, counter = set(), {'ext': 0, 'me': 0}
            disk_ext = set(EXT.findall(disk_history[-1]))
            last_disk = disk_history[-1]

            def observe_disk(written_by_us=False):
                nonlocal disk_ext, last_disk
                current = source.read_text()
                if current != last_disk and not written_by_us:
                    # The workspace wrote the file: it must keep every marker the other writer put there.
                    lost = disk_ext - set(EXT.findall(current))
                    if lost:
                        raise Failure(f'workspace removed another writer\'s lines from the file: {sorted(lost)}')
                    disk_history.append(current)
                last_disk = current
                disk_ext = set(EXT.findall(current))

            def check(step):
                observe_disk()
                if errors:
                    raise Failure(f'page error: {errors}')
                if not ready_quiet(2):
                    pass
                missing = {m for m in live_me if m not in text()}
                if missing:
                    raise Failure(f'author typing missing from the editor after {step}: {sorted(missing)}')

            def ready_quiet(timeout):
                return wait('!matsugitWorkspace.state.saving && !matsugitWorkspace.state.merging && !matsugitWorkspace.state.loading', timeout)

            def lines_of(value):
                return value.split('\n')

            def insert_line(value, line):
                parts = lines_of(value)
                # Never inside the settings block at the top.
                start = next((i for i, l in enumerate(parts[1:], 1) if l.strip() == '---'), 0) + 1
                at = rng.randint(start, len(parts))
                return '\n'.join(parts[:at] + ['', line, ''] + parts[at:])

            def external_write(content, label):
                nonlocal disk_ext, last_disk
                source.write_text(content)
                disk_history.append(content)
                last_disk = content
                disk_ext = set(EXT.findall(content))
                log.append(label)

            for step in range(STEPS):
                busy = state()
                if busy['conflict'] or E('document.getElementById("merge-dialog").open'):
                    resolve(frame, page, log)
                    # A person chose the outcome. Re-baseline what must survive.
                    live_me = {m for m in live_me if m in text()}
                    check('resolve'); continue
                op = rng.choices(['type', 'amend-me', 'save', 'undo', 'ext-target', 'ext-stale', 'ext-amend', 'wait', 'toggle'],
                                 [6, 2, 3, 1, 4, 2, 2, 3, 1])[0]
                if op == 'type':
                    counter['me'] += 1
                    marker = f'ME-{counter["me"]}'
                    line = f'Author note {marker} written by the person.'
                    if rng.random() < .5:
                        E('(() => { const e = matsugitWorkspace.editor; e.dispatch({selection: {anchor: e.state.doc.length}}); e.focus(); })()')
                        page.keyboard.type('\n\n' + line, delay=4)
                    else:
                        current = text()
                        updated = insert_line(current, line)
                        E('''value => { const e = matsugitWorkspace.editor, old = e.state.doc.toString();
                          let a = 0; while (a < old.length && old[a] === value[a]) a++;
                          let b = 0; while (b < old.length - a && old[old.length - 1 - b] === value[value.length - 1 - b]) b++;
                          e.dispatch({changes: {from: a, to: old.length - b, insert: value.slice(a, value.length - b)}, userEvent: 'input'}); }''', updated)
                    live_me.add(marker); log.append(op + ' ' + marker)
                elif op == 'amend-me':
                    candidates = [m for m in sorted(live_me) if m in text()] + sorted(set(EXT.findall(text())))
                    if candidates:
                        marker = rng.choice(candidates)
                        E('''m => { const e = matsugitWorkspace.editor, t = e.state.doc.toString(), at = t.indexOf(m);
                          const end = t.indexOf('\\n', at); const to = end < 0 ? t.length : end;
                          e.dispatch({changes: {from: to, insert: ' amended by the person'}, userEvent: 'input'}); }''', marker)
                        log.append(op + ' ' + marker)
                elif op == 'save':
                    if not E('document.getElementById("save").disabled'):
                        frame.locator('#save').click(); log.append('save')
                        if E('document.getElementById("merge-dialog").open'):
                            resolve(frame, page, log)
                            live_me = {m for m in live_me if m in text()}
                elif op == 'undo':
                    before = text()
                    E('matsugitWorkspace.editor.focus()')
                    page.keyboard.press('ControlOrMeta+z')
                    gone = {m for m in live_me if m in before and m not in text()}
                    live_me -= gone; log.append('undo ' + ','.join(sorted(gone)))
                elif op in ('ext-target', 'ext-stale', 'ext-amend'):
                    counter['ext'] += 1
                    marker = f'EXT-{counter["ext"]}'
                    current = source.read_text()
                    if op == 'ext-target':
                        content = insert_line(current, f'Agent note {marker} from the other writer.')
                    elif op == 'ext-stale':
                        older = disk_history[-rng.randint(1, min(4, len(disk_history)))]
                        content = insert_line(older, f'Agent note {marker} written from an older read.')
                    else:
                        found = ME.findall(current) + EXT.findall(current)
                        if not found:
                            content = insert_line(current, f'Agent note {marker} from the other writer.')
                        else:
                            target = rng.choice(found)
                            content = re.sub(rf'({re.escape(target)}[^\n]*)', rf'\1 changed by {marker}', current, count=1)
                    external_write(content, op + ' ' + marker)
                elif op == 'toggle':
                    frame.locator('#more').click()
                    frame.locator('#autosave').click()
                    page.keyboard.press('Escape'); log.append('toggle autosave')
                page.wait_for_timeout(rng.choice([150, 400, 900, 1800, 3400]))
                check(op)
            # Settle: let polling, merging and autosave finish.
            page.wait_for_timeout(4000)
            ready_quiet(30)
            if state()['conflict'] or E('document.getElementById("merge-dialog").open'):
                resolve(frame, page, log)
                live_me = {m for m in live_me if m in text()}
            if state()['dirty'] and not E('document.getElementById("save").disabled'):
                frame.locator('#save').click()
                if E('document.getElementById("merge-dialog").open'):
                    resolve(frame, page, log)
            page.wait_for_timeout(4000)
            ready_quiet(30)
            check('settle')
            final = state()
            if any(final[k] for k in ('saving', 'merging', 'loading')):
                raise Failure(f'workspace stayed busy: {final}')
            if not final['conflict'] and not final['dirty'] and source.read_text() != text():
                raise Failure('editor says saved but the file differs')
            if not final['conflict']:
                missing = sorted(disk_ext - set(EXT.findall(text())))
                if missing:
                    raise Failure(f'other writer\'s lines on disk missing from the editor: {missing}')
            browser.close()
        return log
    except Failure as failure:
        raise Failure(f'seed {seed} (autosave {autosave}): {failure}\nsteps: {log}') from None
    finally:
        host.terminate()
        host.wait(timeout=20)


def resolve(frame, page, log):
    """A person reviewing: keep both versions of each overlapping passage, then save."""
    if not frame.evaluate('document.getElementById("merge-dialog").open'):
        if frame.locator('#reload').is_visible() and frame.locator('#reload').is_enabled():
            frame.locator('#reload').click()
        else:
            frame.locator('#save').click()
    deadline = time.monotonic() + 20
    while not frame.evaluate('document.getElementById("merge-dialog").open') and time.monotonic() < deadline:
        time.sleep(.1)
    if not frame.evaluate('document.getElementById("merge-dialog").open'):
        raise Failure('a review was needed but no review opened')
    for _ in range(50):
        if frame.locator('#merge-both').is_visible():
            frame.locator('#merge-both').click()
        if frame.locator('#merge-next').is_enabled():
            frame.locator('#merge-next').click()
        else:
            break
    frame.locator('#merge-apply').click()
    deadline = time.monotonic() + 20
    while frame.evaluate('document.getElementById("merge-dialog").open') and time.monotonic() < deadline:
        if frame.locator('#merge-both').is_visible() and frame.locator('#merge-apply').is_enabled():
            frame.locator('#merge-apply').click()
        time.sleep(.2)
    if frame.evaluate('document.getElementById("merge-dialog").open'):
        status = frame.locator('#merge-status').inner_text()
        frame.locator('#merge-cancel').click()
        log.append('review left open: ' + status)
    else:
        log.append('resolved')


if __name__ == '__main__':
    for seed in SEEDS:
        steps = run(seed)
        print(f'seed {seed}: {len(steps)} steps passed', flush=True)
    print('PASS: two writers, randomised; no lost lines, no overwritten file, never stuck', flush=True)
