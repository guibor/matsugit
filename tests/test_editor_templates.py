import unittest

from folioforge.authoring import ELEMENTS, TEMPLATES, editor_templates
from folioforge.source import convert
from folioforge.converter import converter


class EditorTemplatesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = editor_templates()

    def test_shared_templates_and_element_catalogue(self):
        self.assertEqual(len(self.entries), len(TEMPLATES) + len(ELEMENTS))
        for name, md in TEMPLATES.items():
            entry = self.entries[{'section': 'section-deck', 'chart': 'chart-slide'}.get(name, name)]
            self.assertEqual(entry['markdown'], md)
            self.assertEqual(entry['kind'], 'Slide')
            self.assertIn('** ', entry['org'])

    def test_org_elements_preserve_semantics(self):
        for name in ['columns', 'columns-3', 'takeaway', 'notes', 'rows']:
            with self.subTest(name=name):
                org = self.entries[name]['org']
                self.assertIn('#+begin_', org)
                back = convert(org, 'org', 'markdown', converter())
                self.assertIn(name.replace('-3', ''), back)
        for fmt in ['markdown', 'org']:
            comment = self.entries['agent-comment'][fmt]
            self.assertIn('review-INSERT_ID', comment)
            self.assertIn('Pending.', comment)
            self.assertIn('Request:', comment)


if __name__ == '__main__':
    unittest.main()
