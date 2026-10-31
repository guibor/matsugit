"""Inspect the synthetic relationships.md render, offline, in any selected theme."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('FOLIOFORGE_RELATIONSHIPS_OUTPUT'), 'Set FOLIOFORGE_RELATIONSHIPS_OUTPUT')
class RelationshipBrowserTests(unittest.TestCase):
    def test_slides_reading_resize_targets_and_no_fit_loop(self):
        from playwright.sync_api import sync_playwright
        root = Path(os.environ['FOLIOFORGE_RELATIONSHIPS_OUTPUT']).resolve()
        with sync_playwright() as p:
            options = {'headless': True, 'args': ['--no-sandbox', '--disable-dev-shm-usage']}
            if os.environ.get('FOLIOFORGE_CHROMIUM'):
                options['executable_path'] = os.environ['FOLIOFORGE_CHROMIUM']
            browser = p.chromium.launch(**options)
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('http://**', lambda r: r.abort())
                page.route('https://**', lambda r: r.abort())
                for width, height in ((1440,900),(1024,768),(390,844)):
                    page.set_viewport_size({'width':width, 'height':height})
                    page.goto((root/'slides.html').as_uri())
                    page.wait_for_function('window.Reveal?.isReady()')
                    count = page.evaluate('Reveal.getSlides().length')
                    self.assertEqual(count,4)
                    for index in range(count):
                        if page.evaluate('Reveal.isScrollView()'):
                            if index:
                                page.keyboard.press('ArrowRight')
                        else:
                            page.evaluate('i=>{const n=Reveal.getIndices(Reveal.getSlides()[i]);Reveal.slide(n.h,n.v)}',index)
                        page.wait_for_timeout(600)
                        page.wait_for_function('i=>Reveal.getCurrentSlide()===Reveal.getSlides()[i]',arg=index)
                        result = page.evaluate('''()=>{
                          const s=Reveal.getCurrentSlide();
                          const parts=[...s.querySelectorAll(':scope>h2,:scope>.ff-claim,:scope>.ff-body,:scope>.ff-takeaway')].filter(e=>e.getBoundingClientRect().height);
                          return {overflow:s.scrollHeight>s.clientHeight+2||s.scrollWidth>s.clientWidth+2,
                            overlap:parts.some((e,i)=>i&&e.getBoundingClientRect().top<parts[i-1].getBoundingClientRect().bottom-1),
                            images:[...s.querySelectorAll('img')].every(e=>e.naturalWidth>0&&e.getBoundingClientRect().height>60),
                            notes:[...s.querySelectorAll('.ff-callout')].every(e=>e.scrollWidth<=e.clientWidth+2),
                            badges:[...s.querySelectorAll('.ff-callout-number')].every(e=>getComputedStyle(e).backgroundColor!=='rgba(0, 0, 0, 0)'),
                            pointers:[...s.querySelectorAll('.ff-annotated')].map(g=>({
                              notes:g.querySelectorAll('.ff-callout').length,
                              lines:g.querySelectorAll('.ff-annotation-lines>path').length,
                              valid:[...g.querySelectorAll('.ff-annotation-lines path')].every(p=>!/(NaN|Infinity)/.test(p.getAttribute('d')))
                            }))};
                        }''')
                        self.assertFalse(result['overflow'],(width,index,result))
                        self.assertFalse(result['overlap'],(width,index,result))
                        self.assertTrue(result['images'] and result['notes'] and result['badges'],(width,index,result))
                        if index == 0:
                            self.assertTrue(page.locator('.present .ff-implication').evaluate('''g=>{
                              const hs=[...g.querySelectorAll(':scope>.ff-premise>.ff-division-heading,:scope>.ff-consequence>.ff-division-heading')];
                              const a=getComputedStyle(g.querySelector(':scope>.ff-relation'),'::before');
                              const ratio=parseFloat(a.height)/parseFloat(a.width);
                              return Math.abs(hs[0].getBoundingClientRect().top-hs[1].getBoundingClientRect().top)<1
                                && hs.every(h=>getComputedStyle(h).borderBottomWidth==='0px')
                                && Math.abs(ratio-2)<.05 && parseFloat(a.height)<=2.31*parseFloat(getComputedStyle(g).fontSize);
                            }'''),'Implication must use the same unruled headings and bounded triangle as paired actions')
                        if index == 1:
                            self.assertTrue(page.locator('.present .ff-mapping').evaluate('''g=>{
                              const head=g.querySelector('.ff-mapping-head'),rows=[...g.querySelectorAll('.ff-mapping-row')];
                              return getComputedStyle(head).borderBottomWidth==='0px'
                                && rows.slice(1).every(r=>getComputedStyle(r).borderTopStyle==='dashed')
                                && getComputedStyle(g.querySelector('.ff-relation-label')).width==='1px';
                            }'''),'Mapping must use the reference row composition, not table chrome')
                            if width == 1440:
                                for count in (1, 2, 4, 6):
                                    self.assertTrue(page.locator('.present .ff-mapping').evaluate('''(g,count)=>{
                                      const backup=g.cloneNode(true), row=g.querySelector('.ff-mapping-row').cloneNode(true);
                                      g.querySelectorAll('.ff-mapping-row').forEach(r=>r.remove());
                                      for(let i=0;i<count;i++)g.append(row.cloneNode(true));
                                      g.dataset.rows=String(count);
                                      const slide=g.closest('section'), ok=slide.scrollHeight<=slide.clientHeight+2
                                        && [...g.querySelectorAll('.ff-mapping-cell')].every(e=>e.scrollWidth<=e.clientWidth+2);
                                      g.replaceWith(backup);return ok;
                                    }''',count),f'{count} ordinary mapping rows must fit without shrinking text')
                        for pointer in result['pointers']:
                            self.assertEqual(pointer['notes'],pointer['lines'],(width,index,pointer))
                            self.assertTrue(pointer['valid'])
                        if index == 2 and width == 1440:
                            page.locator('.present .ff-callout-number').first.click()
                            self.assertEqual(page.evaluate('document.activeElement.id'),'pilot-cycle')
                            self.assertEqual(page.evaluate('Reveal.getIndices().h'),2)
                        folder = os.environ.get('FOLIOFORGE_RELATIONSHIPS_SCREENSHOTS')
                        if folder:
                            Path(folder).mkdir(parents=True,exist_ok=True)
                            page.screenshot(path=str(Path(folder)/f'slide-{index+1}-{width}.png'))
                    page.evaluate('''()=>{window.ffRedraws=0;new MutationObserver(rs=>{
                      for(const r of rs) for(const n of r.addedNodes) if(n.nodeType===1&&n.matches('.ff-annotation-lines'))window.ffRedraws++;
                    }).observe(document.querySelector('.reveal'),{childList:true,subtree:true})}''')
                    page.wait_for_timeout(800)
                    self.assertLess(page.evaluate('window.ffRedraws'),4,'Annotation/media fitting must settle')
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':900})
                    page.goto((root/'index.html').as_uri())
                    page.wait_for_timeout(400)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))
                    self.assertEqual(page.locator('.ff-mapping-row').count(),3)
                    for link in page.locator('.ff-callout-number').all():
                        target=link.get_attribute('href')[1:]
                        self.assertEqual(page.locator('[id]').evaluate_all('(els,id)=>els.filter(e=>e.id===id).length',target),1)
                    if width==390:
                        self.assertTrue(page.locator('.ff-annotated').evaluate_all('''groups=>groups.every(g=>{
                          const a=g.querySelector('.ff-evidence').getBoundingClientRect(),b=g.querySelector('.ff-callouts').getBoundingClientRect();
                          return b.top>=a.bottom;
                        })'''))
                self.assertEqual(errors,[])
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
