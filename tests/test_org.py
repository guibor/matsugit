"""Org and Markdown author the same slides; no document code is evaluated."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from folioforge.authoring import TEMPLATES, template
from folioforge.converter import converter
from folioforge.core import Error, config, normalize, write_json, render, run
from folioforge.components import prepare
from folioforge.layout import slides, plain
from folioforge.source import read, convert, check_org, write_org
from folioforge.table_editor import TableDocument, signature
from folioforge.publish import check_destination, setup_ci
from folioforge.relationships import nodes

try:
    COMMAND = converter()
except Error:
    COMMAND = None


class OrgSafetyTests(unittest.TestCase):
    def test_reject_includes_and_silently_lost_headlines(self):
        for text in ('#+INCLUDE: "/tmp/not-to-read"', '#+SETUPFILE: /tmp/anything',
                     '#+begin_columns\n**** Lost\nbody\n#+end_columns',
                     '#+begin_columns\nbody', '#+end_column'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_org(text)

    def test_example_and_source_content_are_not_directives(self):
        check_org('#+begin_src text\n#+INCLUDE: /tmp/x\n**** Literal\n#+end_src')

    def test_native_published_source_conflicts_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.org'
            source.write_text('* Original\n')
            (root / 'source.md').write_text('# Original\n')
            write_json(root / 'folioforge-manifest.json', {
                'version': 1, 'source_file': 'source.org',
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'normalized_sha256': hashlib.sha256((root/'source.md').read_bytes()).hexdigest(),
                'files': ['source.org', 'source.md']})
            check_destination(root, Path('/tmp/other.org'))
            source.write_text('* Web edit\n')
            with self.assertRaisesRegex(Error, 'source was edited'):
                check_destination(root, Path('/tmp/other.org'))
            check_destination(root, source.resolve())
            (root/'source.md').write_text('# Conflicting generated edit\n')
            with self.assertRaisesRegex(Error, 'Generated source.md was edited'):
                check_destination(root, source.resolve())


@unittest.skipUnless(COMMAND, 'Requires Pandoc; run folioforge setup-editor')
class OrgParityTests(unittest.TestCase):
    def test_org_alignment_and_cell_targets_match_markdown(self):
        md = '| Label | Value |\n|:------|------:|\n| Cycle | [8 days]{#pilot} |\n'
        before = read(md, 'markdown', COMMAND)
        org = convert(md, 'markdown', 'org', COMMAND)
        self.assertIn('<r>', org)
        self.assertIn('<<pilot>>', org)
        after = read(org, 'org', COMMAND)
        tables = [next(n for n in nodes(ast) if n.get('t') == 'Table') for ast in (before, after)]
        self.assertEqual(signature(tables[0]), signature(tables[1]))
        target = next(n for n in nodes(after) if n.get('t') == 'Span' and n['c'][0][0] == 'pilot')
        self.assertEqual(plain(target['c'][1]), '8 days')
        native = TableDocument('| <l> | <r> |\n| Name | Value |\n|------+-------|\n| A | 12 |\n', COMMAND, 'org')
        result = native.serialize(native.html)
        self.assertEqual(result['format'], 'org')
        self.assertIn('<r>', result['markdown'])

    def test_rich_grid_keeps_named_evidence_targets(self):
        ast = read('| Item | Value |\n|------|-------|\n| Cycle | [8 days]{#pilot} |\n', 'markdown', COMMAND)
        table = ast['blocks'][0]
        cell = table['c'][4][0][3][0][1][1]
        cell[4].append({'t': 'Para', 'c': [{'t': 'Str', 'c': 'Context.'}]})
        org = write_org(ast, COMMAND)
        self.assertIn('#+begin_export markdown', org)
        after = read(org, 'org', COMMAND)
        target = next(n for n in nodes(after) if n.get('t') == 'Span' and n['c'][0][0] == 'pilot')
        self.assertEqual(plain(target['c'][1]), '8 days')
        self.assertIn('Context.', plain(after['blocks']))

    def test_every_recipe_has_an_org_equivalent(self):
        for name in TEMPLATES:
            with self.subTest(name=name):
                md = read(template(name), 'markdown', COMMAND)
                org_text = template(name, fmt='org')
                org = read(org_text, 'org', COMMAND)
                self.assertIn('#+SLIDE_LAYOUT: structured', org_text)
                self.assertNotIn('::: ', org_text)
                self.assertEqual(' '.join(plain(org['blocks']).split()), ' '.join(plain(md['blocks']).split()))
                md_slides = slides(prepare(md))
                org_slides = slides(prepare(org))
                self.assertEqual(len(md_slides['blocks']), len(org_slides['blocks']))
                self.assertEqual(' '.join(plain(md_slides['blocks']).split()), ' '.join(plain(org_slides['blocks']).split()))

    def test_metadata_booleans_and_invalid_values(self):
        ast = read('#+TITLE: A\n#+SLIDE_LAYOUT: structured\n#+SLIDE_SECTION_DIVIDERS: false\n'
                   '#+SLIDE_TITLE_PAGE: false\n#+SLIDE_ASPECT_RATIO: 4:3\n** Slide\nBody', 'org', COMMAND)
        self.assertFalse(ast['meta']['slide-section-dividers']['c'])
        self.assertFalse(ast['meta']['slide-title-page']['c'])
        self.assertEqual(ast['meta']['slide-aspect-ratio']['c'], '4:3')
        for value in ('yes', '"false"', '1'):
            with self.assertRaises(ValueError):
                read('#+SLIDE_TITLE_PAGE: ' + value, 'org', COMMAND)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            read('#+SLIDE_LAYOUT: structured\n#+SLIDE_LAYOUT: default', 'org', COMMAND)

    def test_native_cells_links_unicode_and_alignment_survive(self):
        source = '| Name | Value |\n|------+-------|\n| *Alpha* /beta/ שלום | [[https://example.invalid][Link]] |\n'
        table = TableDocument(source, COMMAND, 'org')
        result = table.serialize(table.html)
        self.assertEqual(result['format'], 'org')
        self.assertIn('*Alpha*', result['markdown'])
        self.assertEqual(signature(table.table), signature(TableDocument(result['markdown'], COMMAND, 'org').table))
        with self.assertRaisesRegex(Error, 'formula tables'):
            TableDocument(source + '#+TBLFM: $2=$1\n', COMMAND, 'org')

    def test_merged_cells_and_lists_use_readable_org_grid(self):
        source = '| A | B |\n|---+---|\n| x | y |\n'
        table = TableDocument(source, COMMAND, 'org')
        for html in ('<table><tr><th colspan="2">Group</th></tr><tr><td rowspan="2">North</td><td>A</td></tr><tr><td>B</td></tr></table>',
                     '<table><tr><th>Name</th><th>Detail</th></tr><tr><td>Alpha</td><td><ul><li>One</li><li>Two</li></ul></td></tr></table>'):
            result = table.serialize(html)
            self.assertEqual(result['format'], 'org-grid')
            self.assertTrue(result['markdown'].startswith('#+begin_export markdown\n+'))
            self.assertNotIn('<table', result['markdown'])
            again = TableDocument(result['markdown'], COMMAND, 'org')
            self.assertEqual(signature(again.table), signature(TableDocument(result['markdown'], COMMAND, 'org').table))
            if 'rowspan' in html:
                self.assertIn('rowspan="2"', again.html)
                self.assertIn('colspan="2"', again.html)

    def test_native_export_roundtrip_keeps_mermaid_math_and_code_inert(self):
        md = ('---\ntitle: Native source\nslide-layout: structured\n---\n'
              '## Evidence\n### Smaller claim\n\n'
              '```mermaid\nflowchart LR\n A --> B\n```\n\n'
              '$E=mc^2$ and **bold**.\n\n'
              '```python\nraise RuntimeError("never execute")\n```\n\n'
              '::: notes\nPresenter detail.\n:::\n\n---\n\nContinuation.\n')
        org = convert(md, 'markdown', 'org', COMMAND)
        self.assertIn('#+begin_src mermaid', org)
        before, after = read(md, 'markdown', COMMAND), read(org, 'org', COMMAND)
        self.assertEqual(' '.join(plain(before['blocks']).split()), ' '.join(plain(after['blocks']).split()))
        self.assertEqual(len(slides(prepare(before))['blocks']), len(slides(prepare(after))['blocks']))

    def test_large_table_input_is_not_silently_truncated(self):
        source = '| Item | Value |\n|------+-------|\n' + ''.join(
            f'| [[https://example.invalid/{i}][Item {i}]] | {i} |\n' for i in range(200))
        table = TableDocument(source, COMMAND, 'org')
        result = table.serialize(table.html)
        self.assertEqual(result['rows'], 201)
        self.assertIn('Item 199', result['markdown'])

    def test_agent_comments_are_not_rendered_or_copied_to_exports(self):
        comments = {
            'markdown': '## Slide\n\nVisible.\n\n:::: {.agent-comment #review-1 status="open"}\nRequest:\nPRIVATE_SENTINEL\n![not an asset](missing.png)\nResponse:\nPending.\n::::\n\n## Next\n\nAlso visible.\n',
            'org': '** Slide\n\nVisible.\n\n#+begin_agent-comment :id "review-1" :status "open"\nRequest:\nPRIVATE_SENTINEL\n[[file:missing.png]]\n#+INCLUDE: /tmp/do-not-read\nResponse:\nPending.\n#+end_agent-comment\n\n** Next\n\nAlso visible.\n'}
        for fmt, source in comments.items():
            with self.subTest(fmt=fmt):
                ast = read(source, fmt, COMMAND)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(ast))
                self.assertIn('Also', json.dumps(ast))
                for target in ('org', 'markdown'):
                    exported = convert(source, fmt, target, COMMAND)
                    self.assertNotIn('PRIVATE_SENTINEL', exported)
                    self.assertNotIn('missing.png', exported)
                    self.assertIn('Also visible.', exported)

    def test_comment_syntax_inside_code_is_literal(self):
        for fmt, source in (
            ('markdown', '```text\n::: agent-comment\nLITERAL\n:::\n```\n'),
            ('org', '#+begin_src text\n#+begin_agent-comment\nLITERAL\n#+end_agent-comment\n#+end_src\n')):
            self.assertIn('LITERAL', json.dumps(read(source, fmt, COMMAND)))


@unittest.skipUnless(os.environ.get('QUARTO'), 'Set QUARTO for actual source normalization')
class OrgNormalizationTests(unittest.TestCase):
    def test_standalone_ci_rebuilds_native_source_and_hides_new_comments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'deck.org'
            source.write_text('#+TITLE: Deck\n#+SLIDE_LAYOUT: structured\n** Evidence\n'
                              '#+begin_takeaway\nKeep meaning.\n#+end_takeaway\n')
            output = root/'folioforge-site/deck'
            render(config(source, {'quarto': os.environ['QUARTO']}), output,
                   edit_url='https://example.invalid/edit/source.org')
            with (output/'source.org').open('a') as stream:
                stream.write('\n** Web edit\nNew Org evidence.\n\n'
                             '#+begin_agent-comment :status "open"\nCI_HIDDEN_SENTINEL\n'
                             '[[file:not-an-asset.png]]\n#+end_agent-comment\n')
            setup_ci(config(source), 'github')
            run([os.sys.executable, '.folioforge-ci/build.py'], cwd=root)
            for name in ('slides.html', 'index.html', 'source.md', 'source.org'):
                text = (output/name).read_text()
                self.assertIn('New Org evidence.', text)
                self.assertNotIn('CI_HIDDEN_SENTINEL', text)
            self.assertIn('href="https://example.invalid/edit/source.org"', (output/'index.html').read_text())

    def test_native_source_is_rebuildable_with_relocated_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            source = root/'deck.org'
            source.write_text('#+TITLE: Deck\n#+SLIDE_LAYOUT: structured\n** Evidence\n'
                              '[[file:figure.svg]]\n\n#+begin_takeaway\nKeep meaning.\n#+end_takeaway\n')
            first, second = root/'one', root/'two'
            first.mkdir(); second.mkdir()
            ast = normalize(config(source, {'quarto': os.environ['QUARTO']}), first)
            saved = (first/'source.org').read_text()
            self.assertIn('assets/', saved)
            self.assertIn('#+SLIDE_LAYOUT: structured', saved)
            rebuilt = normalize(config(first/'source.org', {'quarto': os.environ['QUARTO']}), second)
            self.assertEqual(' '.join(plain(ast['blocks']).split()), ' '.join(plain(rebuilt['blocks']).split()))
            self.assertEqual(saved, (second/'source.org').read_text())
