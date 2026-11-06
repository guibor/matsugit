"""Section transitions and compact Story layout, without changing a real deck."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def wait(frame, expression):
    deadline = time.monotonic()+30
    while not frame.evaluate(expression):
        assert time.monotonic() < deadline, expression
        time.sleep(.05)


with tempfile.TemporaryDirectory(prefix='matsugit-story-layout-') as tmp:
    source = '---\ntitle: A focused pilot\nslide-section-dividers: false\n---\n\n'
    for name in ('Understand the opportunity','Test the smallest change','Decide from evidence'):
        source += '# '+name+'\n\n'
        for title,claim in [('Demand','Interest must turn into repeated use'),
                            ('First value','A smaller first step reveals the outcome sooner'),
                            ('Evidence','Measure completion as well as the time it takes'),
                            ('Guardrails','Keep what already works for returning teams')]:
            source += f'## {title}\n### {claim}\n\nEvidence stays with this slide.\n\n::: takeaway\nMake the next decision small and testable.\n:::\n\n'
    source += '# Open questions\n\n'
    fixture = Path(tmp)/'narrative.md'; fixture.write_text(source)
    host = subprocess.Popen(['node',str(ROOT/'codex-plugin/tests/browser-host.mjs')],stdout=subprocess.PIPE,
        text=True,env=dict(os.environ,MATSUGIT_SHOWCASE_SOURCE=str(fixture),QUARTO='/missing-editor-test'))
    try:
        ready = json.loads(host.stdout.readline())
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{ready["port"]}')
            frame=page.frames[1]
            wait(frame,'!!window.matsugitWorkspace?.state.etag && !matsugitWorkspace.state.loading')
            frame.locator('#auto').uncheck()
            frame.locator('button[data-layout="story"]').click()
            frame.locator('.story-slide').first.wait_for()
            assert frame.locator('#story-size').is_hidden()
            revision=frame.evaluate('matsugitWorkspace.state.revision')
            def current(): return frame.evaluate('matsugitWorkspace.editor.state.doc.toString()')
            def selected(): return frame.locator('.story-selected').count()
            def source_unchanged():
                assert current() == source
                assert frame.evaluate('matsugitWorkspace.state.revision') == revision
                assert Path(ready['source']).read_text() == source
            def position(): return frame.locator('#story-position').inner_text()
            listing=frame.locator('#story-list')
            frame.locator('button[data-story-mode="walkthrough"]').click()
            assert frame.locator('#story-size').is_visible()
            assert frame.locator('button[data-story-size="large"]').get_attribute('aria-pressed') == 'true'
            sections=frame.locator('.story-section'); slides=frame.locator('.story-slide')
            assert sections.count() == 4 and slides.count() == 12
            assert frame.get_by_role('button',name='Fold section').count() == 0
            assert position() == 'Section 1 / 4', position()
            section_height=sections.first.bounding_box()['height']
            assert section_height >= 400
            assert abs(section_height-slides.first.bounding_box()['height']) < 2
            assert sections.first.evaluate('(el)=>getComputedStyle(el).backgroundColor') != slides.first.evaluate('(el)=>getComputedStyle(el).backgroundColor')
            assert sections.first.locator('.story-title').evaluate('(el)=>getComputedStyle(el).color') == 'rgb(255, 255, 255)'
            # Next/previous stop at section transitions, even without selection.
            frame.locator('#story-next').click(); assert position() == '1 / 12'
            frame.locator('#story-previous').click(); assert position() == 'Section 1 / 4'
            assert selected() == 0
            slides.nth(3).focus(); slides.nth(3).press('ArrowDown')
            assert frame.locator('.story-selected').get_attribute('aria-label') == 'section: Test the smallest change'
            assert position() == 'Section 2 / 4'
            frame.locator('#story-next').click(); assert position() == '5 / 12'
            frame.locator('.story-selected').press('End')
            assert position() == 'Section 4 / 4' and frame.locator('#story-next').is_disabled()
            frame.locator('.story-selected').press('Escape'); assert selected() == 0
            listing.press('Home')
            frame.locator('button[data-story-size="compact"]').click()
            assert selected() == 0 and position() == 'Section 1 / 4'
            first=slides.first.bounding_box(); second=slides.nth(1).bounding_box()
            assert first['width'] < 500 and abs(first['y']-second['y']) < 2
            assert sections.first.bounding_box()['width'] > first['width']*2
            assert sections.first.bounding_box()['height'] < section_height
            assert first['height'] < section_height
            assert slides.first.get_by_role('button',name='Edit slide with AI').count() == 1
            for expected in ('1 / 12','2 / 12','3 / 12','4 / 12','Section 2 / 4'):
                frame.locator('#story-next').click()
                assert position() == expected, (position(),expected)
                assert selected() == 0
            # Compact vertical navigation follows grid rows; horizontal follows order.
            slides.first.focus(); slides.first.press('ArrowRight')
            assert frame.locator('.story-selected').get_attribute('data-from') == slides.nth(1).get_attribute('data-from')
            frame.locator('.story-selected').press('ArrowDown')
            assert frame.locator('.story-selected').get_attribute('aria-label') == 'section: Test the smallest change'
            frame.locator('.story-selected').press('ArrowUp')
            assert frame.locator('.story-selected').get_attribute('data-from') in [slides.nth(i).get_attribute('data-from') for i in range(4)]
            frame.locator('.story-selected').press('Escape')
            listing.press('Home'); listing.press('j')
            assert selected() == 0 and listing.evaluate('(el)=>el.scrollTop') > 0
            listing.press('Home'); listing.press('l')
            assert selected() == 0 and position() == 'Section 2 / 4'
            listing.press('h'); assert position() == 'Section 1 / 4'
            source_unchanged()
            # Preferences survive recovery, not the source document.
            frame.evaluate('matsugitWorkspace.flushRecovery()')
            records=list(Path(ready['recovery']).glob('*.json'))
            assert any(json.loads(record.read_text()).get('view',{}).get('storySize') == 'compact' for record in records)
            # Edit a transition title, move the section with its children, Undo.
            sections.first.locator('.story-title').click()
            field=frame.get_by_role('textbox',name='Edit section title')
            field.fill('A clearer direction'); field.press('Enter')
            assert '# A clearer direction\n' in current()
            sections.first.get_by_role('button',name='Move down',exact=True).click()
            assert current().index('# A clearer direction') > current().index('# Test the smallest change')
            assert current().count('Evidence stays with this slide.') == 12
            frame.locator('#undo').click(); time.sleep(.1)
            frame.locator('#undo').click(); time.sleep(.1)
            assert current() == source
            revision=frame.evaluate('matsugitWorkspace.state.revision')
            # Switching size retains a selected slide; Overview stays dense.
            slides.nth(5).focus()
            anchor=frame.locator('.story-selected').get_attribute('data-from')
            for size in ('large','compact'):
                frame.locator(f'button[data-story-size="{size}"]').click()
                assert frame.locator('.story-selected').get_attribute('data-from') == anchor
            frame.locator('button[data-story-mode="overview"]').click()
            assert frame.locator('#story-size').is_hidden()
            assert frame.get_by_role('button',name='Fold section').count() == 4
            assert sections.first.bounding_box()['height'] < 70
            frame.locator('button[data-story-mode="walkthrough"]').click()
            assert frame.locator('button[data-story-size="compact"]').get_attribute('aria-pressed') == 'true'
            # Both sizes fit the full and split panes. Capture synthetic examples.
            for size in ('large','compact'):
                frame.locator(f'button[data-story-size="{size}"]').click()
                for width in (390,800,1440,1920):
                    page.set_viewport_size({'width':width,'height':1000})
                    time.sleep(.1)
                    overflow=frame.locator('.story-row').evaluate_all('(rows)=>rows.filter(r=>r.scrollWidth>r.clientWidth+2 || r.scrollHeight>r.clientHeight+2).map(r=>({kind:r.className,width:r.clientWidth,scrollWidth:r.scrollWidth,height:r.clientHeight,scrollHeight:r.scrollHeight,children:[...r.children].map(c=>({kind:c.className,width:c.clientWidth,scrollWidth:c.scrollWidth,height:c.clientHeight,scrollHeight:c.scrollHeight}))}))')
                    assert not overflow, (size,width,overflow)
                    assert listing.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
                    if os.environ.get('MATSUGIT_TEST_ARTIFACTS') and width in (390,1440):
                        directory=Path(os.environ['MATSUGIT_TEST_ARTIFACTS']); directory.mkdir(parents=True,exist_ok=True)
                        listing.click(position={'x':2,'y':2}); listing.press('Home')
                        page.screenshot(path=str(directory/f'story-{size}-{width}.png'))
                frame.locator('#story-preview').check()
                time.sleep(.2)
                assert not frame.locator('.story-row').evaluate_all('(rows)=>rows.some(r=>r.scrollWidth>r.clientWidth+2)')
                frame.locator('#story-preview').uncheck()
            source_unchanged()
            # Long section names wrap, and native Org has the same transitions.
            org='#+title: Plan\n* '+('Long section '*30)+'\n** First\n*** Claim\n#+begin_takeaway\nDecision\n#+end_takeaway\n* Empty section\n'
            frame.evaluate('(text)=>matsugitWorkspace.load({name:"plan.org",text,writable:false},{acceptRevision:matsugitWorkspace.state.revision})',org)
            wait(frame,'!matsugitWorkspace.state.loading && matsugitWorkspace.state.name === "plan.org"')
            frame.locator('button[data-layout="story"]').click()
            frame.locator('button[data-story-mode="walkthrough"]').click()
            for size in ('large','compact'):
                frame.locator(f'button[data-story-size="{size}"]').click()
                for width in (390,1440):
                    page.set_viewport_size({'width':width,'height':900}); time.sleep(.1)
                    assert sections.count() == 2
                    assert not frame.locator('.story-row').evaluate_all('(rows)=>rows.some(r=>r.scrollWidth>r.clientWidth+2 || r.scrollHeight>r.clientHeight+2)')
            assert current() == org
            assert not errors,errors
            browser.close()
            print('PASS: section transitions, compact grid, traversal and selection, edit/move/undo, recovery, responsive layout, Org and unchanged source')
    finally:
        host.terminate(); host.wait(timeout=20)
