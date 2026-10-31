import copy
import json
import os
import shutil
import unittest

from folioforge.authoring import template
from folioforge.components import prepare
from folioforge.core import run
from folioforge.layout import slides
from folioforge.relationships import nodes
from test_layout import container, document, heading, para

QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))


class RelationshipTests(unittest.TestCase):
    def test_implication_is_opt_in_and_preserves_source(self):
        source = container('implication', [heading(4, 'Cause'), para('First'), heading(4, 'Effect'), para('Second')])
        original = copy.deepcopy(source)
        result = prepare(source)
        self.assertEqual(source, original)
        self.assertIn('ff-implication', str(result))
        self.assertIn('ff-relation', str(result))
        self.assertNotIn('ff-relation', str(prepare(container('comparison', original['c'][1]))))

    def test_implication_requires_two_complete_sides(self):
        for parts in ([para('No headings')], [heading(4, 'One'), para('Only one')],
                      [heading(4, 'One'), heading(4, 'Two'), para('Missing content')],
                      [heading(4, x) if i % 2 == 0 else para(x) for i, x in enumerate(['A','a','B','b','C','c'])]):
            with self.assertRaises(ValueError):
                prepare(container('implication', parts))

    def test_explicit_untitled_sides(self):
        result = prepare(container('implication', [container('column', [para('Before')]),
                                                   container('column', [para('After')])]))
        self.assertIn('ff-consequence', str(result))

    def test_relation_options_reject_typos_and_controls(self):
        source = container('implication', [heading(4,'A'),para('A'),heading(4,'B'),para('B')])
        for pairs in ([['relation','']], [['relation','x'*61]], [['relation','a\nb']],
                      [['relaton','supports']], [['relation','a'],['relation','b']]):
            source['c'][0][2] = pairs
            with self.assertRaises(ValueError):
                prepare(source)


@unittest.skipUnless(QUARTO, 'Quarto/Pandoc needed for source fidelity tests')
class MarkdownRelationshipTests(unittest.TestCase):
    def parse(self, text):
        return json.loads(run([QUARTO, 'pandoc', '-f', 'markdown', '-t', 'json'], text=text))

    def test_all_templates_roundtrip_and_keep_one_slide(self):
        for kind in ('implication','mapping','annotated'):
            ast = self.parse(template(kind))
            original = copy.deepcopy(ast)
            result = prepare(ast)
            self.assertEqual(ast, original)
            self.assertIn('ff-' + kind, str(result))
            self.assertEqual(sum(b['t'] == 'Header' for b in slides(result)['blocks']), 1)
            html = run([QUARTO,'pandoc','-f','json','-t','html'], text=json.dumps(result))
            if kind == 'mapping':
                self.assertNotIn('target=', html)

    def test_mapping_retains_markup_unicode_and_escapes(self):
        ast = self.parse('::: {.mapping relation="supports"}\n| Insight | Action |\n|---|---|\n'
                         '| **Caf\u00e9** & <x> | [Proof](https://example.com) and `x` |\n:::')
        result = prepare(ast)
        html = run([QUARTO,'pandoc','-f','json','-t','html'],text=json.dumps(result))
        self.assertIn('<strong>Caf\u00e9</strong>', html)
        self.assertIn('&amp;', html)
        self.assertIn('href="https://example.com"', html)
        self.assertIn('<code>x</code>', html)
        self.assertEqual(html.count('class="ff-mapping-row"'), 1)

    def test_mapping_bounds_and_bad_tables(self):
        for content in ('Not a table', '|A|B|C|\n|-|-|-|\n|1|2|3|',
                        '|A|B|\n|-|-|\n|x||', '|A|B|\n|-|-|\n' + '|x|y|\n'*7):
            with self.assertRaises(ValueError):
                prepare(self.parse('::: mapping\n'+content+'\n:::'))

    def test_callout_targets_are_unique_local_and_nonempty(self):
        text = template('annotated')
        for old, new in [('target="pilot-cycle"','target="missing"'),
                         ('target="pilot-cycle"','target="pilot-rework"'),
                         ('target="pilot-cycle"','target="../../outside"'),
                         ('Cycle time fell by one third.',''),
                         ('#pilot-rework','#pilot-cycle')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                prepare(self.parse(text.replace(old,new)))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            prepare(self.parse(text+'\n[Duplicate]{#pilot-cycle}\n'))
        with self.assertRaisesRegex(ValueError, 'inside its evidence'):
            prepare(self.parse(text.replace('target="pilot-cycle"','target="external"')+'\n[Outside]{#external}\n'))

    def test_numbered_fallback_needs_no_script_and_preserves_order(self):
        result = prepare(self.parse(template('annotated')))
        html = run([QUARTO,'pandoc','-f','json','-t','html'],text=json.dumps(result))
        self.assertIn('href="#pilot-cycle"', html)
        self.assertIn('id="ff-note-pilot-cycle"', html)
        self.assertIn('aria-describedby="ff-note-pilot-cycle"', html)
        self.assertLess(html.index('8 days'), html.index('Cycle time fell'))
        self.assertEqual(sum(n.get('t') == 'Table' for n in nodes(result)), 1)

    def test_too_many_callouts_and_nested_groups_fail(self):
        text=template('annotated')
        extras='\n'.join(f'::: {{.callout target="extra-{n}"}}\nNote.\n:::' for n in range(2))
        with self.assertRaises(ValueError):
            prepare(self.parse(text.replace('\n:::::\n','\n'+extras+'\n:::::\n')))
        with self.assertRaisesRegex(ValueError, 'nested'):
            prepare(self.parse(':::::: annotated\n::::: evidence\n' + text.split('## ',1)[1].split('\n',1)[1] +
                               '\n:::::\n::: {.callout target="pilot-cycle"}\nNote.\n:::\n::::::'))
        with self.assertRaises(ValueError):
            prepare(self.parse('[Outside]{#outside}\n\n::: {.callout target="outside"}\nNote.\n:::'))


if __name__ == '__main__':
    unittest.main()
