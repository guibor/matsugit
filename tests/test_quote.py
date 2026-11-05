import copy
import unittest
from matsugit import authoring, layout
from matsugit.converter import converter
from matsugit.source import convert, read


class QuoteTests(unittest.TestCase):
    def test_quote_template_is_explicit_and_attribution_is_not_a_hidden_source(self):
        source = authoring.TEMPLATES['quote']
        self.assertEqual(source, authoring.TEMPLATES['quotation'])
        self.assertIn('{.quote .hide-title .hide-claim}', source)
        self.assertIn('::: attribution\n-- Author', source)
        self.assertNotIn('::: source', source)

    def test_plain_slide_semantics_preserve_quote_role_and_outline_headings(self):
        header = {'t': 'Header', 'c': [2, ['perspective', ['quote', 'hide-title', 'hide-claim'], []], [{'t':'Str','c':'Perspective'}]]}
        quote = {'t':'BlockQuote','c':[{'t':'Para','c':[{'t':'Str','c':'Quotation'}]}]}
        ast = {'meta':{'slide-layout':{'t':'MetaString','c':'structured'}}, 'blocks':[header, quote]}
        original = copy.deepcopy(ast)
        slides = layout.slides(ast)
        self.assertEqual(ast, original)
        self.assertIn('quote', slides['blocks'][0]['c'][1][1])
        self.assertIn('hide-title', slides['blocks'][0]['c'][1][1])
        self.assertEqual(layout.plain(slides['blocks'][0]['c'][2]), 'Perspective')
        self.assertEqual(slides['blocks'][1]['c'][1], [quote])

    def test_markdown_and_org_keep_author_and_hidden_heading_roles(self):
        command = converter()
        source = '---\nslide-layout: structured\n---\n\n' + authoring.TEMPLATES['quote']
        org = convert(source, 'markdown', 'org', command)
        for fmt, text in [('markdown', source), ('org', org)]:
            with self.subTest(fmt=fmt):
                ast = read(text, fmt, command)
                title = ast['blocks'][0]
                self.assertEqual(set(title['c'][1][1]), {'quote', 'hide-title', 'hide-claim'})
                self.assertTrue(any(b['t']=='BlockQuote' for b in ast['blocks']))
                self.assertTrue(any('attribution' in layout.classes(b) for b in ast['blocks']))
                self.assertIn('Author, role or publication', layout.plain(ast['blocks']))
