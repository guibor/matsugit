"""Math conversion operates on parsed nodes, never on source-text patterns."""
from copy import deepcopy
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import config, math_html, normalize, run


class MathTests(unittest.TestCase):
    def test_math_is_escaped_and_source_ast_is_untouched(self):
        for kind, delimiter in [('InlineMath', r'\('), ('DisplayMath', r'\[')]:
            tex = r'\text{<tag> & "quoted"} + \frac{x}{y}'
            node = {'t': 'Math', 'c': [{'t': kind}, tex]}
            before = deepcopy(node)
            result = math_html(node)
            self.assertEqual(node, before)
            self.assertEqual(result['t'], 'RawInline')
            self.assertIn('matsugit-math', result['c'][1])
            self.assertIn(delimiter + tex, unescape(result['c'][1]))
            self.assertNotIn('<tag>', result['c'][1])

    def test_code_currency_and_raw_html_are_not_reinterpreted(self):
        nodes = [{'t': 'Str', 'c': '$10M'},
                 {'t': 'Code', 'c': [['', [], []], r'\(x\)']},
                 {'t': 'CodeBlock', 'c': [['', ['latex'], []], '$$x$$']},
                 {'t': 'RawInline', 'c': ['html', '<span>$x$</span>']}]
        self.assertEqual(math_html(nodes), nodes)

    def test_math_in_nested_tables_and_metadata(self):
        node = {'meta': {'title': {'t': 'MetaInlines', 'c': [
            {'t': 'Math', 'c': [{'t': 'InlineMath'}, 'x']}]}},
            'blocks': [{'t': 'Table', 'c': [[{'t': 'Para', 'c': [
                {'t': 'Math', 'c': [{'t': 'InlineMath'}, 'y']}]}]]}]}
        result = math_html(node)
        self.assertEqual(result['meta']['title']['c'][0]['t'], 'RawInline')
        self.assertEqual(result['blocks'][0]['c'][0][0]['c'][0]['t'], 'RawInline')

    def test_bundled_mathjax_matches_reviewed_upstream(self):
        runtime = Path(__file__).resolve().parents[1] / 'matsugit/runtime'
        self.assertEqual(hashlib.sha256((runtime/'mathjax-tex-svg.js').read_bytes()).hexdigest(),
                         'a4354ff94fd868aea0cc6eaaa79a57fda0588646fc46ee3700a349ee0a11cbe6')
        self.assertIn('Apache License', (runtime/'MATHJAX-LICENSE').read_text())

    @unittest.skipUnless(os.environ.get('QUARTO'), 'Set QUARTO for Markdown/Org math parity')
    def test_org_and_markdown_keep_the_same_math(self):
        quarto = os.environ['QUARTO']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'MATSUGIT_CONFIG':str(root/'absent.json')}):
                results = []
                for suffix, text in [('md', '# Test\n\n$x$\n\n$$\\frac{x}{y}$$\n'),
                                     ('org', '* Test\n\n\\(x\\)\n\n\\[\\frac{x}{y}\\]\n')]:
                    source = root / ('math.' + suffix); source.write_text(text)
                    output = root / suffix; output.mkdir()
                    ast = normalize(config(source, {'quarto':quarto}), output)
                    rendered = run([quarto, 'pandoc', '-f', 'json', '-t', 'html'],
                                   text=json.dumps(math_html(ast)))
                    results.append(rendered)
                    self.assertEqual(rendered.count('matsugit-math'), 2)
                self.assertEqual(results[0], results[1])
