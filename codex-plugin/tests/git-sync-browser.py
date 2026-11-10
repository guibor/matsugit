"""Real MCP + browser sync against disposable local Git remotes only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def wait(frame, expression, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.2)
    raise AssertionError(frame.locator('body').inner_text()[-4000:])


server = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')],
                          stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(server.stdout.readline())
    source = Path(ready['source']); repo = source.parent
    with tempfile.TemporaryDirectory() as temp, sync_playwright() as p:
        remote, web = Path(temp) / 'remote.git', Path(temp) / 'web'
        git(temp, 'init', '--bare', '--initial-branch=main', str(remote))
        git(repo, 'init', '-b', 'main')
        git(repo, 'config', 'user.name', 'Test'); git(repo, 'config', 'user.email', 'test@example.invalid')
        (repo / '.gitignore').write_text('recovery/\n')
        git(repo, 'add', source.name, '.gitignore'); git(repo, 'commit', '-m', 'Base')
        git(repo, 'remote', 'add', 'origin', str(remote)); git(repo, 'push', '-u', 'origin', 'main')
        git(temp, 'clone', str(remote), str(web))
        git(web, 'config', 'user.name', 'Web'); git(web, 'config', 'user.email', 'web@example.invalid')
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width':1440, 'height':900})
        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{ready['port']}")
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        (web / source.name).write_text('## Web update\n\nEdited in upstream.\n')
        git(web, 'add', source.name); git(web, 'commit', '-m', 'Web update'); git(web, 'push')
        old = source.read_bytes()
        frame.locator('#git-sync').dispatch_event('click')
        wait(frame, '!document.getElementById("git-sync-apply").disabled')
        assert source.read_bytes() == old
        assert 'Updates available' in frame.locator('#git-sync-progress').inner_text()
        frame.locator('#git-sync-apply').click()
        wait(frame, 'window.matsugitWorkspace.state.base.includes("Web update")')
        wait(frame, 'window.matsugitWorkspace.state.renderedRevision === window.matsugitWorkspace.state.revision')
        assert 'Web update' in source.read_text()
        frame.locator('#close-git-sync').click()

        # Saved local edits with no upstream updates are not a conflict.
        synced = source.read_text()
        source.write_text(synced + '\nMy saved edit.\n')
        frame.evaluate('window.matsugitWorkspace.reload()')
        frame.locator('#git-sync').dispatch_event('click')
        wait(frame, '!document.getElementById("git-sync-check").disabled')
        assert 'No incoming updates' in frame.locator('#git-sync-progress').inner_text()
        assert 'not published' in frame.locator('#git-sync-progress').inner_text()
        assert frame.locator('#git-sync-apply').is_disabled()
        for _ in range(3):
            frame.locator('#git-sync-check').click()
            wait(frame, '!document.getElementById("git-sync-check").disabled')
            assert 'No incoming updates' in frame.locator('#git-sync-progress').inner_text()
        frame.locator('#git-sync-publish').click()
        wait(frame, 'document.getElementById("publish-dialog").open && !window.matsugitWorkspace.state.delivering')
        assert not frame.locator('#git-sync-dialog').evaluate('(el) => el.open')
        frame.locator('#close-publish').click()
        assert 'My saved edit.' in source.read_text()

        # A true overlap is named; rechecking after manual reconciliation works.
        (web / source.name).write_text('## Overlapping upstream edit\n')
        git(web, 'add', source.name); git(web, 'commit', '-m', 'Overlap'); git(web, 'push')
        frame.locator('#git-sync').dispatch_event('click')
        wait(frame, '!document.getElementById("git-sync-check").disabled')
        assert 'Overlapping files' in frame.locator('#git-sync-progress').inner_text()
        assert source.name in frame.locator('#git-sync-progress').inner_text()
        assert frame.locator('#git-sync-apply').is_disabled()
        assert 'My saved edit.' in source.read_text()
        source.write_text(synced)  # Simulate an explicit reconciliation in this disposable checkout.
        frame.evaluate('window.matsugitWorkspace.reload()')
        unrelated = repo / 'local notes.txt'; unrelated.write_text('Keep my unrelated work\n')
        frame.locator('#git-sync-check').click()
        wait(frame, '!document.getElementById("git-sync-check").disabled')
        assert 'do not overlap' in frame.locator('#git-sync-progress').inner_text()
        assert frame.locator('#git-sync-apply').is_enabled()
        frame.locator('#git-sync-apply').click()
        wait(frame, '!window.matsugitWorkspace.state.delivering')
        assert 'Overlapping upstream edit' in source.read_text()
        assert unrelated.read_text() == 'Keep my unrelated work\n'
        assert git(repo, 'stash', 'list') == ''

        # A network failure must release controls and allow the same panel to retry.
        git(repo, 'remote', 'set-url', 'origin', str(Path(temp) / 'absent.git'))
        frame.locator('#git-sync-check').click()
        wait(frame, '!document.getElementById("git-sync-check").disabled')
        assert 'absent.git' in frame.locator('#git-sync-progress').inner_text()
        git(repo, 'remote', 'set-url', 'origin', str(remote))
        frame.locator('#git-sync-check').click()
        wait(frame, '!document.getElementById("git-sync-check").disabled')
        assert 'No incoming updates' in frame.locator('#git-sync-progress').inner_text()
        frame.locator('#close-git-sync').click()

        (web / source.name).write_text('## Another upstream edit\n')
        git(web, 'add', source.name); git(web, 'commit', '-m', 'Another'); git(web, 'push')
        frame.evaluate('window.matsugitWorkspace.editor.dispatch({changes:{from:0,insert:"UNSAVED DRAFT\\n"}})')
        frame.locator('#git-sync').dispatch_event('click')
        wait(frame, '!document.getElementById("git-sync-apply").disabled')
        frame.locator('#git-sync-apply').click()
        assert 'Unsaved' in frame.locator('#git-sync-progress').inner_text()
        assert 'UNSAVED DRAFT' in frame.evaluate('window.matsugitWorkspace.editor.state.doc.toString()')
        assert 'Another upstream' not in source.read_text()
        for width, height in ((1440,900),(390,844)):
            page.set_viewport_size({'width':width,'height':height})
            box = frame.locator('#git-sync-dialog').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert box['y'] >= 0 and box['y'] + box['height'] <= height
            page.screenshot(path=f'/tmp/matsugit-git-sync-{width}.png')
        assert not errors, errors
        browser.close()
        print('Git sync: upstream edits, saved local edits, repeated checks, overlap/reconciliation retry, unrelated changes preserved, fetch failure/retry, publish review, unsaved draft and responsive dialog passed.')
finally:
    server.terminate(); server.wait(timeout=30)
