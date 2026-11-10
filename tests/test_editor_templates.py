import unittest

from matsugit.authoring import CATALOG, ELEMENTS, HIDDEN, TEMPLATES, editor_templates
from matsugit.source import convert
from matsugit.converter import converter


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

    def test_every_recipe_has_a_plain_name_or_is_deliberately_hidden(self):
        self.assertEqual(set(self.entries), set(CATALOG) | HIDDEN)
        self.assertFalse(set(CATALOG) & HIDDEN)
        titles = [entry['title'] for entry in self.entries.values() if 'title' in entry]
        self.assertEqual(len(titles), len(set(titles)))
        for key, entry in self.entries.items():
            if key in HIDDEN:
                self.assertNotIn('title', entry)
                continue
            self.assertIn(entry['group'], ('slide', 'part'))
            self.assertTrue(entry['title'] and entry['when'].endswith('.') and entry['sketch'])
            # Names are for people who do not read Markdown.
            self.assertNotRegex(entry['title'] + entry['when'], r'[#{}`]|::|H[1-6]\b')
        # Every recipe that starts with a slide heading is offered as a new slide.
        for key, entry in self.entries.items():
            if key not in HIDDEN:
                starts_slide = entry['markdown'].lstrip().startswith(('## ', '# '))
                self.assertEqual(entry['group'] == 'slide', starts_slide, key)

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
