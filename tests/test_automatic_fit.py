import os
from pathlib import Path
import unittest
import shutil
import tempfile


class AutomaticFitTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('QUARTO', shutil.which('quarto')), 'Quarto required')
    def test_real_renderer_and_pdf(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright required')
        from matsugit.core import config, render
        from matsugit.exports import browser_artifacts
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'deck.md'
            source.write_text('---\nslide-layout: structured\n---\n\n## Evidence and implications\n\n### A fixed claim\n\n:::: columns\n\n#### Evidence\n\n' +
                              ('A considered statement about the evidence. ' * 10) +
                              '\n\n#### Implications\n\nA short peer paragraph.\n\n::::\n')
            before = source.read_bytes()
            output = root / 'render'
            render(config(source, {'theme':'default'}), output, formats=('slides',))
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
                page = browser.new_page(viewport={'width':1440,'height':1000})
                page.goto((output/'slides.html').as_uri())
                page.wait_for_function('window.Reveal?.isReady() && !!window.matsugitFit?.fitAll')
                reports = page.evaluate('matsugitFit.fitAll().filter(Boolean)')
                self.assertTrue(reports)
                page.screenshot(path='/tmp/matsugit-auto-fit-rendered.png')
                browser.close()
            browser_artifacts(output, root/'deck.pdf')
            self.assertTrue((root/'deck.pdf').read_bytes().startswith(b'%PDF-'))
            self.assertEqual(source.read_bytes(), before)

    def test_bounded_peer_fitting_and_reset(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Playwright required')
        runtime = Path(__file__).resolve().parents[1] / 'matsugit/runtime/fit.js'
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
            page = browser.new_page(viewport={'width':1200,'height':900})
            page.set_content('''<style>
              section {width:900px;font:28px/1.3 Arial} h2{font-size:48px;margin:0}
              .ff-claim{font-size:24px} .columns{display:flex;gap:30px}
              .column{width:435px} h4{font-size:28px;margin:10px 0}
              p{margin:15px 0} .source{font-size:16px}
              </style><div class="reveal"><div class="slides"><section id="slide">
              <h2>Fixed title</h2><div class="ff-claim">Fixed claim</div><div class="ff-body">
              <div class="columns"><div class="column"><h4>First heading</h4><p id="dense"></p></div>
              <div class="column"><h4>Second heading</h4><p id="peer">Short peer paragraph.</p></div></div>
              <div class="source">Fixed source</div></div></section></div></div>
              <script>let height=2000;const slide=document.querySelector('section');
              const Reveal={isReady:()=>true,getConfig:()=>({width:900,height}),
              getCurrentSlide:()=>slide,getSlides:()=>[slide],on:()=>{}};window.Reveal=Reveal;
              dense.textContent='A considered statement about the evidence and its implications. '.repeat(9);
              </script>''')
            page.add_script_tag(content=runtime.read_text())
            page.evaluate('matsugitFit.fitSlide(slide)')
            self.assertEqual(page.locator('#peer').get_attribute('style'), None)
            baseline = page.evaluate('''() => ({title:getComputedStyle(slide.querySelector('h2')).fontSize,
              claim:getComputedStyle(slide.querySelector('.ff-claim')).fontSize,
              heading:getComputedStyle(slide.querySelector('h4')).fontSize,
              source:getComputedStyle(slide.querySelector('.source')).fontSize})''')
            page.evaluate('height=slide.offsetHeight-65')
            report = page.evaluate('matsugitFit.fitSlide(slide)')
            self.assertFalse(report['overflow'], report)
            sizes = page.evaluate('[dense,peer].map(e=>parseFloat(getComputedStyle(e).fontSize))')
            self.assertEqual(sizes[0], sizes[1])
            self.assertGreaterEqual(sizes[0], 28 * .88 - .01)
            self.assertLess(sizes[0], 28)
            after = page.evaluate('''() => ({title:getComputedStyle(slide.querySelector('h2')).fontSize,
              claim:getComputedStyle(slide.querySelector('.ff-claim')).fontSize,
              heading:getComputedStyle(slide.querySelector('h4')).fontSize,
              source:getComputedStyle(slide.querySelector('.source')).fontSize})''')
            self.assertEqual(baseline, after)
            page.evaluate('matsugitFit.fitSlide(slide)')
            self.assertEqual(sizes, page.evaluate('[dense,peer].map(e=>parseFloat(getComputedStyle(e).fontSize))'))
            page.screenshot(path='/tmp/matsugit-auto-fit.png')
            page.evaluate('height=150')
            self.assertTrue(page.evaluate('matsugitFit.fitSlide(slide).unresolved'))
            self.assertGreaterEqual(page.evaluate('parseFloat(getComputedStyle(dense).fontSize)'), 28*.88-.01)
            page.evaluate('height=2000;matsugitFit.fitSlide(slide)')
            self.assertEqual(page.evaluate('getComputedStyle(dense).fontSize'), '28px')
            page.evaluate('height=150;slide.classList.add("no-fit");matsugitFit.fitSlide(slide)')
            self.assertEqual(page.evaluate('getComputedStyle(dense).fontSize'), '28px')
            page.evaluate('''slide.classList.remove('no-fit');
              slide.querySelector('.ff-body').innerHTML='<table style="font-size:21px"><tr><th>A</th><th>B</th></tr><tr><td>Many words here</td><td>A peer</td></tr></table><img style="height:28px;width:300px" alt="fixed connector">';
              height=80;matsugitFit.fitSlide(slide)''')
            table_sizes = page.evaluate('[...slide.querySelectorAll("th,td")].map(e=>parseFloat(getComputedStyle(e).fontSize))')
            self.assertTrue(all(size >= 20 for size in table_sizes), table_sizes)
            self.assertEqual(len(set(table_sizes)), 1)
            self.assertEqual(page.evaluate('getComputedStyle(slide.querySelector("img")).height'), '28px')
            browser.close()
