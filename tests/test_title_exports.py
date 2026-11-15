"""Real output checks for a single authored cover, without changing its source."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from matsugit.core import config, render
from matsugit.exports import export_file, browser_artifacts


QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))
FIXTURE = '''---
title: A single opening
slide-layout: structured
---

## A single opening {#opening .cover}

### The authored claim stays

The cover body stays.

## Evidence

Second slide content.
'''


@unittest.skipUnless(QUARTO, 'Real export requires Quarto')
class TitleExports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='matsugit-title-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'deck.md'
        self.source.write_text(FIXTURE)
        self.settings = config(self.source, {'theme':'default', 'quarto':QUARTO})

    def test_powerpoint_has_one_authored_cover(self):
        result = self.root / 'deck.pptx'
        export_file(self.settings, 'pptx', result)
        with zipfile.ZipFile(result) as archive:
            pages = [name for name in archive.namelist()
                     if name.startswith('ppt/slides/slide') and name.endswith('.xml')]
            self.assertEqual(len(pages), 2)
            text = '\n'.join(' '.join(ET.fromstring(archive.read(name)).itertext()) for name in pages)
            self.assertEqual(text.count('A single opening'), 1)
            self.assertIn('The cover body stays.', text)
        self.assertEqual(self.source.read_text(), FIXTURE)

    @unittest.skipUnless(os.environ.get('MATSUGIT_TITLE_PDF') and shutil.which('pdftotext'),
                         'Opt-in browser PDF check')
    def test_pdf_has_one_authored_cover(self):
        output = self.root / 'html'
        render(self.settings, output)
        pdf = self.root / 'deck.pdf'
        browser_artifacts(output, pdf)
        text = subprocess.check_output(['pdftotext', str(pdf), '-'], text=True)
        self.assertEqual(text.count('A single opening'), 1)
        self.assertIn('The cover body stays.', text)
        self.assertIn('Second slide content.', text)
        self.assertEqual(self.source.read_text(), FIXTURE)
