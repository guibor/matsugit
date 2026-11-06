"""AI action against an isolated chat host; no real agent messages or documents."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression):
    deadline = time.monotonic() + 30
    while not frame.evaluate(expression):
        assert time.monotonic() < deadline, expression
        time.sleep(.05)


with tempfile.TemporaryDirectory(prefix='matsugit-slide-agent-') as tmp:
    source = '---\ntitle: Narrative\n---\n# Decision\n\n## First\n### A clear claim\n\nEvidence one.\n\n::: takeaway\nA decision\n:::\n\n## Second\n### Another claim\n\nPrivate neighbor.\n'
    fixture = Path(tmp)/'narrative.md'
    fixture.write_text(source)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for mode in ('extended', 'standard', ''):
            host = subprocess.Popen(['node', str(ROOT/'codex-plugin/tests/browser-host.mjs')],
                stdout=subprocess.PIPE, text=True, env=dict(os.environ,
                    MATSUGIT_SHOWCASE_SOURCE=str(fixture), MATSUGIT_TEST_CHAT=mode,
                    MATSUGIT_STANDARD_MCP='1' if mode == 'standard' else '0', QUARTO='/missing-editor-test'))
            try:
                ready = json.loads(host.stdout.readline())
                base = f'http://127.0.0.1:{ready["port"]}'
                disk = Path(ready['source'])
                def messages():
                    with urlopen(base+'/test-messages') as response:
                        return json.load(response)
                page = browser.new_page(viewport={'width':1440,'height':900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                frame = page.frames[1]
                wait(frame, '!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
                frame.locator('#auto').uncheck()
                frame.locator('button[data-layout="story"]').click()
                button = frame.get_by_role('button', name='Edit slide with AI')
                prompt = frame.locator('#slide-agent-prompt')
                send = frame.locator('#slide-agent-send')
                status = frame.locator('#slide-agent-status')
                def open_prompt():
                    button.first.click()
                    frame.locator('#slide-agent-dialog').wait_for()
                def close(): frame.locator('#slide-agent-close').click()
                def edit(value):
                    frame.evaluate('(value)=>{const e=matsugitWorkspace.editor; e.dispatch({changes:{from:0,to:e.state.doc.length,insert:value}})}',value)
                def saved():
                    wait(frame, '!matsugitWorkspace.state.saving && matsugitWorkspace.editor.state.doc.toString() === matsugitWorkspace.state.base')

                button.first.wait_for()
                assert button.count() == 2
                assert button.first.locator('svg').count() == 1
                for story_mode in ('overview','walkthrough'):
                    frame.locator(f'button[data-story-mode="{story_mode}"]').click()
                    for width in (390,800,1440):
                        page.set_viewport_size({'width':width,'height':900})
                        open_prompt()
                        prompt.fill('hjkl'); prompt.press('ArrowLeft')
                        assert prompt.input_value() == 'hjkl'
                        assert frame.locator('#slide-agent-context').inner_text() == 'Decision / Slide 1 / First'
                        assert frame.locator('#slide-agent-source').text_content().startswith('## First\n')
                        assert 'Private neighbor' not in frame.locator('#slide-agent-source').text_content()
                        assert not frame.locator('#slide-agent-dialog').evaluate('(el)=>el.scrollWidth > el.clientWidth+1')
                        close()
                assert disk.read_text() == source and messages() == []
                open_prompt(); assert prompt.input_value() == 'hjkl'
                prompt.fill('Tighten the claim')
                if mode == 'extended' and os.environ.get('MATSUGIT_TEST_ARTIFACTS'):
                    artifacts = Path(os.environ['MATSUGIT_TEST_ARTIFACTS'])
                    artifacts.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(artifacts/'slide-agent-desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    page.screenshot(path=str(artifacts/'slide-agent-mobile.png'))
                    page.set_viewport_size({'width':1440,'height':900})
                if not mode:
                    assert send.is_disabled()
                    assert 'cannot send' in status.inner_text()
                    frame.locator('#slide-agent-copy').click()
                    frame.locator('#slide-agent-request-panel').wait_for()
                    assert 'Tighten the claim' in frame.locator('#slide-agent-request').input_value()
                    assert messages() == [] and disk.read_text() == source
                    close(); page.close(); continue

                assert send.inner_text() == 'Send'
                send.click()
                wait(frame, 'document.querySelector("#slide-agent-status").textContent === "Sent to current chat."')
                assert send.is_disabled()
                assert len(messages()) == 1
                message = messages()[0]
                assert message['role'] == 'user'
                if mode == 'extended':
                    assert message['_meta']['openai/message'] == {'target':'active','send':True}
                else:
                    assert 'openai/message' not in message.get('_meta',{})
                text = message['content'][0]['text']
                assert 'Tighten the claim' in text and 'Evidence one.' in text
                assert 'Private neighbor' not in text
                assert str(disk) in text
                assert disk.read_text() == source
                close()
                if mode == 'standard':
                    assert not errors, errors
                    page.close(); continue

                # An explicit Save and send writes the current draft before dispatch.
                changed = source.replace('Evidence one.', 'Edited evidence.')
                edit(changed)
                open_prompt(); prompt.fill('Polish the title')
                assert send.inner_text() == 'Save and send'
                assert disk.read_text() == source
                send.click()
                wait(frame, 'document.querySelector("#slide-agent-status").textContent === "Sent to current chat."')
                assert disk.read_text() == changed
                assert len(messages()) == 2 and 'Edited evidence.' in messages()[-1]['content'][0]['text']
                close()

                # A pending prompt cannot retarget after an edit, even in the same file.
                open_prompt(); prompt.fill('Keep this instruction')
                edit(changed+'\nAnother edit\n')
                send.click()
                wait(frame, 'document.querySelector("#slide-agent-status").textContent.includes("document changed")')
                assert len(messages()) == 2 and prompt.input_value() == 'Keep this instruction'
                close()
                frame.locator('#save').click(); saved()
                open_prompt(); assert prompt.input_value() == 'Keep this instruction'

                # Failure after delivery is not retried, and the request stays available.
                with urlopen(Request(base+'/test-fail-chat',method='POST')) as response: response.read()
                send.click()
                wait(frame, 'document.querySelector("#slide-agent-status").textContent.includes("Delivery unconfirmed")')
                assert len(messages()) == 3 and send.is_disabled()
                assert prompt.input_value() == 'Keep this instruction'
                close()

                # A dirty draft with a stale etag is never sent or overwritten.
                edit(changed+'\nDraft only\n')
                open_prompt(); prompt.fill('Do not lose my edit')
                disk.write_text(changed+'\nExternal edit\n')
                send.click()
                wait(frame, '!document.querySelector("#slide-agent-send").getAttribute("aria-busy").includes("true")')
                assert len(messages()) == 3
                assert 'Draft only' in frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
                assert 'External edit' in disk.read_text()
                assert 'Sent to current chat' not in status.inner_text()
                assert not errors, errors
                page.screenshot(path=str(Path(tmp)/'ai-prompt.png'))
                print('PASS: sparkles in both modes, responsive prompt, scoped current-chat send, explicit save, stale draft/save refusal, no delivery retries, prompt retention')
                page.close()
            finally:
                host.terminate(); host.wait(timeout=20)
        browser.close()
print('PASS: standard MCP and OpenAI active-chat transport; unsupported-host copy fallback')
