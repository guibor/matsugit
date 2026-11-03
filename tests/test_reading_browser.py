"""Check the structured fixture as a reading document, not a slide handout."""
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('MATSUGIT_READING_OUTPUT'), 'Set rendered structured.md output')
class ReadingBrowserTests(unittest.TestCase):
    def test_continuous_reading_and_semantic_content(self):
        from playwright.sync_api import sync_playwright
        root = Path(os.environ['MATSUGIT_READING_OUTPUT'])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ['CHROME'])
            try:
                for width, height in ((1440, 900), (390, 844)):
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    page.route('http*://**', lambda route: route.abort())
                    page.goto((root / 'index.html').as_uri())
                    page.wait_for_function('document.querySelector("svg.mermaid-js")')
                    main = page.locator('main')
                    self.assertEqual(main.locator('table').count(), 2)
                    self.assertEqual(main.locator('.takeaway').count(), 2)
                    self.assertEqual(main.locator('.reveal, .ff-handout-slide, .ff-content').count(), 0)
                    self.assertNotIn('slide-layout:', main.inner_text())
                    self.assertEqual(main.inner_text().count('A smaller, lighter claim'), 1)
                    self.assertIn('An unfinished outline heading', main.inner_text())
                    result = page.evaluate('''() => {
                      const main = document.querySelector('main');
                      const takeaways = [...main.querySelectorAll('.takeaway')];
                      return {
                        overflow: document.documentElement.scrollWidth > innerWidth + 2,
                        continuous: main.scrollHeight > innerHeight,
                        noClipping: [...main.querySelectorAll('.takeaway, .columns, .rows')].every(el =>
                          !['hidden','clip'].includes(getComputedStyle(el).overflowY)),
                        inFlow: takeaways.every(el => ['static','relative'].includes(getComputedStyle(el).position)),
                        afterEvidence: takeaways.every(el => !el.previousElementSibling ||
                          el.getBoundingClientRect().top >= el.previousElementSibling.getBoundingClientRect().bottom - 2)
                      };
                    }''')
                    self.assertFalse(result['overflow'], (width, result))
                    for key in ('continuous', 'noClipping', 'inFlow', 'afterEvidence'):
                        self.assertTrue(result[key], (width, key, result))
                    page.screenshot(path=str(root / f'reading-{width}.png'), full_page=True)
                    page.close()
            finally:
                browser.close()
