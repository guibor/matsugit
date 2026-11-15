"""One immutable source, two independent display projections."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit import core
from matsugit.document import document
from matsugit.layout import slides, metadata


def heading(level, text):
    return {'t':'Header', 'c':[level, [text.lower().replace(' ', '-'), [], []], [{'t':'Str','c':text}]]}


def paragraph(text):
    return {'t':'Para', 'c':[{'t':'Str','c':text}]}


def source(blocks):
    return {'meta':{'title':{'t':'MetaString','c':'Example'},
                    'slide-layout':{'t':'MetaString','c':'structured'}}, 'blocks':blocks}


class DocumentTests(unittest.TestCase):
    def test_collapsing_is_opt_in_and_only_changes_the_reading_projection(self):
        ast = source([heading(2, 'Topic'), paragraph('Evidence'), heading(2, 'More'), paragraph('Detail')])
        original = deepcopy(ast)
        self.assertEqual(document(ast), ast)
        ast['meta']['document-collapsible'] = {'t': 'MetaBool', 'c': False}
        self.assertEqual(document(ast)['blocks'], original['blocks'])
        ast['meta']['document-collapsible']['c'] = True
        before = deepcopy(ast)
        result = document(ast)
        self.assertEqual(result['blocks'][0]['c'][1][1], ['collapsible'])
        self.assertEqual(result['blocks'][2]['c'][1][1], ['collapsible'])
        self.assertEqual(slides(ast)['blocks'], slides(original)['blocks'])
        self.assertEqual(ast, before)

    def test_selected_sections_and_blocks_retain_markers_without_global_option(self):
        ast = source([heading(2, 'Selected'), paragraph('Evidence'), heading(2, 'Ordinary'),
                      {'t': 'Div', 'c': [['detail', ['collapsible'], [['title', 'Supporting detail']]], [paragraph('More')]]}])
        ast['blocks'][0]['c'][1][1].append('collapsible')
        self.assertEqual(document(ast), ast)
        self.assertEqual(document(ast)['blocks'][2]['c'][1][1], [])

    def test_collapsible_metadata_is_a_safe_boolean(self):
        for value in (True, False):
            meta = {'document-collapsible': {'t': 'MetaBool', 'c': value}}
            self.assertEqual(metadata(meta), meta)
        with self.assertRaisesRegex(ValueError, 'document-collapsible must be true or false'):
            metadata({'document-collapsible': {'t': 'MetaString', 'c': 'true'}})

    def test_opening_h2_title_keeps_anchor_claim_and_body_once(self):
        ast = source([{'t':'RawBlock','c':['html','<!-- author note -->']},
                      heading(2,'Example'), heading(3,'Opening claim'), paragraph('Cover evidence'),
                      heading(2,'Example'), paragraph('Later section')])
        before = deepcopy(ast)
        result = document(ast)['blocks']
        self.assertEqual(ast, before)
        self.assertEqual(result[1], {'t':'Div','c':[['example',[],[]],[]]})
        self.assertEqual(result[2]['c'][1], [paragraph('Opening claim')])
        self.assertEqual(result[3], paragraph('Cover evidence'))
        self.assertEqual(result[4], heading(2,'Example'))

    def test_duplicate_title_after_real_intro_is_not_removed(self):
        ast = source([paragraph('Introduction'), heading(2,'Example'), paragraph('Body')])
        self.assertEqual(document(ast), ast)

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


class CoverTests(unittest.TestCase):
    def test_matching_first_slide_uses_authored_cover_without_source_edits(self):
        for layout in ('default', 'structured'):
            with self.subTest(layout=layout):
                ast = source([heading(2,'Example'), heading(3,'Claim'), paragraph('Evidence')])
                ast['meta']['slide-layout']['c'] = layout
                original = deepcopy(ast)
                result = slides(ast)
                self.assertFalse(result['meta']['slide-title-page']['c'])
                self.assertEqual(result['meta']['title'], ast['meta']['title'])
                self.assertIn('Evidence', str(result['blocks']))
                self.assertEqual(ast, original)

    def test_explicit_cover_and_title_page_choice_are_respected(self):
        ast = source([heading(2,'An authored cover'), paragraph('Body')])
        ast['blocks'][0]['c'][1][1] = ['cover']
        self.assertFalse(slides(ast)['meta']['slide-title-page']['c'])
        for choice in (True, False):
            ast['meta']['slide-title-page'] = {'t':'MetaBool','c':choice}
            self.assertEqual(slides(ast)['meta']['slide-title-page']['c'], choice)

    def test_unrelated_first_slide_and_omitted_outline_keep_generated_cover(self):
        for blocks in ([heading(2,'Topic'), paragraph('Body')],
                       [heading(2,'Example'), heading(2,'Topic'), paragraph('Body')],
                       [heading(2,'Topic'), paragraph('Body'), heading(2,'Example'), paragraph('Later')]):
            self.assertNotIn('slide-title-page', slides(source(blocks))['meta'])

    def test_formatted_title_and_comments_match_but_visible_intro_does_not(self):
        ast = source([{'t':'RawBlock','c':['html','<!-- note -->']}, heading(1,'Example')])
        ast['meta']['slide-layout']['c'] = 'default'
        ast['blocks'][1]['c'][2] = [{'t':'Strong','c':[{'t':'Str','c':'Example'}]}]
        self.assertFalse(slides(ast)['meta']['slide-title-page']['c'])
        self.assertEqual(document(ast)['blocks'][1]['t'], 'Div')
        ast['blocks'].insert(0, paragraph('Real introduction'))
        self.assertNotIn('slide-title-page', slides(ast)['meta'])
        self.assertEqual(document(ast), ast)

    def test_cover_policy_change_forces_full_preview_not_heading_patch(self):
        from matsugit.preview import annotate
        ast = source([heading(2,'Example'), paragraph('Body')])
        before = annotate(slides(ast), heading_slots=True)[1]
        ast['blocks'][0]['c'][2] = [{'t':'Str','c':'Different'}]
        after = annotate(slides(ast), heading_slots=True)[1]
        self.assertNotEqual(before['shape'], after['shape'])


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
