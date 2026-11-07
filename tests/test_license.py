"""First-party attribution is packaged without replacing dependency notices."""
import json
from pathlib import Path
import unittest
import tempfile

from matsugit.publish import setup_ci

ROOT = Path(__file__).resolve().parents[1]


class LicenseTests(unittest.TestCase):
    def test_license_and_author_credit(self):
        license_text = (ROOT / 'LICENSE').read_text()
        self.assertTrue(license_text.startswith('MIT License\n'))
        self.assertIn('Copyright (c) 2026 MDF (guibor)', license_text)
        self.assertEqual((ROOT / 'matsugit/runtime/MATSUGIT-LICENSE').read_text(), license_text)
        self.assertIn('The above copyright notice and this permission notice', license_text)
        self.assertIn('license = {file = "LICENSE"}', (ROOT / 'pyproject.toml').read_text())
        self.assertIn('https://github.com/guibor][MDF (guibor)', (ROOT / 'README.org').read_text())

    def test_node_metadata_and_third_party_notices(self):
        for name in ('codex-plugin', 'editor'):
            package = json.loads((ROOT / name / 'package.json').read_text())
            lock = json.loads((ROOT / name / 'package-lock.json').read_text())
            self.assertEqual(package['license'], 'MIT')
            self.assertEqual(lock['packages']['']['license'], 'MIT')
        for name in ('codex-plugin/bundle/THIRD-PARTY-NOTICES.txt',
                     'matsugit/editor_assets/THIRD-PARTY-LICENSES.txt',
                     'matsugit/runtime/MATHJAX-LICENSE'):
            self.assertGreater((ROOT / name).stat().st_size, 100)

    def test_ci_retains_first_party_license(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup_ci({'repo': root, 'site_dir': 'site'}, 'gitlab')
            self.assertEqual((root / '.matsugit-ci/runtime/MATSUGIT-LICENSE').read_bytes(),
                             (ROOT / 'LICENSE').read_bytes())


if __name__ == '__main__': unittest.main()
