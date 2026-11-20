import json
import shutil
import subprocess
import unittest

from matsugit.reading_tables import auto_tables


@unittest.skipUnless(shutil.which('pandoc'), 'requires Pandoc')
class ReadingTables(unittest.TestCase):
    def test_only_default_pipe_widths_are_marked(self):
        for separator, expected in [('|---|---|', True), ('|:---|---:|', True),
                                    ('|-----|----------|', False), ('|------|------|', False)]:
            with self.subTest(separator=separator):
                text = '| Status | Action |\n' + separator + '\n| Ready | ' + ('check ' * 30) + '|\n'
                ast = json.loads(subprocess.check_output(['pandoc', '-f', 'markdown', '-t', 'json'],
                                                         input=text, text=True))
                auto_tables(ast, text)
                self.assertEqual(ast['blocks'][0]['t'] == 'Div', expected)
