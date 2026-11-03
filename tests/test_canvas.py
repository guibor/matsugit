import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import Error, config, normalize, canvas_components, render
from matsugit.converter import converter
from matsugit.source import convert


class CanvasTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {'MATSUGIT_CONFIG':str(self.root/'empty.json')})
        env.start(); self.addCleanup(env.stop)
        self.source = self.root / 'deck.md'
        self.html = self.root / 'visual.html'
        self.html.write_text('<h1>Evidence &amp; insight</h1><script>window.example = 1</script>')
        self.source.write_text('---\ntitle: Canvas\nslide-layout: structured\n---\n## Evidence\n\n::: {.canvas src="visual.html" title="Example & evidence"}\n:::\n')

    def prepared(self, source=None):
        output = self.root / ('output-' + str(len(list(self.root.glob('output-*'))))); output.mkdir()
        settings = config(source or self.source)
        ast = normalize(dict(settings, _preview_pandoc=converter()), output)
        return output, ast, canvas_components(ast, output)

    def test_markdown_org_canvas_is_isolated_and_source_stays_editable(self):
        for fmt in ('markdown', 'org'):
            source = self.source
            if fmt == 'org':
                source = self.root / 'deck.org'
                source.write_text(convert(self.source.read_text(), 'markdown', 'org', converter()))
            output, _, display = self.prepared(source)
            html = json.dumps(display)
            self.assertIn('ff-canvas-dialog', html)
            self.assertIn('sandbox=\\"\\"', html)
            self.assertIn('default-src', html)
            self.assertIn('connect-src', html)
            self.assertNotIn('allow-same-origin', html)
            saved = output / ('source.org' if fmt == 'org' else 'source.md')
            self.assertIn('canvas', saved.read_text())
            self.assertNotIn('iframe', saved.read_text())

    def test_scripts_only_enabled_explicitly(self):
        self.source.write_text(self.source.read_text().replace('title="Example & evidence"', 'title="Example & evidence" interactive="true"'))
        _, _, display = self.prepared()
        self.assertIn('allow-scripts', json.dumps(display))
        self.assertNotIn('allow-same-origin', json.dumps(display))

    def test_unsafe_or_missing_sources_fail(self):
        for src in ('https://example.invalid/app', '../secret.html', '.private.html', 'visual.html?x=1'):
            self.source.write_text('::: {.canvas title="Evidence" src="'+src+'"}\n:::\n')
            with self.assertRaises((Error, ValueError)): self.prepared()
        self.source.write_text('::: {.canvas src="visual.html"}\n:::\n')
        with self.assertRaisesRegex(ValueError, 'title'): self.prepared()

    def test_powerpoint_refuses_canvas_without_losing_an_existing_export(self):
        from matsugit.exports import export_file
        output = self.root / 'deck.pptx'
        output.write_bytes(b'existing reviewed deck')
        settings = dict(config(self.source), _preview_pandoc=converter())
        with self.assertRaisesRegex(Error, 'cannot be embedded'):
            export_file(settings, 'pptx', output, replace=True)
        self.assertEqual(output.read_bytes(), b'existing reviewed deck')

    @unittest.skipUnless(os.environ.get('QUARTO'), 'Set QUARTO for canvas renderer parity')
    def test_both_outputs_contain_canvas_and_document_is_not_paginated(self):
        output = self.root / 'render'
        render(config(self.source), output)
        for name in ('index.html', 'slides.html'):
            html = (output / name).read_text()
            self.assertTrue('ff-canvas-frame' in html, name)
            self.assertTrue('ff-canvas-expand' in html, name)
        self.assertNotIn('class="reveal"', (output / 'index.html').read_text())


if __name__ == '__main__': unittest.main()
