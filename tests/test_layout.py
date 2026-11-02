"""Synthetic regression tests for preview/publishing slide conventions."""
from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import config, normalize, render, run
from matsugit.layout import metadata, slides
from matsugit.publish import setup_ci


def heading(level, text):
    return {'t':'Header', 'c':[level, [text.lower().replace(' ', '-'), [], []], [{'t':'Str','c':text}]]}


def para(text):
    return {'t':'Para', 'c':[{'t':'Str','c':text}]}


def container(name, blocks):
    return {'t':'Div','c':[['',[name],[]],blocks]}


def document(blocks, layout='structured', dividers=False, empty=False):
    return {'meta': {'title':{'t':'MetaInlines','c':[{'t':'Str','c':'Example deck'}]},
                     'slide-layout':{'t':'MetaString','c':layout},
                     'slide-section-dividers':{'t':'MetaBool','c':dividers},
                     'slide-empty-slides':{'t':'MetaBool','c':empty}}, 'blocks':blocks}


class LayoutTests(unittest.TestCase):
    def test_aspect_and_title_page_are_safe_opt_in_display_settings(self):
        value=metadata({'slide-aspect-ratio':{'t':'MetaString','c':'4:3'},
                        'slide-title-page':{'t':'MetaBool','c':False}})
        self.assertEqual(value['slide-title-page']['c'],False)
        self.assertEqual(value['slide-aspect-ratio']['c'],'4:3')
        for bad in ('1:0','100000:1','4:3;execute'):
            with self.assertRaises(ValueError):metadata({'slide-aspect-ratio':{'t':'MetaString','c':bad}})
        with self.assertRaises(ValueError):metadata({'slide-title-page':{'t':'MetaString','c':'false'}})

    def test_personal_default_never_overrides_explicit_theme(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'MATSUGIT_CONFIG':str(Path(directory)/'absent.json'),
                'MATSUGIT_DEFAULT_THEME':'personal'}):
            source=Path(directory)/'test.md'
            source.write_text('# Test')
            self.assertEqual(config(source)['theme'],'personal')
            self.assertEqual(config(source, {'theme':'work'})['theme'],'work')

    def test_safe_metadata_preserved_and_executable_keys_removed(self):
        meta = document([])['meta']
        meta['filters'] = {'t':'MetaString','c':'do-not-run.lua'}
        result = metadata(meta)
        self.assertEqual(result['slide-section-dividers'], {'t':'MetaBool','c':False})
        self.assertIn('title',result)
        self.assertNotIn('filters',result)

    def test_bad_options_fail_instead_of_silent_default(self):
        for key, value in (('slide-layout', 'unknown'), ('slide-section-dividers', 'false'),
                           ('slide-empty-slides', 'true')):
            with self.assertRaises(ValueError):
                metadata({key:{'t':'MetaString','c':value}})

    def test_structured_hierarchy_takeaway_and_empty_outline(self):
        ast = document([heading(1,'Section'), heading(2,'Title'), heading(3,'Smaller claim'),
                        heading(4,'Evidence'), para('Body'), container('takeaway',[para('Conclusion')]),
                        heading(2,'Empty outline')])
        before = deepcopy(ast)
        result = slides(ast)
        self.assertEqual(ast,before)
        self.assertEqual([b['c'][2] for b in result['blocks'] if b['t']=='Header'], [heading(2,'Title')['c'][2]])
        self.assertEqual([b['c'][0][1] for b in result['blocks'] if b['t']=='Div'],
                         [['claim','ff-claim'],['ff-body'],['takeaway','ff-takeaway']])
        body = result['blocks'][2]['c'][1]
        self.assertEqual(body[0]['t'],'Div')
        self.assertIn(['aria-level','4'], body[0]['c'][0][2])

    def test_manual_break_inherits_claim_and_no_blank_trailing_slide(self):
        ast = document([heading(1,'Section'),heading(2,'Title'),heading(3,'Claim'),para('First'),
                        {'t':'HorizontalRule'},para('Second'),{'t':'HorizontalRule'}])
        result = slides(ast)['blocks']
        self.assertEqual(len([b for b in result if b['t']=='Header']),2)
        claims=[b for b in result if b['t']=='Div' and 'claim' in b['c'][0][1]]
        self.assertEqual(len(claims),2)
        self.assertEqual(claims[0],claims[1])

    def test_dividers_and_empty_slides_are_explicit_options(self):
        blocks=[heading(1,'Section'),heading(2,'Empty')]
        self.assertEqual(slides(document(blocks))['blocks'],[])
        result=slides(document(blocks,dividers=True,empty=True))['blocks']
        self.assertEqual(len([b for b in result if b['t']=='Header']),2)

    def test_section_intro_is_retained_without_divider(self):
        result=slides(document([heading(1,'Section'),para('Introduction'),heading(2,'Title'),para('Body')]))
        self.assertIn('Introduction',str(result))
        self.assertEqual(len([b for b in result['blocks'] if b['t']=='Header']),2)

    def test_legacy_title_claim_uses_parent_title(self):
        result=slides(document([heading(1,'Topic'),heading(2,'Longer claim'),para('Body')],layout='title-claim'))
        self.assertEqual(result['blocks'][0]['c'][2],heading(2,'Topic')['c'][2])
        self.assertEqual(result['blocks'][1]['c'][1][0]['c'],heading(2,'Longer claim')['c'][2])

    def test_h4_columns_are_supported_without_nested_slide_headers(self):
        result=slides(document([heading(2,'Title'), container('columns',[
            heading(4,'Left'),para('A'),heading(4,'Right'),para('B')])]))
        columns=result['blocks'][1]['c'][1][0]
        self.assertEqual(len(columns['c'][1]),2)
        self.assertEqual(columns['c'][1][0]['c'][1][0]['t'],'Div')

    def test_default_layout_preserves_original_slide_structure(self):
        ast=document([heading(1,'Section'),heading(2,'Title'),para('Body')],layout='default')
        del ast['meta']['slide-section-dividers']
        del ast['meta']['slide-empty-slides']
        self.assertEqual(slides(ast),ast)

    def test_rows_support_explicit_and_heading_forms_without_changing_content(self):
        for blocks in ([container('row',[para('First')]),container('row',[para('Second')])],
                       [heading(4,'First section'),para('First'),heading(4,'Second section'),para('Second')]):
            ast=document([heading(2,'Title'),container('rows',blocks)])
            before=deepcopy(ast)
            result=slides(ast)
            self.assertEqual(ast,before)
            rows=result['blocks'][1]['c'][1][0]
            self.assertEqual(rows['c'][0][1],['ff-rows'])
            self.assertEqual([p['c'][0][1] for p in rows['c'][1]],[['ff-row'],['ff-row']])
            self.assertIn('First',str(rows))
            self.assertIn('Second',str(rows))

    def test_rows_reject_ambiguous_empty_and_single_sections(self):
        for blocks in ([para('Not sections')], [container('row',[para('Only')])],
                       [container('row',[]),container('row',[para('Second')])],
                       [heading(4,'First'),para('A'),container('row',[para('Mixed')])]):
            with self.assertRaises(ValueError):
                slides(document([heading(2,'Title'),container('rows',blocks)]))

    def test_columns_can_be_nested_in_rows(self):
        result=slides(document([heading(2,'Title'),container('rows',[
            container('row',[container('columns',[heading(4,'A'),para('One'),heading(4,'B'),para('Two')])]),
            container('row',[para('Conclusion')])])]))
        row=result['blocks'][1]['c'][1][0]['c'][1][0]
        columns=row['c'][1][0]
        self.assertEqual(len(columns['c'][1]),2)
        self.assertTrue(all(part['c'][1][0]['t']=='Div' for part in columns['c'][1]))

    def test_explicit_divider_option_also_works_in_default_layout(self):
        ast=document([heading(1,'Section'),heading(2,'Title'),para('Body')],layout='default')
        result=slides(ast)
        self.assertEqual(len([b for b in result['blocks'] if b['t']=='Header']),1)


QUARTO=os.environ.get('QUARTO',shutil.which('quarto'))
FIXTURE='''---
title: Synthetic layout regression
slide-layout: structured
slide-section-dividers: false
filters: [never-run.lua]
---

# Section not a slide

## A clear title

### A smaller explanatory claim

#### Evidence

| Item | Value |
| ---- | ----- |
| First | 12 |

::: takeaway
A separate conclusion.
:::

---

Second segment with the same title and claim.

## Empty outline
'''


@unittest.skipUnless(QUARTO,'Set QUARTO for real rendering tests')
class LayoutRenderTests(unittest.TestCase):
    def test_reference_aspect_and_authored_cover_keep_document_title(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'input.md'
            source.write_text('---\ntitle: Test deck\nslide-layout: structured\nslide-aspect-ratio: "4:3"\nslide-title-page: false\nslide-empty-slides: true\n---\n\n## An authored statement {.statement}\n')
            output=root/'output'
            render(config(source,{'quarto':QUARTO}),output)
            deck=(output/'slides.html').read_text()
            self.assertNotIn('id="title-slide"',deck)
            self.assertIn('An authored statement',deck)
            self.assertIn('Test deck',(output/'index.html').read_text())
            self.assertIn('"height": 960',(output/'_quarto.yml').read_text())

    def test_standalone_ci_preserves_layout_and_document_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.md'
            source.write_text(FIXTURE)
            output = root / 'matsugit-site/example'
            render(config(source, {'quarto': QUARTO}), output)
            setup_ci(config(source), 'github')
            with patch.dict(os.environ, {'QUARTO': QUARTO}):
                run([os.sys.executable, '.matsugit-ci/build.py'], cwd=root)
            deck = (output / 'slides.html').read_text()
            self.assertIn('ff-claim', deck)
            self.assertIn('continuation-2', deck)
            self.assertNotIn('Empty outline', deck)
            self.assertIn('Empty outline', (output / 'index.html').read_text())
            self.assertIn('slide-layout: structured', (output / 'source.md').read_text())

    def test_metadata_roundtrip_and_separate_document_slide_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'input.md'
            source.write_text(FIXTURE)
            output=root/'output'
            render(config(source,{'quarto':QUARTO}),output)
            normalized=(output/'source.md').read_text()
            self.assertIn('slide-layout: structured',normalized)
            self.assertIn('slide-section-dividers: false',normalized)
            self.assertNotIn('never-run.lua',normalized)
            self.assertIn('Empty outline',(output/'index.html').read_text())
            deck=(output/'slides.html').read_text()
            self.assertNotIn('Empty outline',deck)
            self.assertNotIn('Section not a slide',deck)
            self.assertIn('ff-claim',deck)
            self.assertIn('ff-takeaway',deck)
            self.assertIn('continuation-2',deck)
            self.assertIn('<table',deck)
            second=root/'normalized-again'
            second.mkdir()
            normalize(config(output/'source.md',{'quarto':QUARTO}),second)
            self.assertEqual(normalized,(second/'source.md').read_text())
