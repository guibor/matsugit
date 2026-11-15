"""Explicit shallow media heights must survive the shared rendering pipeline."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from matsugit.core import config, normalize, render

QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))
@unittest.skipUnless(QUARTO, 'Quarto required')
class FixedMediaTests(unittest.TestCase):
    def fixture(self, root):
        (root/'triangle.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="28" viewBox="0 0 1120 28"><path d="M0 0H1120L560 28Z" fill="#2e5bb8"/></svg>')
        source=root/'deck.md'
        row='::::: columns\n' + ''.join(':::: column\n#### '+title+'\n\n'+words+'\n::::\n' for title,words in
            [('Inputs','Several inputs interact.'),('History','Observations are sparse.'),('Evidence','Availability changes observations.')]) + ':::::\n'
        source.write_text('---\nslide-layout: structured\n---\n\n## Challenges and implications\n\n### Three challenges lead to three requirements\n\n'+row+'\n![](triangle.svg){width=95% height=28px}\n\n'+row)
        return source

    def test_explicit_height_survives_normalization_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=self.fixture(root)
            first=root/'one'; first.mkdir(); second=root/'two'; second.mkdir()
            normalize(config(source,{'quarto':QUARTO,'theme':'default'}),first)
            normalize(config(first/'source.md',{'quarto':QUARTO,'theme':'default'}),second)
            self.assertEqual((first/'source.md').read_text(),(second/'source.md').read_text())
            self.assertIn('ff-media-fixed',(first/'source.md').read_text())
            self.assertIn('--ff-image-height:28px',(first/'source.md').read_text())

    def test_real_shallow_triangle_is_not_a_flexible_media_slot(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright required for geometry')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=self.fixture(root); output=root/'render'
            render(config(source,{'quarto':QUARTO,'theme':'default'}),output,formats=('slides',))
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.goto((output/'slides.html').as_uri())
                page.wait_for_function('window.Reveal?.isReady()')
                page.evaluate('Reveal.slide(0)')
                page.wait_for_function('document.querySelector(".ff-media-fixed img")?.complete')
                page.wait_for_timeout(500)
                metrics=page.evaluate('''() => { const slot=document.querySelector('.ff-media-fixed'), image=slot.querySelector('img');
                    return {height:parseFloat(getComputedStyle(image).height), slot:slot.offsetHeight,
                      flexible:slot.classList.contains('ff-fitted'), loaded:image.naturalWidth>0}; }''')
                self.assertTrue(metrics['loaded']); self.assertFalse(metrics['flexible'])
                self.assertAlmostEqual(metrics['height'],28,delta=1)
                self.assertLessEqual(metrics['slot'],40,metrics)
                page.screenshot(path='/tmp/matsugit-shallow-triangle.png')
                browser.close()
