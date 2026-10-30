"""Opt-in browser checks for structured slides; synthetic source only."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('FOLIOFORGE_LAYOUT_OUTPUT'), 'Set a rendered synthetic layout fixture')
class LayoutBrowserTests(unittest.TestCase):
    def test_hierarchy_columns_media_and_reading_structure(self):
        from playwright.sync_api import sync_playwright
        root=Path(os.environ['FOLIOFORGE_LAYOUT_OUTPUT'])
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ['CHROME'],
                args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                for width,height in ((1440,900),(390,844)):
                    page=browser.new_page(viewport={'width':width,'height':height})
                    page.route('https://cdn.jsdelivr.net/npm/mathjax@**',lambda r:r.abort())
                    errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto((root/'index.html').as_uri())
                    self.assertIn('An unfinished outline heading',page.locator('body').inner_text())
                    self.assertNotIn('slide-layout:',page.locator('body').inner_text())
                    page.goto((root/'slides.html').as_uri())
                    page.wait_for_function('window.Reveal && Reveal.isReady() && document.querySelector("svg.mermaid-js")')
                    ids=page.evaluate('Reveal.getSlides().filter(s=>s.id && !s.classList.contains("stack")).map(s=>s.id)')
                    self.assertEqual(len(ids),4,ids)
                    for id in ids:
                        page.evaluate('''id=>{const s=document.getElementById(id);
                          if(Reveal.isScrollView?.()) s.scrollIntoView({behavior:'instant',block:'center'});
                          else {const i=Reveal.getIndices(s);Reveal.slide(i.h,i.v)}}''',id)
                        page.wait_for_function('id=>Reveal.getCurrentSlide().id===id',arg=id)
                        page.wait_for_timeout(250)
                        result=page.evaluate('''()=>{
                          const s=Reveal.getCurrentSlide(), title=s.querySelector('h2'), claim=s.querySelector('.ff-claim');
                          const r=s.getBoundingClientRect(), rect=e=>e.getBoundingClientRect();
                          const children=[...s.querySelectorAll('.ff-claim,.ff-body,.ff-takeaway')];
                          return {hasTitle:!!title,claimSmaller:!claim||parseFloat(getComputedStyle(claim).fontSize)<parseFloat(getComputedStyle(title).fontSize),
                            claimLight:!claim||Number(getComputedStyle(claim).fontWeight)<=400,
                            noOverlap:children.every((e,i)=>!i||rect(e).top>=rect(children[i-1]).bottom-1),
                            noOverflow:children.every(e=>rect(e).bottom<=r.bottom+2&&rect(e).right<=r.right+2),
                            headings:s.querySelectorAll('[role="heading"][aria-level="4"]').length,
                            columns:[...s.querySelectorAll('.column')].map(e=>rect(e).width/r.width),
                            labelsFit:[...s.querySelectorAll('svg.mermaid-js .node')].every(n=>{
                              const box=n.querySelector('rect.label-container'),label=n.querySelector('.nodeLabel');
                              if(!box||!label)return true;
                              const b=rect(box),l=rect(label);
                              return l.left>=b.left-1&&l.right<=b.right+1&&l.top>=b.top-1&&l.bottom<=b.bottom+1;
                            }),
                            diagram:[...s.querySelectorAll('svg.mermaid-js')].map(e=>({w:rect(e).width,h:rect(e).height}))};
                        }''')
                        if result['hasTitle']:
                            for key in ('claimSmaller','claimLight','noOverlap','noOverflow','labelsFit'):
                                self.assertTrue(result[key],(width,id,key,result))
                            for ratio in result['columns']:
                                self.assertGreater(ratio,.3)
                                self.assertLess(ratio,.6)
                            for rect in result['diagram']:
                                self.assertGreater(rect['w'],20)
                                self.assertGreater(rect['h'],20)
                        if 'headline' in id:
                            page.screenshot(path=f'/tmp/folioforge-structured-{width}.png')
                    self.assertFalse(errors,errors)
                    page.close()
            finally:
                browser.close()
