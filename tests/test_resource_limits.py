import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit import core


class ResourceLimitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'deck.md'
        self.source.write_text('synthetic source')
        self.output = self.root / 'output'
        self.output.mkdir()
        self.settings = dict(source=self.source, source_root=self.root, quarto='quarto')

    def ast(self, *assets):
        return {'meta': {}, 'blocks': [
            {'t': 'Para', 'c': [{'t': 'Image', 'c': [['', [], []], [], [name, '']]}]}
            for name in assets]}

    def prepare(self, *assets):
        with patch('matsugit.source.read', return_value=self.ast(*assets)):
            return core.normalize(self.settings, self.output, editable_source=False)

    def test_source_file_and_utf8_draft_rejected_before_parsing(self):
        with patch.dict(os.environ, MATSUGIT_MAX_SOURCE_BYTES='4'), \
             patch('matsugit.source.read') as parse:
            with self.assertRaisesRegex(core.Error, 'source limit'):
                core.normalize(self.settings, self.output)
            with self.assertRaisesRegex(core.Error, 'source limit'):
                core.normalize(self.settings, self.output, source_text='\u00e9' * 3)
            parse.assert_not_called()
            self.assertEqual(core.bounded_source(self.source, 'four'), 'four')

    def test_growing_source_is_bounded_after_stat(self):
        self.source.write_bytes(b'ab')
        with self.source.open('rb') as original:
            stream = io.BytesIO(b'abcdef')
            stream.fileno = original.fileno
            with patch.dict(os.environ, MATSUGIT_MAX_SOURCE_BYTES='4'), \
                 patch.object(Path, 'open', return_value=stream):
                with self.assertRaisesRegex(core.Error, 'source limit'):
                    core.bounded_source(self.source)

    def test_individual_attachment_limit_and_no_whole_file_read(self):
        (self.root / 'one.png').write_bytes(b'12345')
        with patch.dict(os.environ, MATSUGIT_MAX_ASSET_BYTES='4'), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded read')):
            with self.assertRaisesRegex(core.Error, 'budget'):
                self.prepare('one.png')
        self.assertEqual(list(self.output.rglob('*')), [])

    def test_total_budget_and_repeated_references(self):
        (self.root / 'one.png').write_bytes(b'1234')
        (self.root / 'two.png').write_bytes(b'5678')
        with patch.dict(os.environ, MATSUGIT_MAX_ASSET_BYTES='4', MATSUGIT_MAX_TOTAL_ASSET_BYTES='7'):
            with self.assertRaisesRegex(core.Error, 'budget'):
                self.prepare('one.png', 'one.png', 'two.png')
        self.assertEqual(len(list((self.output / 'assets').iterdir())), 1)
        with patch.dict(os.environ, MATSUGIT_MAX_TOTAL_ASSET_BYTES='4'):
            self.prepare('one.png', 'one.png')
        self.assertEqual(len(list((self.output / 'assets').iterdir())), 1)

    def test_growing_attachment_leaves_no_partial_copy(self):
        asset = self.root / 'one.png'
        asset.write_bytes(b'12')
        with asset.open('rb') as original:
            stream = io.BytesIO(b'12345')
            stream.fileno = original.fileno
            with patch.object(Path, 'open', return_value=stream):
                with self.assertRaisesRegex(core.Error, 'grew'):
                    core.copy_asset(asset, self.output, 4)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_invalid_limits_cannot_silently_disable_bounds(self):
        for value in ('0', '-1', 'unlimited', '1.5'):
            with self.subTest(value=value), patch.dict(os.environ, MATSUGIT_MAX_SOURCE_BYTES=value):
                with self.assertRaisesRegex(core.Error, 'positive byte limit'):
                    core.bounded_source(self.source)
