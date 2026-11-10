"""Review, merge and push through the UI, exclusively to a disposable local remote."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def git(repo, *args):
    return subprocess.check_output(['git','-C',str(repo),*args], stderr=subprocess.PIPE, text=True).strip()


def wait(frame, expression, timeout=40):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError((expression, frame.locator('body').inner_text()[-2000:]))


with tempfile.TemporaryDirectory(prefix='matsugit-git-ux-') as temp:
    root = Path(temp); fixture = root/'deck.md'
    base = '# Plan\n\n## Decision\n\nBase evidence\n'
    fixture.write_text(base)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, MATSUGIT_SHOWCASE_SOURCE=str(fixture), QUARTO='/missing-quarto-for-editor-test'))
    try:
        ready = json.loads(host.stdout.readline()); source = Path(ready['source']); repo = source.parent
        remote = root/'remote.git'; web = root/'web'
        git(root,'init','--bare','--initial-branch=main',str(remote)); git(repo,'init','-b','main')
        for key,value in [('user.name','Synthetic'),('user.email','test@example.invalid'),('commit.gpgsign','false'),('core.autocrlf','false')]: git(repo,'config',key,value)
        (repo/'other.txt').write_text('Original\n')
        git(repo,'add',source.name,'other.txt'); git(repo,'commit','-m','Base')
        git(repo,'remote','add','origin',str(remote)); git(repo,'push','-u','origin','main')
        git(root,'clone',str(remote),str(web))
        for key,value in [('user.name','Web'),('user.email','web@example.invalid'),('commit.gpgsign','false')]: git(web,'config',key,value)
        (web/source.name).write_text(base.replace('Base evidence','Remote evidence'))
        git(web,'add',source.name); git(web,'commit','-m','Web edit'); git(web,'push')
        source.write_text(base.replace('Base evidence','Local evidence'))
        (repo/'other.txt').write_text('Unrelated private draft\n')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame=page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.locator('#git-sync').dispatch_event('click')
            wait(frame,'!document.getElementById("git-sync-check").disabled')
            assert 'overlap' in frame.locator('#git-sync-progress').inner_text()
            original_head=git(repo,'rev-parse','HEAD')
            frame.locator('#git-exchange-start').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            assert frame.locator('#merge-title').inner_text()=='Review Git changes'
            assert 'Remote evidence' in frame.locator('#merge-incoming').input_value()
            assert 'Local evidence' in frame.locator('#merge-local').input_value()
            frame.locator('#merge-cancel').click()
            assert git(repo,'rev-parse','HEAD')==original_head
            assert source.read_text().endswith('Local evidence\n')
            frame.locator('#git-exchange-start').click()
            frame.locator('#merge-dialog').wait_for(state='visible')
            frame.locator('#merge-both').click(); frame.locator('#merge-apply').click()
            frame.locator('#git-exchange-confirmation').wait_for(state='visible')
            assert str(remote) in frame.locator('#git-sync-progress').inner_text()
            assert 'not committed' in frame.locator('#git-exchange-warning').inner_text()
            assert git(repo,'rev-parse','HEAD')==original_head
            shots=Path(tempfile.mkdtemp(prefix='matsugit-git-exchange-shots-'))
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                assert frame.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(shots/f'commit-review-{width}.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            frame.locator('#git-exchange-confirm').click()
            wait(frame,'!matsugitWorkspace.state.delivering')
            assert 'Pushed ' in frame.locator('#git-sync-progress').inner_text()
            assert 'Local evidence' in source.read_text() and 'Remote evidence' in source.read_text()
            assert frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')==source.read_text()
            assert frame.locator('#save-state').inner_text()=='Saved to file'
            wait(frame,'document.getElementById("publication-state").textContent.includes("Pushed")')
            assert git(remote,'show','main:other.txt')=='Original'
            assert (repo/'other.txt').read_text()=='Unrelated private draft\n'
            assert git(repo,'diff','--cached')==''

            # A late file edit invalidates the plan, and Check again stays usable.
            frame.locator('#git-exchange-start').click()
            frame.locator('#merge-dialog').wait_for(state='visible'); frame.locator('#merge-apply').click()
            frame.locator('#git-exchange-confirmation').wait_for(state='visible')
            head=git(repo,'rev-parse','HEAD'); source.write_text(source.read_text()+'\nAgent later edit\n')
            frame.locator('#git-exchange-confirm').click(); wait(frame,'!matsugitWorkspace.state.delivering')
            assert 'changed since review' in frame.locator('#git-sync-progress').inner_text()
            assert git(repo,'rev-parse','HEAD')==head and 'Agent later edit' in source.read_text()
            assert frame.locator('#git-sync-check').is_enabled()
            frame.locator('#git-sync-check').click(); wait(frame,'!matsugitWorkspace.state.delivering')
            assert 'No incoming' in frame.locator('#git-sync-progress').inner_text()
            assert not errors, errors
            browser.close()
            print('PASS: Git overlap/cancel/review/push, scope, saved state, stale-plan retry and responsive layout', shots)
    finally:
        host.terminate()
        try: host.wait(timeout=10)
        except subprocess.TimeoutExpired: host.kill(); host.wait()
