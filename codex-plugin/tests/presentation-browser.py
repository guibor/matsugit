"""Check presentation with an existing synthetic, self-contained demo HTML."""
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    for width, height in ((1440, 900), (390, 844), (320, 700)):
        page = browser.new_page(viewport={'width': width, 'height': height})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(Path(sys.argv[1]).resolve().as_uri())
        page.wait_for_function('!!window.matsugitWorkspace?.state.rendered')
        # Simulate the fullscreen restriction common to embedded hosts.
        page.evaluate("() => { document.documentElement.requestFullscreen = () => Promise.reject(new Error('Host restriction')); }")
        page.locator('#present').click()
        page.mouse.move(0, 0)
        exit_button = page.get_by_role('button', name='Exit presentation', exact=True)
        assert exit_button.inner_text() == 'Exit presentation'
        assert exit_button.is_visible()
        assert page.locator('#presentation-controls').evaluate('e=>getComputedStyle(e).opacity') == '1'
        controls = page.locator('#presentation-controls').bounding_box()
        assert controls['x'] >= 0 and controls['x'] + controls['width'] <= width
        assert controls['y'] >= 0 and controls['y'] + controls['height'] <= height
        assert exit_button.evaluate('e=>e.scrollWidth <= e.clientWidth')
        frame = page.locator('#preview').element_handle().content_frame()
        assert page.evaluate('matsugitWorkspace.state.format') == 'document'
        assert frame.locator('main').is_visible()
        assert page.locator('header').is_hidden()
        bounds = page.locator('#preview').bounding_box()
        assert bounds['width'] == width and bounds['height'] == height
        page.locator('#present-next').click()
        frame.wait_for_function('scrollY > 0')
        exit_button.click()
        page.wait_for_function('!document.body.classList.contains("presenting")')
        assert page.evaluate('matsugitWorkspace.state.layout') == 'split'
        assert page.locator('#present').evaluate('(button) => button === document.activeElement')
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
        if os.environ.get('MATSUGIT_SCREENSHOTS'):
            shots = Path(os.environ['MATSUGIT_SCREENSHOTS'])
            shots.mkdir(parents=True, exist_ok=True)
            page.locator('#present').click()
            page.mouse.move(0, 0)
            page.screenshot(path=str(shots / f'presentation-exit-{width}.png'))
            exit_button.click()
            assert page.evaluate('matsugitWorkspace.state.layout') == 'split'
        assert not errors, errors
        print(f'Present, visible exit, navigation, fullscreen fallback and return passed: {width}x{height}')
        page.close()
    browser.close()
