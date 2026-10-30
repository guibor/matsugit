"""Opt-in geometry checks for generic stacked sections, with synthetic content."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('FOLIOFORGE_ROWS_OUTPUT'), 'Set rendered rows fixture')
class RowsBrowserTests(unittest.TestCase):
    def test_sections_gaps_media_and_reading_flow(self):
        from playwright.sync_api import sync_playwright
        root=Path(os.environ['FOLIOFORGE_ROWS_OUTPUT'])
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ['CHROME'],
                                      args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                for width,height in ((1440,900),(390,844)):
                    page=browser.new_page(viewport={'width':width,'height':height})
                    page.route('https://**',lambda r:r.abort())
                    errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto((root/'index.html').as_uri())
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                    self.assertEqual(page.locator('.rows > .row').count(),2)
                    page.goto((root/'slides.html').as_uri())
                    page.wait_for_function('window.Reveal?.isReady() && document.querySelector("svg.mermaid-js")')
                    ids=page.evaluate('Reveal.getSlides().filter(s=>s.id&&!s.classList.contains("stack")).map(s=>s.id)')
                    self.assertEqual(len(ids),4)
                    for id in ids:
                        page.evaluate('''id=>{const s=document.getElementById(id);
                          if(Reveal.isScrollView?.())s.scrollIntoView({behavior:'instant',block:'center'});
                          else{const i=Reveal.getIndices(s);Reveal.slide(i.h,i.v)}}''',id)
                        page.wait_for_function('id=>Reveal.getCurrentSlide().id===id',arg=id)
                        page.wait_for_timeout(250)
                        result=page.evaluate('''()=>{
                          const s=Reveal.getCurrentSlide(),r=s.getBoundingClientRect();
                          const rect=e=>e.getBoundingClientRect(), rows=[...s.querySelectorAll('.ff-row')];
                          const content=[...s.querySelectorAll(':scope>h2,:scope>.ff-claim,:scope>.ff-body,:scope>.ff-takeaway')];
                          return {fits:s.scrollHeight<=s.clientHeight+2,
                            separate:content.every((e,i)=>!i||rect(e).top>=rect(content[i-1]).bottom-1),
                            rows:rows.map((e,i)=>({border:getComputedStyle(e).borderTopWidth,
                              gap:i?(rect(e).top-rect(rows[i-1]).bottom)/Reveal.getScale():null})),
                            media:[...s.querySelectorAll('svg.mermaid-js')].map(e=>({w:rect(e).width,h:rect(e).height,
                              inside:rect(e).bottom<=rect(e.closest('.ff-row')).bottom+1})),
                            fallback:[...s.querySelectorAll('table + .ff-division-heading')].map(e=>({
                              border:getComputedStyle(e).borderTopWidth,padding:parseFloat(getComputedStyle(e).paddingTop)}))};
                        }''')
                        self.assertTrue(result['fits'],(width,id,result))
                        self.assertTrue(result['separate'],(width,id,result))
                        for row in result['rows'][1:]:
                            self.assertEqual(row['border'],'1px')
                            self.assertGreaterEqual(row['gap'],23)
                        for media in result['media']:
                            self.assertTrue(media['inside'],(width,id,media))
                            self.assertGreater(media['w'],20)
                            self.assertGreater(media['h'],20)
                        for fallback in result['fallback']:
                            self.assertEqual(fallback['border'],'1px')
                            self.assertGreaterEqual(fallback['padding'],20)
                    self.assertFalse(errors,errors)
                    page.close()
            finally:
                browser.close()
