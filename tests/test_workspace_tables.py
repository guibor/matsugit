import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from matsugit.converter import converter
from matsugit.core import Error

spec = importlib.util.spec_from_file_location('workspace_actions', Path(__file__).resolve().parents[1] / 'codex-plugin/actions.py')
actions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actions)
try:
    COMMAND = converter()
except Error:
    COMMAND = None


@unittest.skipUnless(COMMAND, 'Requires span-aware Pandoc')
class WorkspaceTables(unittest.TestCase):
    source = '| Name | Value |\n| --- | --- |\n| **Alpha** | 12 |\n'

    def run_action(self, operation, **kwargs):
        with patch('matsugit.table_editor.converter', return_value=COMMAND):
            return actions.main(dict(action='table-'+operation, source=self.source, **kwargs))

    def test_open_check_and_serialize_do_not_require_a_file_or_theme(self):
        opened = self.run_action('open')
        self.assertIn('<table>', opened['html'])
        self.assertEqual(self.run_action('check', html=opened['html']), {'ok': True})
        self.assertEqual(self.run_action('serialize', html=opened['html'])['format'], 'pipe')

    def test_restore_and_merged_cells_preserve_content_without_html_source(self):
        html = '<table><tr><th colspan="2">Group</th></tr><tr><td>Alpha</td><td>12</td></tr></table>'
        result = self.run_action('open', html=html)
        self.assertIn('colspan="2"', result['html'])
        self.assertNotIn('<table', result['source'])
        self.assertIn('Alpha', result['source'])

    def test_unsafe_or_unsupported_restored_html_is_refused(self):
        for html in ('<script>alert(1)</script>', '<table><tr><td><img src="https://example.invalid"></td></tr></table>'):
            with self.assertRaises(Error):
                self.run_action('open', html=html)
