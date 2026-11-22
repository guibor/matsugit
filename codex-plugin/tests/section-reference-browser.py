"""Verify the same numbered Markdown link by clicking both actual exports."""
from pathlib import Path
import subprocess
import tempfile
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / 'example.md'
    source.write_text('---\ntitle: Reference test\nslide-layout: structured\n---\n\n'
                      '## Decision\n\nRead the method [\\[1\\]](#detail-method).\n\n'
                      '## Method {#detail-method .collapsible}\n\nEvidence in full.\n')
    out = Path(tmp) / 'out'
    subprocess.run([str(root / 'bin/matsugit'), 'render', str(source), '--output', str(out)], check=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto((out / 'index.html').as_uri())
        page.get_by_role('link', name='[1]', exact=True).click()
        assert page.locator('#detail-method').is_visible()
        assert page.get_by_text('Evidence in full.', exact=True).is_visible()
        page.goto((out / 'slides.html').as_uri())
        page.wait_for_function('window.Reveal?.isReady()')
        page.evaluate("Reveal.slide(Reveal.getIndices([...document.querySelectorAll('section')].find(s=>s.querySelector('a[href*=detail-method]'))).h)")
        page.get_by_role('link', name='[1]', exact=True).click()
        page.wait_for_function("Reveal.getCurrentSlide()?.id === 'detail-method'")
        print('PASS: numbered reference opened reading section and navigated to detail slide.')
