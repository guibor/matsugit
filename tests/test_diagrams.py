import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from matsugit import diagrams
from matsugit.core import install_theme, normalize, run, config

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40"><text x="5" y="25">Evidence</text></svg>'
QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))
REAL = (diagrams.runtime_path() / 'node_modules/@d2lang/d2/package.json').is_file()


def block(code='a -> b', options=None):
    return {'t': 'CodeBlock', 'c': [['evidence', ['d2', 'media-half'], list((options or {}).items())], code]}


class DiagramTests(unittest.TestCase):
    def test_theme_palette_and_validation(self):
        result = diagrams.style({'layout': 'dagre', 'palette': {'B1': '#123456'}}, {'accent': '#abcdef'})
        self.assertEqual(result['palette']['B1'], '#123456')
        self.assertEqual(result['palette']['B2'], '#abcdef')
        for theme in ({'layout': 'shell'}, {'palette': {'B1': 'red'}}, {'palette': {'not-a-token': '#123456'}}, {'include': '/tmp/x'}):
            with self.assertRaises(ValueError):
                diagrams.style(theme)

    def test_theme_manifest_copies_and_inherits_diagrams(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('base', 'child', 'out'):
                (root / name).mkdir()
            (root / 'base/theme.json').write_text(json.dumps({'document': 'doc.css', 'slides': 'slides.scss', 'diagrams': 'd2.json'}))
            for name in ('doc.css', 'slides.scss', 'd2.json'):
                (root / 'base' / name).write_text('{}')
            (root / 'child/theme.json').write_text('{"extends":"base"}')
            theme = install_theme({'themes_dir': root, 'theme': 'child'}, root / 'out')
            self.assertEqual(theme['diagrams'], 'd2.json')
            self.assertTrue((root / 'out/theme/d2.json').is_file())

    def test_prepare_is_opt_in_preserves_source_and_caches(self):
        source = block()
        original = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as temp, patch.object(diagrams, 'render_svg', return_value=SVG) as render:
            root = Path(temp)
            first = diagrams.prepare(source, root, cache=root / 'cache')
            second = diagrams.prepare(source, root, cache=root / 'cache')
            self.assertEqual(first, second)
            render.assert_called_once()
            self.assertIn('media-half', first['c'][0][1])
            self.assertIn('ff-d2', first['c'][0][1])
            self.assertNotIn('ff-diagram', first['c'][0][1])
            self.assertEqual(source, original)
            self.assertEqual(first['c'][1][0]['c'][0]['c'][1], [])
            self.assertEqual(dict(first['c'][0][2])['aria-label'], 'D2 diagram')
            diagrams.prepare(block('a -> c'), root, cache=root / 'cache')
            diagrams.prepare(source, root, {'palette': {'B1': '#654321'}}, cache=root / 'cache')
            self.assertEqual(render.call_count, 3)
            mermaid = {'t': 'CodeBlock', 'c': [['', ['mermaid'], []], 'flowchart LR\n A-->B']}
            self.assertEqual(diagrams.prepare(mermaid, root), mermaid)
            self.assertFalse(diagrams.contains(mermaid))

    def test_bad_options_and_missing_backend_are_actionable(self):
        with self.assertRaisesRegex(ValueError, 'block options'):
            diagrams.prepare(block(options={'eval': 'true'}), '/unused')
        with patch.dict(os.environ, {'MATSUGIT_DIAGRAM_RUNTIME': '/nonexistent'}):
            with self.assertRaisesRegex(ValueError, 'setup-diagrams'):
                diagrams.render_svg('a -> b', diagrams.style())
        for code in ('', 'x' * 64001):
            with self.assertRaises(ValueError):
                diagrams.render_svg(code, diagrams.style())

    def test_svg_rejects_external_and_active_content(self):
        self.assertEqual(diagrams.validate_svg(SVG), SVG)
        for content in ('<script>alert(1)</script>', '<image href="https://example.invalid/x"/>',
                        '<a href="javascript:alert(1)">x</a>', '<text onload="x()"/>',
                        '<style>@import "https://example.invalid/x";</style>',
                        '<style>text{fill:url(https://example.invalid)}</style>',
                        '<path fill="url(https://example.invalid/x.svg#y)"/>',
                        '<foreignObject><iframe src="file:///etc/passwd"/></foreignObject>'):
            with self.subTest(content=content), self.assertRaises(ValueError):
                diagrams.validate_svg(SVG.replace('</svg>', content + '</svg>'))

    @unittest.skipUnless(QUARTO, 'Quarto required for parser parity')
    def test_org_markdown_normalize_same_diagram_and_keep_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            results = []
            for extension, text in (('md', '```d2\na -> b\n```\n'), ('org', '#+begin_src d2\na -> b\n#+end_src\n')):
                source = root / ('input.' + extension)
                source.write_text(text)
                output = root / extension
                output.mkdir()
                ast = normalize({'source': source, 'source_root': root, 'quarto': QUARTO}, output)
                results.append(ast['blocks'][0])
                self.assertIn('a -> b', (output / 'source.md').read_text())
                self.assertTrue(diagrams.contains(ast))
            self.assertEqual(results[0]['c'][0], results[1]['c'][0])
            self.assertEqual(results[0]['c'][1].rstrip(), results[1]['c'][1].rstrip())

    @unittest.skipUnless(REAL, 'Optional D2 runtime not installed')
    def test_real_renderer_determinism_unicode_and_security(self):
        appearance = diagrams.style({'palette': {'B1': '#123456'}})
        code = 'direction: right\na: Insight\nb: פעולה\na -> b: informs'
        first = diagrams.render_svg(code, appearance)
        self.assertEqual(first, diagrams.render_svg(code, appearance))
        self.assertIn('Insight', first)
        self.assertIn('פעולה', first)
        self.assertIn('#123456', first)
        for bad in ('x: @/etc/passwd', 'x: @https://example.invalid/secret',
                    'x.icon: https://example.invalid/image.svg', 'x.link: javascript:alert(1)',
                    'layers: {next: {a -> b}}'):
            with self.subTest(code=bad), self.assertRaises(ValueError):
                diagrams.render_svg(bad, appearance)

    @unittest.skipUnless(REAL and QUARTO, 'D2 runtime and Quarto required')
    def test_pptx_contains_diagram_not_code(self):
        from matsugit.exports import export_file
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'diagram.md'
            source.write_text('---\nslide-layout: structured\n---\n## Evidence\n\n```d2\na -> b: informs\n```\n')
            export_file(config(source, {'quarto': QUARTO}), 'pptx', root / 'diagram.pptx')
            with zipfile.ZipFile(root / 'diagram.pptx') as archive:
                self.assertTrue(any(name.startswith('ppt/media/') for name in archive.namelist()))
                xml = b''.join(archive.read(n) for n in archive.namelist()
                               if n.startswith('ppt/slides/') and n.endswith('.xml')).decode()
                self.assertIn('Evidence', xml)
                self.assertNotIn('a -&gt; b', xml)


if __name__ == '__main__':
    unittest.main()
