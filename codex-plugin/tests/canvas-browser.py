"""Inspect local canvas output, including sandbox, expansion and persistent state."""
import os
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
    for width, height in ((1440,900), (390,844)):
        for name in ('index.html', 'slides.html'):
            print(f'Checking {name} at {width}x{height}', flush=True)
            page = browser.new_page(viewport={'width':width, 'height':height})
            page.bring_to_front()
            outbound = []
            def route_request(route):
                if route.request.url.startswith(('http:', 'https:')):
                    if route.request.frame.url == 'about:srcdoc':
                        outbound.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*', route_request)
            page.goto((Path(sys.argv[1]) / name).resolve().as_uri())
            if name == 'slides.html':
                page.wait_for_function('window.Reveal?.isReady()')
                page.evaluate('''() => {
                  const slide = document.querySelector('.ff-canvas-frame').closest('section');
                  if (Reveal.isScrollView?.()) slide.scrollIntoView({behavior:'instant', block:'center'});
                  else { const i = Reveal.getIndices(slide); Reveal.slide(i.h, i.v); }
                }''')
                page.wait_for_function('Reveal.getCurrentSlide()?.querySelector(".ff-canvas-frame") && Reveal.getCurrentSlide().dataset.ffMediaReady === "true"')
                # Iframe-local actionability does not await its ancestor's slide transform.
                page.wait_for_timeout(1000)
            frame = page.locator('.ff-canvas-frame').element_handle().content_frame()
            expect(frame.locator('#increment')).to_be_visible()
            assert page.locator('.ff-canvas-frame').evaluate('el => el.inert')
            expect(frame.locator('#value')).to_have_text('0')
            assert frame.evaluate('try { void parent.document; false } catch { true }')
            page.locator('.ff-canvas-expand').click()
            assert page.locator('.ff-canvas-dialog').evaluate('el => el.matches(":modal")')
            bounds = page.locator('.ff-canvas-dialog').bounding_box()
            assert bounds['x'] >= 0 and bounds['y'] >= 0
            assert bounds['width'] >= width * .85 and bounds['height'] >= height * .85
            assert not page.locator('.ff-canvas-frame').evaluate('el => el.inert')
            frame.locator('#increment').click()
            expect(frame.locator('#value')).to_have_text('1')
            page.locator('.ff-canvas-expand').click()
            assert not page.locator('.ff-canvas-dialog').evaluate('el => el.matches(":modal")')
            assert frame.locator('#value').inner_text() == '1'
            # Escape closes only the canvas and leaves its state intact.
            page.locator('.ff-canvas-expand').click()
            frame.locator('#increment').click()
            expect(frame.locator('#value')).to_have_text('2')
            page.locator('.ff-canvas-expand').focus()
            page.keyboard.press('Escape')
            assert not page.locator('.ff-canvas-dialog').evaluate('el => el.matches(":modal")')
            assert frame.locator('#value').inner_text() == '2'
            assert not outbound, outbound
            page.close()
    browser.close()
print('Document/slide canvas, opaque sandbox, expansion, state retention and no network passed at desktop/mobile sizes')
