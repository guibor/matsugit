"""Check presentation with an existing synthetic, self-contained demo HTML."""
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    for width, height in ((1440, 900), (390, 844)):
        page = browser.new_page(viewport={'width': width, 'height': height})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(Path(sys.argv[1]).resolve().as_uri())
        page.wait_for_function('!!window.matsugitWorkspace?.state.rendered')
        # Simulate the fullscreen restriction common to embedded hosts.
        page.evaluate("() => { document.documentElement.requestFullscreen = () => Promise.reject(new Error('Host restriction')); }")
        page.locator('#present').click()
        frame = page.locator('#preview').element_handle().content_frame()
        assert page.evaluate('matsugitWorkspace.state.format') == 'document'
        assert frame.locator('main').is_visible()
        assert page.locator('header').is_hidden()
        bounds = page.locator('#preview').bounding_box()
        assert bounds['width'] == width and bounds['height'] == height
        page.locator('#present-next').click()
        frame.wait_for_function('scrollY > 0')
        frame.locator('body').press('Escape')
        page.wait_for_function('!document.body.classList.contains("presenting")')
        assert page.evaluate('matsugitWorkspace.state.layout') == 'split'
        page.locator('[data-format="slides"]').click()
        page.locator('#present').click()
        preview = page.frame_locator('#preview')
        preview.locator('.reveal.ready').wait_for()
        frame = page.locator('#preview').element_handle().content_frame()
        assert page.locator('header').is_hidden()
        bounds = page.locator('#preview').bounding_box()
        assert bounds['width'] == width and bounds['height'] == height
        before = frame.evaluate('Reveal.getIndices().h')
        page.locator('#present-next').click()
        frame.wait_for_function(f'Reveal.getIndices().h > {before}')
        page.locator('#present-previous').click()
        frame.wait_for_function(f'Reveal.getIndices().h === {before}')
        frame.locator('body').press('ArrowRight')
        frame.wait_for_function(f'Reveal.getIndices().h > {before}')
        frame.locator('body').press('Escape')
        page.wait_for_function('!document.body.classList.contains("presenting")')
        assert page.locator('header').is_visible()
        assert page.evaluate('matsugitWorkspace.state.layout') == 'split'
        assert page.evaluate('matsugitWorkspace.state.format') == 'slides'
        assert page.locator('#sync').is_checked()
        assert not errors, errors
        print(f'Present, navigation, fullscreen fallback and return passed: {width}x{height}')
        page.close()
    browser.close()
