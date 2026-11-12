from pathlib import Path
import tempfile
import unittest

from matsugit.authoring import template


class TourTemplateTests(unittest.TestCase):
    def test_cli_template_uses_the_shared_deck_and_never_replaces_edits(self):
        source = Path(__file__).resolve().parents[1] / 'matsugit/templates/tour.md'
        self.assertEqual(template('tour'), source.read_text())
        self.assertEqual(template('tour', fragment=True), source.read_text())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'matsugit-tour.md'
            template('tour', output=target)
            self.assertEqual(target.read_text(), source.read_text())
            target.write_text('My edited tour')
            with self.assertRaises(FileExistsError):
                template('tour', output=target)
            self.assertEqual(target.read_text(), 'My edited tour')
