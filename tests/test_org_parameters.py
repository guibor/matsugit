import json
import shutil
import unittest
from matsugit.converter import converter
from matsugit.source import read, org_block_parameters
from matsugit.layout import plain


class OrgParametersTests(unittest.TestCase):
    def test_quoted_parameters_and_literals_survive_old_and_new_pandoc(self):
        source = '''#+begin_src text
#+begin_region :title "Literal"
#+end_region
#+end_src

#+attr_html: :id original
#+begin_div :ratio "2:1"
#+begin_region :title "A longer \\"quoted\\" heading"
Evidence.
#+end_region
#+end_div
'''
        commands = [converter()]
        if shutil.which('quarto'): commands.append(['quarto','pandoc'])
        for command in commands:
            with self.subTest(command=command):
                ast = read(source,'org',command)
                self.assertIn('#+begin_region :title "Literal"',ast['blocks'][0]['c'][1])
                column = ast['blocks'][1]
                self.assertEqual(column['c'][0][0],'original')
                self.assertIn(['ratio','2:1'],column['c'][0][2])
                self.assertEqual(plain(column['c'][1][0]['c'][2]),'A longer "quoted" heading')
                self.assertNotIn('data-matsugit-',json.dumps(ast))

    def test_malformed_attributes_fail_without_executing_anything(self):
        for value in (':title "unterminated', ':title', 'not-an-attribute value'):
            with self.assertRaises(ValueError): org_block_parameters('#+begin_region '+value+'\n#+end_region\n')


if __name__ == '__main__': unittest.main()
