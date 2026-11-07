"""Actual Org/Markdown render parity; requires the synthetic recipe previews."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('MATSUGIT_ORG_PREVIEWS'), 'Render the Org/Markdown recipe corpus first')
class OrgBrowserTests(unittest.TestCase):
    def test_rendered_recipes_and_hidden_comments(self):
        from playwright.sync_api import sync_playwright
        root = Path(os.environ['MATSUGIT_ORG_PREVIEWS'])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('MATSUGIT_CHROMIUM'),
                                        args=['--no-sandbox'])
            try:
                observed = {}
                for variant in ('md-theme-a', 'org-theme-a', 'org-theme-b'):
                    folder = root / variant
                    self.assertTrue((folder / 'slides.html').is_file(), str(folder))
                    for file in folder.rglob('*'):
                        if file.is_file() and file.suffix in ('.html', '.md', '.org', '.qmd', '.json'):
                            self.assertNotIn('HIDDEN_REVIEW_SENTINEL', file.read_text(), str(file))
                    for width, height in ((1440, 900), (390, 844)):
                        page = browser.new_page(viewport={'width': width, 'height': height})
                        page.route('http://**', lambda route: route.abort())
                        page.route('https://**', lambda route: route.abort())
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto((folder/'slides.html').as_uri())
                        page.wait_for_function('window.Reveal?.isReady()')
                        page.wait_for_timeout(800)
                        self.assertEqual(page.evaluate('Reveal.getSlides().length'), 16)
                        texts = []
                        for i in range(16):
                            if page.evaluate('Reveal.isScrollView()'):
                                if i:
                                    page.keyboard.press('ArrowRight')
                            else:
                                page.evaluate('i=>{const n=Reveal.getIndices(Reveal.getSlides()[i]);Reveal.slide(n.h,n.v)}', i)
                            page.wait_for_function('i=>Reveal.getCurrentSlide()===Reveal.getSlides()[i]', arg=i)
                            page.wait_for_timeout(300)
                            info = page.evaluate('''()=>{
                              const s=Reveal.getCurrentSlide();
                              const parts=[...s.querySelectorAll(':scope>h2,:scope>.ff-claim,:scope>.ff-body,:scope>.ff-takeaway')].filter(e=>e.getBoundingClientRect().height).sort((a,b)=>a.getBoundingClientRect().top-b.getBoundingClientRect().top);
                              return {id:s.id,text:s.innerText.replace(/\\s+/g,' ').trim(),
                                overflow:s.scrollHeight>s.clientHeight+2||s.scrollWidth>s.clientWidth+2,
                                overlap:parts.some((e,j)=>j&&e.getBoundingClientRect().top<parts[j-1].getBoundingClientRect().bottom-1),
                                images:[...s.querySelectorAll('img')].every(e=>e.complete&&e.naturalWidth>0)};
                            }''')
                            self.assertFalse(info['overflow'] or info['overlap'], (variant, width, i, info))
                            self.assertTrue(info['images'], (variant, i))
                            texts.append(info['text'])
                            if width == 1440 and i in (3, 6, 8, 13, 14, 15):
                                page.screenshot(path=str(root/f'{variant}-{i}.png'))
                        self.assertGreater(page.locator('.mermaid svg, svg.mermaid-js').count(), 0)
                        observed[(variant, width)] = texts
                        page.goto((folder/'index.html').as_uri())
                        page.wait_for_timeout(500)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth+2'))
                        self.assertEqual(errors, [])
                        page.close()
                for width in (1440, 390):
                    self.assertEqual(observed[('md-theme-a', width)], observed[('org-theme-a', width)])
            finally:
                browser.close()
