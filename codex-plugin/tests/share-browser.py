"""Real plugin UI: one Share button from first share to two-way changes.

Uses a local bare remote behind a fake ssh (see publish-target.py); nothing
leaves the machine and no real account, project or site is touched.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', tempfile.mkdtemp(prefix='matsugit-share-')))
shots.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location('publish_target', Path(__file__).with_name('publish-target.py'))
publish_target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_target)
info = publish_target.create(Path(tempfile.mkdtemp(prefix='matsugit-share-target-')).resolve() / 'target')
root = Path(info['repo']).parent
env = dict(os.environ, MATSUGIT_TEST_SOURCE=info['source'], MATSUGIT_TEST_CONFIG=info['config'],
           GIT_SSH_COMMAND=info['ssh'], MATSUGIT_STANDARD_MCP='1')


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def wait(frame, expression, timeout=90):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if frame.evaluate(expression):
            return
        time.sleep(.15)
    raise AssertionError(expression + '\n' + frame.locator('#share-dialog').inner_text() + '\n' + frame.locator('#notice-text').inner_text())


TEXT = 'matsugitWorkspace.editor.state.doc.toString()'
IDLE = '!matsugitWorkspace.state.delivering'
host = subprocess.Popen(['node', str(ROOT / 'codex-plugin/tests/browser-host.mjs')], env=env, stdout=subprocess.PIPE, text=True)
try:
    ready = json.loads(host.stdout.readline())
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1300, 'height': 850}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{ready["port"]}')
        frame = page.frames[1]
        wait(frame, '!!window.matsugitWorkspace?.state.rendered')
        frame.locator('#auto').uncheck()
        title = lambda: frame.locator('#share-title').inner_text()
        detail = lambda: frame.locator('#share-detail').inner_text()

        def edit(old, new):
            frame.evaluate('''([old, text]) => { const e = matsugitWorkspace.editor, at = e.state.doc.toString().indexOf(old);
              if (at < 0) throw Error('missing ' + old);
              e.dispatch({changes: {from: at, to: at + old.length, insert: text}}); }''', [old, new])

        def settled(expected):
            wait(frame, IDLE + f' && document.getElementById("share-title").textContent.startsWith({json.dumps(expected)})')

        # One button; the detailed Git controls are no longer in the header.
        assert frame.locator('#share').inner_text().strip() == 'Share'
        for hidden in ('#git-sync', '#publish', '#publication-state'):
            assert frame.locator(hidden).is_hidden()

        # First share, starting from an unsaved edit: save, move into the project, send.
        edit('Evidence.', 'Evidence, first version.')
        frame.locator('#share').click()
        settled('Not shared yet')
        assert 'saved first' in detail() and frame.locator('#share-destination').input_value() == 'docs'
        assert frame.locator('#share-destination option').inner_text() == 'team/docs'
        page.screenshot(path=str(shots / 'share-first.png'))
        frame.locator('#share-go').click()
        settled('Ready to share')
        assert 'https://git.example.invalid/team/docs' in detail() and 'A link stays' in detail()
        assert Path(info['source']).read_text().count('first version') == 1 and not Path(info['source']).is_symlink()
        assert not Path(info['destination']).exists()
        page.screenshot(path=str(shots / 'share-ready.png'))
        frame.locator('#share-go').click()
        settled('Sent')
        # No provider login exists for this synthetic host: say so, never claim "Live".
        wait(frame, 'document.getElementById("share-detail").textContent.includes("cannot see the site build")', 60)
        assert title() == 'Sent'
        assert frame.locator('#share-link').get_attribute('href') == 'https://git.example.invalid/team/docs'
        assert Path(info['source']).is_symlink() and 'first version' in Path(info['destination']).read_text()
        assert 'first version' in git(root / 'remotes/team/docs.git', 'show', 'main:matsugit-site/deck/source.md')
        assert frame.evaluate('matsugitWorkspace.state.path') == info['destination']
        assert frame.locator('#filename').inner_text() == 'deck/source.md'
        page.screenshot(path=str(shots / 'share-sent.png'))
        frame.locator('#share-close').click()
        wait(frame, 'document.getElementById("share").textContent.trim() === "Sent"', 20)

        # Later changes: one check, one confirmation.
        edit('first version', 'second version')
        wait(frame, 'document.getElementById("share").textContent.trim() === "Share changes"', 20)
        frame.locator('#share').click()
        settled('You have unsaved changes')
        frame.locator('#share-go').click()
        settled('Ready to share')
        assert 'git.example.invalid' in detail()
        frame.locator('#share-go').click()
        settled('Sent')
        assert 'second version' in git(root / 'remotes/team/docs.git', 'show', 'main:matsugit-site/deck/source.md')
        frame.locator('#share-close').click()

        # Nothing new: say so instead of offering to send.
        frame.locator('#share').click()
        wait(frame, IDLE + ' && /^(Up to date|Sent)/.test(document.getElementById("share-title").textContent)')
        assert frame.locator('#share-go').is_hidden()
        frame.locator('#share-close').click()

        # A colleague edits the deck in the project (as the GitLab web editor would).
        other = root / 'colleague'
        git(root, 'clone', 'git@git.example.invalid:team/docs.git', str(other))
        git(other, 'config', 'user.name', 'Colleague'); git(other, 'config', 'user.email', 'colleague@example.invalid')
        shared = other / 'matsugit-site/deck/source.md'

        def colleague(old, new):
            git(other, 'pull', '--ff-only')
            assert old in shared.read_text()
            shared.write_text(shared.read_text().replace(old, new))
            git(other, 'commit', '-am', 'Colleague edit'); git(other, 'push')

        colleague('## One claim', '## One sharper claim')
        frame.locator('#share').click()
        settled('Someone else changed this deck')
        frame.locator('#share-go').click()
        settled('Up to date')
        wait(frame, TEXT + '.includes("One sharper claim")', 20)
        frame.locator('#share-close').click()

        # Both changed different parts: combined without questions.
        colleague('title: Pilot', 'title: Pilot review')
        edit('second version', 'third version')
        frame.locator('#share').click()
        settled('You have unsaved changes')
        frame.locator('#share-go').click()
        settled('Ready to share')
        assert 'combined with yours' in detail()
        frame.locator('#share-go').click()
        settled('Sent')
        pushed = git(root / 'remotes/team/docs.git', 'show', 'main:matsugit-site/deck/source.md')
        assert 'title: Pilot review' in pushed and 'third version' in pushed
        wait(frame, TEXT + '.includes("title: Pilot review")', 20)
        frame.locator('#share-close').click()

        # Both changed the same sentence: the author chooses, then one confirmation.
        colleague('third version', 'their wording')
        edit('third version', 'my wording')
        frame.locator('#share').click()
        settled('You have unsaved changes')
        frame.locator('#share-go').click()
        settled('You and someone else changed the same part')
        frame.locator('#share-go').click()
        frame.locator('#merge-mine').click()
        page.screenshot(path=str(shots / 'share-choose.png'))
        frame.locator('#merge-apply').click()
        settled('Ready to share')
        assert 'my wording' not in git(root / 'remotes/team/docs.git', 'show', 'main:matsugit-site/deck/source.md')
        frame.locator('#share-go').click()
        settled('Sent')
        pushed = git(root / 'remotes/team/docs.git', 'show', 'main:matsugit-site/deck/source.md')
        assert 'my wording' in pushed and 'their wording' not in pushed
        frame.locator('#share-close').click()

        # The detailed views remain one step away.
        frame.locator('#share').click()
        wait(frame, IDLE)
        frame.locator('#share-advanced summary').click()
        frame.locator('#share-advanced-sync').click()
        assert frame.locator('#git-sync-dialog').is_visible() and frame.locator('#share-dialog').is_hidden()
        wait(frame, IDLE)
        frame.locator('#close-git-sync').click()
        for width, height in [(390, 844), (760, 800)]:
            page.set_viewport_size({'width': width, 'height': height})
            frame.locator('#share').click()
            wait(frame, IDLE)
            page.screenshot(path=str(shots / f'share-{width}.png'))
            assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
            frame.locator('#share-close').click()
        assert not errors, errors
        print('PASS: first share with save and move, later changes, nothing new, colleague edits, combined and conflicting changes, advanced views', flush=True)
        page.close(run_before_unload=False)
        browser.close()
finally:
    host.terminate()
    host.wait(timeout=20)
