"""One immutable source, two independent display projections."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit import core
from matsugit.document import document


def heading(level, text):
    return {'t':'Header', 'c':[level, [text.lower().replace(' ', '-'), [], []], [{'t':'Str','c':text}]]}


def paragraph(text):
    return {'t':'Para', 'c':[{'t':'Str','c':text}]}


def source(blocks):
    return {'meta':{'title':{'t':'MetaString','c':'Example'},
                    'slide-layout':{'t':'MetaString','c':'structured'}}, 'blocks':blocks}


class DocumentTests(unittest.TestCase):
    def test_claim_becomes_lead_without_rewriting_source_or_other_headings(self):
        ast = source([heading(1,'Example'), heading(1,'Section'), heading(2,'Slide'),
                      heading(3,'The claim'), paragraph('Evidence'), heading(3,'A real subsection'),
                      {'t':'HorizontalRule'}, heading(3,'Continuation claim'), paragraph('More evidence')])
        before = deepcopy(ast)
        result = document(ast)['blocks']
        self.assertEqual(ast, before)
        self.assertEqual(result[0], {'t':'Div', 'c':[['example',[],[]],[]]})
        self.assertEqual(result[1], ast['blocks'][1])
        self.assertEqual(result[3]['c'][1], [paragraph('The claim')])
        self.assertEqual(result[3]['c'][0][0], 'the-claim')
        self.assertEqual(result[5], heading(3,'A real subsection'))
        self.assertEqual(result[6]['c'][1], [paragraph('Continuation claim')])
        self.assertFalse(any(block['t'] == 'HorizontalRule' for block in result))

    def test_default_document_retains_h3_and_rules(self):
        ast = source([heading(2,'Topic'), heading(3,'Subsection'), {'t':'HorizontalRule'}])
        del ast['meta']['slide-layout']
        self.assertEqual(document(ast), ast)

    def test_notes_are_not_reading_content_by_default(self):
        ast = source([heading(2,'Topic'), {'t':'Div','c':[['',['notes'],[]],[paragraph('Private')]]}, paragraph('Public')])
        self.assertNotIn('Private', str(document(ast)))
        self.assertIn('Private', str(ast))


class IndependentRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'deck.md'
        self.source.write_text('An authored source, never a generated view.')
        self.settings = core.config(self.source, {'theme':'default', 'themes_dir':str(self.root / 'themes')})
        self.ast = source([heading(2,'Topic'), heading(3,'Claim'), paragraph('Body')])
        self.calls = []
        def normalize(settings, output, **kwargs):
            (output / 'source.md').write_text(self.source.read_text())
            return deepcopy(self.ast)
        def run(command, *, text=None, cwd=None):
            self.calls.append(command)
            if 'render' in command:
                (Path(cwd) / command[command.index('--output') + 1]).write_text('<html>Rendered</html>')
            return 'Generated view'
        self.addCleanup(patch.stopall)
        patch('matsugit.core.normalize', side_effect=normalize).start()
        patch('matsugit.core.run', side_effect=run).start()

    def test_document_only_never_calls_slide_layout(self):
        output = self.root / 'document'
        with patch('matsugit.core.slide_layout', side_effect=ValueError('Invalid slide composition')):
            result = core.render(self.settings, output, formats=('document',))
        self.assertTrue((output/'index.html').is_file())
        self.assertFalse((output/'slides.qmd').exists())
        self.assertNotIn('href="slides.html"', (output/'navigation.html').read_text())
        self.assertEqual(result['formats'], ['document'])
        self.assertEqual(json.loads((output/'_quarto.yml').read_text())['project']['render'], ['render.qmd'])

    def test_slides_only_never_prepares_reading_document(self):
        output = self.root / 'slides'
        with patch('matsugit.document.document', side_effect=AssertionError('Reading path invoked')):
            core.render(self.settings, output, formats=('slides',))
        self.assertTrue((output/'slides.html').is_file())
        self.assertFalse((output/'render.qmd').exists())
        metadata = json.loads((output/'_quarto.yml').read_text())
        self.assertEqual(metadata['format']['revealjs']['footer'], '')
        self.assertFalse(metadata['format']['html']['format-links'])
        self.assertEqual(len([call for call in self.calls if 'render' in call]), 1)

    def test_handout_requires_slides_before_any_output_write(self):
        output = self.root / 'invalid'
        with self.assertRaisesRegex(core.Error, 'handout requires slides'):
            core.render(dict(self.settings, handout=True), output, formats=('document',))
        self.assertFalse(output.exists())

    def test_cli_only_is_forwarded_and_source_stays_unchanged(self):
        from matsugit.cli import main
        original = self.source.read_bytes()
        with patch('matsugit.cli.render') as render:
            self.assertEqual(main(['render',str(self.source),'--output',str(self.root/'cli'),'--only','slides']), 0)
            self.assertEqual(render.call_args.kwargs['formats'], ('slides',))
        self.assertEqual(self.source.read_bytes(), original)
