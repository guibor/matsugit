"""Real exported HTML: opt-in folding, inheritance and printable content."""
import os
from pathlib import Path
import subprocess
import tempfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BODY = '''## Parent {#parent%s}

Parent evidence.

#### Child {#child}

Child evidence.

## Sibling {#sibling}

Sibling evidence.

%s
'''
BLOCK = '''::: {.collapsible title="Supporting detail"}

Block evidence.

:::
'''

with tempfile.TemporaryDirectory(prefix='matsugit-fold-export-') as tmp:
    root = Path(tmp)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE'))
        page = browser.new_page(viewport={'width': 1100, 'height': 850})
        for mode, marker, block, yaml in (
            ('default', '', '', ''),
            ('selected', ' .collapsible', BLOCK, ''),
            ('all', '', '', 'document-collapsible: true\n'),
        ):
            source = root / (mode + '.md')
            text = '---\ntitle: Folding example\n' + yaml + '---\n\n' + BODY % (marker, block)
            source.write_text(text)
            output = root / mode
            subprocess.run(['python3', str(ROOT/'bin/matsugit'), 'render', str(source),
                            '--theme', 'default', '--output', str(output), '--only', 'document'],
                           cwd=ROOT, check=True, capture_output=True, timeout=120)
            page.goto((output/'index.html').as_uri())
            page.wait_for_load_state('load')
            assert source.read_text() == text
            if mode == 'default':
                assert page.locator('.ff-fold-toggle').count() == 0
                assert page.get_by_text('Child evidence.', exact=True).is_visible()
                continue
            assert page.locator('.ff-fold-toggle').count() == 3
            assert page.locator('#parent > h2 button').get_attribute('aria-expanded') == 'false'
            assert page.get_by_text('Child evidence.', exact=True).is_hidden()
            page.locator('#parent > h2 button').click()
            assert page.get_by_text('Parent evidence.', exact=True).is_visible()
            assert page.get_by_text('Child evidence.', exact=True).is_hidden()
            page.locator('#child > h4 button').click()
            assert page.get_by_text('Child evidence.', exact=True).is_visible()
            if mode == 'selected':
                assert page.locator('#sibling > h2 button').count() == 0
                assert page.get_by_text('Sibling evidence.', exact=True).is_visible()
                assert page.get_by_text('Block evidence.', exact=True).is_hidden()
                page.get_by_role('button', name='Section: Supporting detail').click()
                assert page.get_by_text('Block evidence.', exact=True).is_visible()
            else:
                assert page.get_by_text('Sibling evidence.', exact=True).is_hidden()
            page.reload()
            assert page.get_by_text('Parent evidence.', exact=True).is_hidden()
            page.emulate_media(media='print')
            for evidence in ('Parent evidence.', 'Child evidence.', 'Sibling evidence.'):
                assert page.get_by_text(evidence, exact=True).is_visible()
            if block:
                assert page.get_by_text('Block evidence.', exact=True).is_visible()
            page.emulate_media(media='screen')
            shots = Path(os.environ.get('MATSUGIT_SCREENSHOTS', '/tmp/matsugit-fold-export-shots'))
            shots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shots / (mode + '.png')))
        browser.close()
print('PASS: actual exported HTML, default off, selected and global folding, inherited children, fresh-load defaults, print and source preservation')
