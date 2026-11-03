"""Canvas expansion in the shared workspace, including nested Present/Escape."""
import os
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    for width, height in ((1440, 900), (390, 844)):
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.route('http*://**', lambda route: route.abort())
        page.goto(Path(sys.argv[1]).resolve().as_uri())
        page.wait_for_function('!!window.matsugitWorkspace?.state.rendered')
        page.evaluate("() => { document.documentElement.requestFullscreen = () => Promise.reject(new Error('Host restriction')); }")
        for fmt in ('document', 'slides'):
            page.locator(f'[data-format="{fmt}"]').click()
            page.locator('#present').click()
            preview = page.locator('#preview').element_handle().content_frame()
            if fmt == 'slides':
                preview.wait_for_function('window.Reveal?.isReady()')
                preview.evaluate('Reveal.slide(1)')
            preview.locator('.ff-canvas-expand').click()
            visual = preview.locator('.ff-canvas-frame').element_handle().content_frame()
            visual.locator('#increment').click()
            expect(visual.locator('#value')).to_have_text('1')
            if os.environ.get('MATSUGIT_SCREENSHOTS'):
                output = Path(os.environ['MATSUGIT_SCREENSHOTS'])
                output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output / f'canvas-{fmt}-{width}.png'))
            preview.locator('.ff-canvas-expand').focus()
            page.keyboard.press('Escape')
            assert not preview.locator('.ff-canvas-dialog').evaluate('el => el.matches(":modal")')
            assert page.evaluate('document.body.classList.contains("presenting")')
            expect(visual.locator('#value')).to_have_text('1')
            preview.locator('body').press('Escape')
            page.wait_for_function('!document.body.classList.contains("presenting")')
            assert page.evaluate('matsugitWorkspace.state.layout') == 'split'
        page.close()
        print(f'Canvas in shared Document/Slides Present: {width}x{height}')
    browser.close()
