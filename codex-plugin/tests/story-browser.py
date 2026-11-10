"""Story editor against the real plugin, using an isolated synthetic file."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if frame.evaluate(expression): return
        time.sleep(.1)
    raise AssertionError((expression, frame.locator('body').inner_text()[-3000:]))


original = '''
---
title: From pilot to repeatable growth
slide-layout: structured
---

<!--
# Section example
## Slide example
### Claim example
  ::: takeaway: optional conclusion, not a live fence
-->

# Why now

## Demand has moved beyond the early adopters
### The constraint is onboarding, not customer interest

| Segment | Interest | Activated |
| --- | --- | --- |
| New teams | 82% | 31% |
| Existing teams | 74% | 68% |

::: notes
Keep this evidence with the first slide.
:::

## A smaller first step unlocks adoption
### Reduce setup before expanding the launch

- Lead with a useful first workflow.
- Measure time to first value.

::: takeaway
Make the first ten minutes count.
:::

# What we do next

## Test the simpler onboarding with three teams
### A focused pilot gives us a decision, not just more data

- Confirm ownership.
- Observe activation.
- Review the evidence together.

## Scale only what proves repeatable

The final decision stays with this slide.
'''

with tempfile.TemporaryDirectory(prefix='matsugit-story-') as tmp:
    fixture = Path(tmp)/'growth-review.md'; fixture.write_text(original)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')], stdout=subprocess.PIPE,text=True,
        env=dict(os.environ,MATSUGIT_SHOWCASE_SOURCE=str(fixture),
                 QUARTO=os.environ.get('QUARTO','quarto') if os.environ.get('MATSUGIT_STORY_RENDER') else '/missing-quarto-for-editor-test'))
    try:
        ready = json.loads(host.stdout.readline()); source = Path(ready['source'])
        shots = Path(os.environ.get('MATSUGIT_STORY_SHOTS',tempfile.mkdtemp(prefix='matsugit-story-shots-')))
        shots.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []; page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{ready["port"]}'); frame = page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck(); frame.locator('#sync').uncheck()
            if os.environ.get('MATSUGIT_STORY_RENDER'):
                wait(frame,'!!matsugitWorkspace.state.rendered?.document',timeout=120)
            frame.locator('button[data-layout="story"]').click()
            frame.locator('.story-slide').first.wait_for()
            def current(): return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            def titles(): return frame.locator('.story-slide .story-heading .story-title').all_text_contents()
            def row(label): return frame.get_by_role('listitem',name=label,exact=True)
            def undo():
                frame.locator('#undo').click(); time.sleep(.15)
            assert len(titles()) == 4
            assert not frame.locator('#editor').is_visible()
            assert not frame.locator('#preview-pane').is_visible()
            assert frame.locator('.story-claim').count() == 3
            assert frame.locator('.story-row').count() == 6
            assert frame.locator('[data-story-depth]').count() == 0
            page.screenshot(path=str(shots/'story-overview.png'))
            # Overview and Walkthrough are presentations of the same paired slides.
            assert frame.locator('#story-pane').get_attribute('data-story-mode') == 'overview'
            first = frame.locator('.story-slide').first
            overview_height = first.bounding_box()['height']
            revision = frame.evaluate('matsugitWorkspace.state.revision')
            assert overview_height < 75
            assert first.bounding_box()['x'] > frame.locator('.story-section').first.bounding_box()['x']
            first.focus()
            frame.locator('button[data-story-mode="walkthrough"]').click()
            assert first.bounding_box()['height'] > 300
            assert frame.locator('#story-position').inner_text() == '1 / 4'
            assert 'Segment' not in frame.locator('#story-list').inner_text()
            assert not frame.locator('#preview-pane').is_visible()
            assert current() == original and frame.evaluate('matsugitWorkspace.state.revision') == revision
            page.screenshot(path=str(shots/'story-walkthrough.png'))
            frame.locator('#story-next').click()
            assert frame.locator('#story-position').inner_text() == '2 / 4'
            frame.locator('.story-slide').nth(1).press('PageDown')
            assert frame.locator('#story-position').inner_text() == 'Section 2 / 2'
            frame.locator('#story-previous').click()
            assert frame.locator('#story-position').inner_text() == '2 / 4'
            frame.locator('.story-slide').nth(1).locator('.story-heading .story-title').click()
            frame.get_by_role('textbox',name='Edit slide title').fill('Walk through the argument')
            frame.get_by_role('textbox',name='Edit slide title').press('Tab')
            frame.get_by_role('textbox',name='Edit claim title').fill('The paired message remains editable')
            frame.get_by_role('textbox',name='Edit claim title').press('Enter')
            frame.locator('.story-slide').nth(1).press('Alt+ArrowUp')
            assert titles()[0] == 'Walk through the argument'
            assert 'Make the first ten minutes count.' in current()
            undo()
            frame.locator('button[data-story-mode="overview"]').click()
            assert frame.locator('.story-selected').get_attribute('aria-label') == 'slide: Walk through the argument'
            assert frame.locator('.story-selected .story-claim').inner_text() == 'The paired message remains editable'
            undo(); undo(); assert current() == original
            # Folding only changes Overview; Walkthrough still exposes the full story.
            frame.locator('.story-section').first.get_by_role('button',name='Fold section').click()
            assert frame.locator('.story-slide').count() == 2
            frame.locator('button[data-story-mode="walkthrough"]').click()
            assert frame.locator('.story-slide').count() == 4
            frame.locator('.story-slide').first.focus()
            frame.locator('button[data-story-mode="overview"]').click()
            assert frame.locator('.story-slide').count() == 4
            assert current() == original
            # Moving directly from one field to another must not lose the click
            # or use offsets from before the first title changed length.
            frame.locator('.story-slide .story-heading .story-title').first.click()
            frame.get_by_role('textbox',name='Edit slide title').fill('A short title')
            frame.locator('.story-slide').nth(1).locator('.story-heading .story-title').click()
            frame.get_by_role('textbox',name='Edit slide title').fill('A different title')
            frame.get_by_role('textbox',name='Edit slide title').press('Enter')
            assert titles()[:2] == ['A short title','A different title']
            undo(); undo(); assert current() == original
            # New items are inserted after the entire selected subtree.
            frame.locator('.story-slide').first.focus()
            frame.locator('#story-add-slide').click()
            frame.locator('#story-new-slide-title').fill('A new part of the argument')
            frame.locator('#story-new-claim').fill('A focused new claim')
            frame.locator('#story-new-form button[type=submit]').click()
            assert titles()[1] == 'A new part of the argument'
            assert current().index('Keep this evidence') < current().index('## A new part')
            added = frame.locator('.story-slide').nth(1)
            assert added.locator('.story-claim').inner_text() == 'A focused new claim'
            assert added.locator('.story-detail').inner_text() == 'Empty body'
            assert '## A new part of the argument\n\n### A focused new claim\n\n## A smaller' in current()
            page.screenshot(path=str(shots/'story-empty-body.png'))
            undo(); assert current() == original
            # Title and claim are one editable unit; Tab edits the paired field.
            frame.locator('.story-slide .story-heading .story-title').first.click()
            frame.get_by_role('textbox',name='Edit slide title').fill('Compact title')
            frame.get_by_role('textbox',name='Edit slide title').press('Tab')
            frame.get_by_role('textbox',name='Edit claim title').fill('A connected claim')
            frame.get_by_role('textbox',name='Edit claim title').press('Enter')
            assert frame.locator('.story-slide').first.locator('.story-claim').inner_text() == 'A connected claim'
            assert frame.locator('.story-slide').first.evaluate('(el)=>el.classList.contains("story-selected")')
            undo(); undo(); assert current() == original
            frame.locator('.story-section').first.focus()
            frame.locator('#story-add-section').click()
            frame.get_by_role('textbox',name='Edit section title').press('Enter')
            assert frame.locator('.story-section').count() == 3
            undo(); assert current() == original
            # Reorder a whole section; a single Undo restores the exact source.
            frame.locator('.story-section').nth(1).get_by_role('button',name='Move up',exact=True).click()
            assert current().index('# What we do next') < current().index('# Why now')
            assert current().startswith('\n---\ntitle: From pilot')
            undo(); assert current() == original
            # Keyboard reorder a slide with its evidence, then Undo.
            first = frame.locator('.story-slide').first
            first.focus(); first.press('Alt+ArrowDown')
            assert titles()[0].startswith('A smaller')
            assert '| New teams | 82%' in current() and 'Keep this evidence' in current()
            undo(); assert current() == original
            # Click-to-edit is a real draft transaction, including links/attributes.
            frame.locator('.story-claim .story-title').first.click()
            field = frame.get_by_role('textbox',name='Edit claim title')
            field.fill('The first ten minutes determine whether teams stay')
            assert '### The first ten minutes determine whether teams stay' in current()
            field.press('Enter')
            assert source.read_text() == original
            assert 'Unsaved' in frame.locator('#save-state').inner_text()
            frame.locator('#save').click(); wait(frame,'!matsugitWorkspace.state.saving')
            saved = source.read_text(); assert 'first ten minutes determine' in saved
            # Add a missing claim, leaving all body text untouched.
            frame.locator('.story-slide').last.get_by_role('button',name='Add claim').click()
            frame.get_by_role('textbox',name='Edit claim title').fill('Replicate the result before widening the rollout')
            frame.get_by_role('textbox',name='Edit claim title').press('Enter')
            assert '### Replicate the result before widening the rollout' in current()
            assert 'The final decision stays with this slide.' in current()
            # Move across sections via an accessible destination selector.
            first = frame.locator('.story-slide').first
            first.get_by_role('button',name='Move to...',exact=True).click()
            frame.locator('#story-move-search').fill('What we do next')
            frame.locator('#story-destinations [role=option]').first.click()
            frame.locator('#story-move-position').select_option('inside')
            frame.locator('#story-move-apply').click()
            assert titles()[-1].startswith('Demand has moved')
            assert current().index('## Demand has moved') > current().index('# What we do next')
            # Native drag/drop reorders and does not change the saved file.
            before_drag = current()
            rows = frame.locator('.story-slide')
            rows.last.get_by_role('button',name='Drag slide').drag_to(rows.first,target_position={'x':30,'y':3})
            assert titles()[0].startswith('Demand has moved')
            assert current() != before_drag and source.read_text() == saved
            undo(); assert current() == before_drag
            # Section folding is view-only; paired slides never split into separate levels.
            before = current()
            frame.locator('.story-section').first.get_by_role('button',name='Fold section').click()
            assert len(titles()) == 3
            frame.locator('.story-section').first.get_by_role('button',name='Fold section').click()
            assert current() == before
            # Saved moves make the external writer's base ambiguous. Keep the
            # title draft and require review rather than guessing its parent.
            frame.locator('#save').click(); wait(frame,'!matsugitWorkspace.state.saving')
            saved = source.read_text()
            frame.locator('.story-claim .story-title').first.click()
            field = frame.get_by_role('textbox',name='Edit claim title')
            field.fill('A deliberately edited local claim')
            local = current()
            incoming = saved.replace('The final decision stays with this slide.','New supporting evidence from the agent.')
            source.write_text(incoming)
            frame.evaluate('matsugitWorkspace.reload()'); wait(frame,'!matsugitWorkspace.state.merging')
            assert frame.evaluate('matsugitWorkspace.state.conflict && matsugitWorkspace.state.ambiguousExternal')
            assert current() == local and source.read_text() == incoming
            frame.locator('#more').click()
            frame.locator('#external-review').click()
            frame.locator('#changes-dialog').wait_for(state='visible')
            frame.locator('#changes-preview').click()
            wait(frame,'!document.getElementById("changes-apply").disabled')
            reviewed = local.replace('The final decision stays with this slide.','New supporting evidence from the agent.')
            assert frame.locator('#changes-result').input_value() == reviewed
            frame.locator('#changes-apply').click()
            wait(frame,'!document.getElementById("changes-dialog").open')
            assert current() == reviewed and source.read_text() == incoming
            assert not frame.evaluate('matsugitWorkspace.state.conflict')
            # Once reviewed, independent file edits combine while a title is
            # still being typed. Only the author's changes remain unsaved.
            frame.locator('.story-claim .story-title').first.click()
            frame.get_by_role('textbox',name='Edit claim title').fill('A deliberately edited local claim, refined')
            local = current()
            incoming = incoming.replace('Observe activation.', 'Observe the activation signal.')
            source.write_text(incoming)
            frame.evaluate('matsugitWorkspace.reload()'); wait(frame,'!matsugitWorkspace.state.merging')
            assert current() == local.replace('Observe activation.', 'Observe the activation signal.')
            assert source.read_text() == incoming
            assert not frame.evaluate('matsugitWorkspace.state.conflict')
            frame.locator('button[data-layout="story"]').click()
            frame.locator('.story-edit').wait_for(state='hidden')
            frame.locator('#story-preview').check()
            assert frame.locator('#preview-pane').is_visible()
            if os.environ.get('MATSUGIT_STORY_RENDER'):
                frame.locator('button[data-format="slides"]').click()
                wait(frame,'!!matsugitWorkspace.state.rendered?.slides && !matsugitWorkspace.state.rendering',timeout=120)
                projected = frame.frame_locator('#preview')
                projected.locator('.reveal .slides section.present').first.wait_for(state='visible',timeout=30000)
                frame.locator('#sync').check()
                frame.locator('.story-slide').nth(1).focus()
                deadline = time.monotonic()+20
                while 'Test the simpler onboarding' not in projected.locator('.reveal .slides section.present').first.inner_text():
                    if time.monotonic()>deadline: raise AssertionError('Story selection did not follow into the real slide preview')
                    time.sleep(.1)
                assert projected.locator('.reveal .slides section.present').first.bounding_box()['width'] > 100
                page.screenshot(path=str(shots/'story-with-preview.png'))
            frame.locator('#story-preview').uncheck()
            # Extremely long titles wrap; user text is never interpreted as HTML.
            frame.locator('.story-slide .story-heading .story-title').first.click()
            frame.get_by_role('textbox',name='Edit slide title').fill('Long word '+('x'*160)+' <script>window.bad=true</script>')
            frame.get_by_role('textbox',name='Edit slide title').press('Enter')
            assert not frame.evaluate('!!window.bad')
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                assert frame.evaluate('document.body.scrollWidth <= window.innerWidth')
                assert frame.evaluate('document.getElementById("story-list").scrollWidth <= document.getElementById("story-list").clientWidth')
                page.screenshot(path=str(shots/f'story-{width}.png'))
            undo()
            page.set_viewport_size({'width':1440,'height':1000})
            time.sleep(.2)
            page.screenshot(path=str(shots/'story-desktop.png'))
            # Large narrative: dense but complete, and scrolling keeps the walkthrough position.
            dense = '\n---\ntitle: Narrative map\n---\n\n'
            narrative = [
                ('Why change', [
                    ('Demand', 'Interest alone does not establish repeatable adoption'),
                    ('The bottleneck', 'First value arrives too late in the current journey'),
                    ('User effort', 'Every extra setup decision creates another exit'),
                    ('Existing strengths', 'Keep the workflow that returning teams already trust'),
                    ('Opportunity', 'A smaller first step can reveal value sooner'),
                    ('The decision', 'Test the entry experience before widening distribution')]),
                ('What changes', [
                    ('One starting point', 'Offer a useful first workflow, not a blank canvas'),
                    ('Fewer decisions', 'Defer setup that does not contribute to first value'),
                    ('Visible progress', 'Make the next step clear at every point'),
                    ('An early result', 'Let new teams experience the outcome before configuring it'),
                    ('Human support', 'Keep a direct path to help when the flow breaks'),
                    ('Scope boundary', 'Leave the established workflow unchanged for existing teams')]),
                ('How we learn', [
                    ('A focused pilot', 'Observe a small group before expanding the rollout'),
                    ('Primary measure', 'Track time to first value rather than signups alone'),
                    ('Supporting evidence', 'Pair completion data with observed user friction'),
                    ('Guardrails', 'Check that simplicity does not compromise successful use'),
                    ('Decision criteria', 'Agree what would justify expansion before the pilot starts'),
                    ('Open questions', 'Treat uncertain assumptions as tests, not conclusions')]),
                ('What happens next', [
                    ('Ownership', 'Name one accountable owner for the complete first journey'),
                    ('First delivery', 'Ship the smallest change that tests the central assumption'),
                    ('Review cadence', 'Discuss the evidence together before adding scope'),
                    ('If it works', 'Expand gradually while checking that the result repeats'),
                    ('If it does not', 'Use the observed friction to choose the next experiment'),
                    ('The ask', 'Approve a bounded pilot and a clear review point')]),
            ]
            for section, slides in narrative:
                dense += f'# {section}\n\n'
                for title, claim in slides:
                    dense += f'## {title}\n### {claim}\n\nEvidence stays attached.\n\n'
            frame.evaluate('(text)=>matsugitWorkspace.load({name:"map.md",text,writable:false},{acceptRevision:matsugitWorkspace.state.revision})',dense)
            wait(frame,'!matsugitWorkspace.state.loading')
            frame.locator('button[data-story-mode="overview"]').click()
            assert frame.locator('.story-slide').count() == 24
            visible = frame.locator('.story-slide').evaluate_all('(rows)=>{const box=document.getElementById("story-list").getBoundingClientRect();return rows.filter(r=>{const b=r.getBoundingClientRect();return b.top>=box.top && b.bottom<=box.bottom}).length}')
            assert visible >= 14, visible
            time.sleep(4.1)
            page.screenshot(path=str(shots/'story-map.png'))
            frame.locator('button[data-story-mode="walkthrough"]').click()
            frame.locator('.story-slide').nth(12).evaluate('(el)=>el.scrollIntoView({block:"start"})')
            wait(frame,'document.getElementById("story-position").textContent === "13 / 24"')
            assert current() == dense
            page.screenshot(path=str(shots/'story-walkthrough-map.png'))
            for mode in ('overview','walkthrough'):
                frame.locator(f'button[data-story-mode="{mode}"]').click()
                for width in (390,800,1440):
                    page.set_viewport_size({'width':width,'height':1000})
                    page.screenshot(path=str(shots/f'story-{mode}-{width}.png'))
                    assert frame.evaluate('document.body.scrollWidth <= window.innerWidth')
                    assert frame.evaluate('document.getElementById("story-list").scrollWidth <= document.getElementById("story-list").clientWidth'), (mode,width,frame.locator('#story-list').evaluate('(el)=>({client:el.clientWidth,scroll:el.scrollWidth,rows:[...el.children].slice(0,3).map(r=>({width:r.offsetWidth,scroll:r.scrollWidth}))})'))
                    if width == 390: page.screenshot(path=str(shots/f'story-{mode}-mobile.png'))
            frame.locator('button[data-story-mode="overview"]').click()
            # Native Org gets the same editor without converting the source.
            org = '#+title: Plan\n\n* Direction\n** First\n:PROPERTIES:\n:CUSTOM_ID: stable\n:END:\n\nEvidence\n\n** Second\n*** Existing claim\n\nBody\n'
            frame.evaluate('(text)=>matsugitWorkspace.load({name:"plan.org",text,writable:false},{acceptRevision:matsugitWorkspace.state.revision})',org)
            wait(frame,'!matsugitWorkspace.state.loading')
            frame.locator('button[data-layout="story"]').click()
            frame.locator('.story-slide').first.get_by_role('button',name='Add claim').click()
            frame.get_by_role('textbox',name='Edit claim title').fill('New claim')
            frame.get_by_role('textbox',name='Edit claim title').press('Enter')
            assert ':CUSTOM_ID: stable\n:END:\n\n*** New claim' in current()
            frame.locator('.story-slide').last.get_by_role('button',name='Move up',exact=True).click()
            assert current().index('** Second') < current().index('** First')
            assert ':CUSTOM_ID: stable' in current() and '#+title: Plan' in current()
            assert not errors, errors
            print(f'PASS: Story editing, subtree moves, drag, keyboard, undo, save, external merge, folding, responsive layout; screenshots {shots}',flush=True)
            browser.close()
    finally:
        host.terminate(); host.wait(timeout=20)
