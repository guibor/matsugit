"""The plain-language check from the command line agrees with the workspace's."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from matsugit.check import check, report
from matsugit.cli import main
from matsugit.core import Error

ROOT = Path(__file__).resolve().parents[1]
HEAD = '---\ntitle: T\nslide-layout: structured\n---\n\n'


@unittest.skipUnless(shutil.which('node') and (ROOT / 'codex-plugin/bundle/story-cli.mjs').is_file(), 'Node and the bundled workspace are required')
class CheckCommandTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.deck = Path(temp.name) / 'deck.md'

    def test_problems_are_located_and_reported_in_plain_words(self):
        self.deck.write_text(HEAD + '## One\n\nFine.\n\n## Two\n\n:::: columns\n#### A\nx\n::::\n\n::: takaway\nDone.\n:::\n')
        before = self.deck.read_bytes()
        data = check(self.deck)
        self.assertEqual((data['problems'], data['tips']), (1, 1))
        self.assertEqual([(item['code'], item['slide'], item['line']) for item in data['findings']],
                         [('parts-count', 2, 12), ('block-name', 2, 17)])
        text = report(data)
        self.assertIn('To fix: Slide 2 (Two), line 12', text)
        self.assertIn('Tip: Slide 2 (Two), line 17', text)
        self.assertNotIn('`', text)
        self.assertEqual(self.deck.read_bytes(), before)
        self.assertEqual(main(['check', str(self.deck)]), 0)
        self.assertEqual(main(['check', str(self.deck), '--strict']), 2)

    def test_a_clean_deck_and_the_bundled_examples_pass(self):
        self.deck.write_text(HEAD + '## One\n\nFine.\n')
        self.assertIn('No problems found', report(check(self.deck)))
        for example in sorted((ROOT / 'examples').glob('*.md')):
            self.assertEqual(check(example)['problems'], 0, example.name)

    def test_other_files_are_refused(self):
        other = self.deck.with_suffix('.txt'); other.write_text('x')
        with self.assertRaises(Error):
            check(other)

    def test_installed_cli_can_select_a_checkout(self):
        self.deck.write_text(HEAD + '## One\n\nFine.\n')
        with patch('matsugit.check.__file__', str(self.deck.parent / 'installed/matsugit/check.py')):
            with self.assertRaisesRegex(Error, '--checkout'):
                check(self.deck)
            self.assertEqual(check(self.deck, ROOT)['problems'], 0)
            self.assertEqual(main(['check', str(self.deck), '--checkout', str(ROOT)]), 0)

    def test_oversized_input_is_rejected_before_starting_a_helper(self):
        self.deck.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with patch('matsugit.check.subprocess.run') as run:
            with self.assertRaisesRegex(Error, '2 MiB'):
                check(self.deck)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
