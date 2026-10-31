"""Optional cross-theme check of the two relationship composition examples."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('FOLIOFORGE_COMPOSITIONS_OUTPUT'),
                     'Render examples/relationship-compositions.md first')
class CompositionBrowserTests(unittest.TestCase):
    def test_dense_panels_and_paired_rows_on_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright
        root = Path(os.environ['FOLIOFORGE_COMPOSITIONS_OUTPUT'])
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get('FOLIOFORGE_CHROMIUM'),
                args=['--no-sandbox', '--disable-dev-shm-usage'])
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route('http://**', lambda r: r.abort())
                page.route('https://**', lambda r: r.abort())
                for width, height in ((1440, 900), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.goto((root / 'slides.html').as_uri())
                    page.wait_for_function('window.Reveal?.isReady()')
                    page.wait_for_timeout(600)
                    self.assertEqual(page.evaluate('Reveal.getSlides().length'), 2)
                    for index in range(2):
                        if page.evaluate('Reveal.isScrollView()'):
                            if index:
                                page.keyboard.press('ArrowRight')
                        else:
                            page.evaluate('i=>Reveal.slide(i,0)', index)
                        page.wait_for_timeout(500)
                        page.wait_for_function('i=>Reveal.getCurrentSlide()===Reveal.getSlides()[i]', arg=index)
                        result = page.evaluate('''()=>{
                          const s=Reveal.getCurrentSlide();
                          const hs=[...s.querySelectorAll('.ff-division-heading,.ff-mapping-head>.ff-mapping-cell')];
                          const arrows=[...s.querySelectorAll('.ff-implication>.ff-relation,.ff-mapping-row>.ff-relation')];
                          return {overflow:s.scrollHeight>s.clientHeight+2||s.scrollWidth>s.clientWidth+2,
                            aligned:Math.abs(hs[0].getBoundingClientRect().top-hs[1].getBoundingClientRect().top)<1,
                            triangles:arrows.every(a=>{const c=getComputedStyle(a,'::before'),r=parseFloat(c.height)/parseFloat(c.width);
                              return a.parentElement.classList.contains('ff-implication')?r>6:Math.abs(r-2)<.05}),
                            arrows:arrows.length};
                        }''')
                        self.assertFalse(result['overflow'], (width, index, result))
                        self.assertTrue(result['aligned'] and result['triangles'], result)
                        self.assertEqual(result['arrows'], 1 if index == 0 else 4)
                    page.goto((root / 'index.html').as_uri())
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))
                    self.assertEqual(page.locator('.ff-mapping-row').count(), 4)
                self.assertEqual(errors, [])
            finally:
                browser.close()
