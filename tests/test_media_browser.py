"""Opt-in rendered-media checks, using only the synthetic fixture."""
import os
from pathlib import Path
import tempfile
import unittest

from matsugit.core import config, render


@unittest.skipUnless(os.environ.get('MATSUGIT_MEDIA_BROWSER_TESTS'), 'Opt-in media browser tests')
class MediaBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(os.environ.get('MATSUGIT_MEDIA_OUTPUT', cls.temp.name))
        if not os.environ.get('MATSUGIT_MEDIA_OUTPUT'):
            render(config(Path(__file__).parent / 'fixtures/media.md'), cls.output)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(executable_path=os.environ['CHROME'],
                                                   args=['--no-sandbox', '--disable-dev-shm-usage'])
        cls.addClassCleanup(cls.browser.close)

    def test_local_document_and_slides_fit_desktop_mobile_and_resize(self):
        for viewport in ({'width':1440,'height':900}, {'width':390,'height':844}):
            page = self.browser.new_page(viewport=viewport)
            self.addCleanup(page.close)
            page.route('https://cdn.jsdelivr.net/npm/mathjax@**', lambda route: route.abort())
            errors, remote = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: remote.append(r.url) if r.url.startswith(('https:', 'http:')) else None)
            page.goto((self.output / 'index.html').as_uri())
            page.wait_for_function('document.querySelectorAll("svg.mermaid-js").length === 3')
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
            self.assertEqual(page.locator('img').evaluate_all('(els)=>els.filter(e=>!e.complete || !e.naturalWidth).length'), 0)
            page.goto((self.output / 'slides.html').as_uri())
            page.wait_for_function('window.Reveal && Reveal.isReady() && document.querySelectorAll("svg.mermaid-js").length === 3')
            # Mobile scroll view also exposes an anonymous stack wrapper.
            ids = page.evaluate('Reveal.getSlides().map(s=>s.id).filter(Boolean)')
            for slide_id in ids:
                page.evaluate('''id => {
                  const s=document.getElementById(id), i=Reveal.getIndices(s);
                  if (Reveal.isScrollView?.()) s.scrollIntoView({behavior:'instant',block:'center'});
                  else Reveal.slide(i.h,i.v);
                }''', slide_id)
                try:
                    page.wait_for_function('(id)=>Reveal.getCurrentSlide().id === id', arg=slide_id, timeout=5000)
                except Exception:
                    self.fail(f'{viewport}: expected {slide_id}, current {page.evaluate("Reveal.getCurrentSlide().id")}')
                page.wait_for_timeout(400)
                metrics = page.evaluate('''() => {
                  const s=Reveal.getCurrentSlide(), sr=s.getBoundingClientRect();
                  const slots=[...s.querySelectorAll('.ff-media')];
                  const title=s.querySelector('h3') || s.querySelector('h2');
                  const takeaway=s.querySelector('.takeaway');
                  return slots.map(slot=>{
                    const r=slot.getBoundingClientRect(), media=slot.querySelector('img,svg.mermaid-js');
                    const m=media.getBoundingClientRect();
                    const column=slot.closest('.column'), cr=column?.getBoundingClientRect();
                    return {w:m.width,h:m.height, fitted:slot.classList.contains('ff-fitted'),
                      inside:r.bottom<=sr.bottom+2 && r.left>=sr.left-2 && r.right<=sr.right+2,
                      belowTitle:!title || r.top>=title.getBoundingClientRect().bottom-2,
                      aboveTakeaway:!takeaway || r.bottom<=takeaway.getBoundingClientRect().top+2,
                      inColumn:!cr || m.width<=cr.width+2,
                      fit:media.tagName==='IMG' ? getComputedStyle(media).objectFit : media.getAttribute('preserveAspectRatio')};
                  });
                }''')
                for m in metrics:
                    self.assertGreater(m['w'], 20, (slide_id,m))
                    self.assertGreater(m['h'], 20, (slide_id,m))
                    for flag in ('fitted','inside','belowTitle','aboveTakeaway','inColumn'):
                        self.assertTrue(m[flag], (slide_id,m))
                    self.assertIn(m['fit'], ('contain','xMidYMid meet'))
            self.assertFalse(errors, errors)
            # Reveal's pre-existing MathJax plugin may fetch its math runtime.
            # Mermaid and the new media fitter must not introduce network loads.
            unexpected = [url for url in remote if not url.startswith('https://cdn.jsdelivr.net/npm/mathjax@')]
            self.assertFalse(unexpected, unexpected)
