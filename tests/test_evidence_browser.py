"""Run against a rendered evidence-media.md fixture; no network access."""
import os
from pathlib import Path
import unittest

@unittest.skipUnless(os.environ.get('MATSUGIT_EVIDENCE_OUTPUT'),'Set MATSUGIT_EVIDENCE_OUTPUT')
class EvidenceBrowserTests(unittest.TestCase):
    def test_comparison_images_and_uncaptioned_portrait_fit(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            opts={'headless':True}
            if os.environ.get('MATSUGIT_CHROMIUM'):
                opts['executable_path']=os.environ['MATSUGIT_CHROMIUM']
            browser=p.chromium.launch(**opts)
            try:
                page=browser.new_page(viewport={'width':1440,'height':900})
                page.route('http://**',lambda r:r.abort())
                page.route('https://**',lambda r:r.abort())
                page.goto((Path(os.environ['MATSUGIT_EVIDENCE_OUTPUT'])/'slides.html').resolve().as_uri())
                page.wait_for_function('window.Reveal?.isReady()')
                for i in (1,2):
                    page.evaluate('i=>Reveal.slide(i)',i)
                    page.wait_for_timeout(600)
                    result=page.evaluate('''()=>{
                      const s=Reveal.getCurrentSlide(),b=s.getBoundingClientRect();
                      return {overflow:s.scrollHeight>s.clientHeight+2,
                        images:[...s.querySelectorAll('img')].map(e=>{const r=e.getBoundingClientRect();return e.naturalWidth>0&&r.height>100&&r.bottom<=b.bottom+2})};
                    }''')
                    self.assertFalse(result['overflow'],result)
                    self.assertTrue(result['images'] and all(result['images']),result)
            finally:browser.close()
