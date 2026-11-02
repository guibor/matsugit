"""Snapshot invalidation and inert text patches, without publishing any content."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from matsugit import core, preview, charts


class AnchorTests(unittest.TestCase):
    def test_inlines_not_geometry_are_replaceable(self):
        ast = {'meta': {}, 'blocks': [{'t': 'Para', 'c': [{'t': 'Str', 'c': 'Hello'}]}]}
        annotated, first = preview.annotate(ast)
        changed = deepcopy(ast)
        changed['blocks'][0]['c'] = [{'t': 'Strong', 'c': [{'t': 'Str', 'c': 'Goodbye'}]}]
        _, second = preview.annotate(changed)
        self.assertEqual(first['shape'], second['shape'])
        self.assertNotEqual(first['slots'], second['slots'])
        self.assertEqual(ast['blocks'][0]['c'][0]['t'], 'Str')
        self.assertEqual(annotated['blocks'][0]['c'][0]['t'], 'Span')
        changed['blocks'].append({'t': 'HorizontalRule'})
        self.assertNotEqual(preview.annotate(changed)[1]['shape'], first['shape'])

    def test_active_or_initialized_content_never_becomes_a_patch(self):
        for node in ({'t': 'RawInline', 'c': ['html', '<b>raw</b>']},
                     {'t': 'Math', 'c': [{'t': 'InlineMath'}, 'x']},
                     {'t': 'Note', 'c': []}, {'t': 'Code', 'c': [['', [], []], 'x']},
                     {'t': 'Image', 'c': []},
                     {'t': 'Link', 'c': [['', [], []], [], ['assets/x.pdf', '']]}):
            self.assertFalse(preview.safe_inlines([node]), node)

    def test_headings_remain_global_dependencies_for_toc_menu_and_anchors(self):
        ast = {'meta': {}, 'blocks': [{'t': 'Header', 'c': [2, ['stable', [], []], [{'t': 'Str', 'c': 'Before'}]]}]}
        first = preview.annotate(ast)[1]
        ast['blocks'][0]['c'][2][0]['c'] = 'After'
        self.assertNotEqual(first['shape'], preview.annotate(ast)[1]['shape'])

    def test_chart_cache_avoids_regenerating_unchanged_exhibits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {'caption': 'Synthetic', 'headers': ['X', 'Y'], 'unit': 'count'}
            result = {'svg': '<svg/>', 'spec': None}
            with patch('matsugit.charts.render_chart', return_value=result) as worker:
                charts.save_chart(data, root / 'first', cache=root / 'cache')
                charts.save_chart(data, root / 'second', cache=root / 'cache')
                self.assertEqual(worker.call_count, 1)
                charts.save_chart(data, root / 'third', colours={'accent': '#ffffff'}, cache=root / 'cache')
                self.assertEqual(worker.call_count, 2)


QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))


@unittest.skipUnless(QUARTO, 'Set QUARTO for real parser preview checks')
class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'deck.md'
        self.source.write_text('Original file must remain untouched')
        self.settings = core.config(self.source, {'quarto': QUARTO, 'theme': 'default', 'themes_dir': str(self.root / 'themes')})
        self.count = 0
        self.full = patch('matsugit.core.render').start()
        self.addCleanup(patch.stopall)

    def render(self, text, base=None, format='slides'):
        self.count += 1
        out = self.root / str(self.count)
        result = preview.render(self.settings, out, text, format, base)
        return out, result

    def test_text_table_links_unicode_and_independent_branches(self):
        source = ('---\ntitle: Demo\nslide-layout: structured\n---\n\n## Stable\n\n'
                  '| Value | Evidence |\n|---|---|\n| 12 | [One][ref] |\n\n'
                  'Readable & safe.\n\n[ref]: https://example.invalid/one\n')
        first, full = self.render(source)
        self.assertEqual(full['kind'], 'full')
        second, result = self.render(source.replace('12', '14').replace('Readable', '**שלום**').replace('/one', '/two'), first)
        self.assertEqual(result['kind'], 'patch')
        self.assertEqual(result['changed'], 3)
        html = (second / 'patch.json').read_text()
        self.assertIn('<strong>שלום</strong>', html)
        self.assertIn('&amp;', html)
        self.assertIn('example.invalid/two', html)
        _, unchanged = self.render(source, first)
        self.assertEqual(unchanged['changed'], 0)
        self.assertEqual(self.full.call_count, 1)
        self.assertEqual(self.source.read_text(), 'Original file must remain untouched')

    def test_org_and_markdown_have_the_same_patch_contract(self):
        for suffix, source in (('.md', '## Topic\n\n- Before\n'), ('.org', '* Topic\n\n- Before\n')):
            self.settings['source'] = self.root / ('deck' + suffix)
            first, _ = self.render(source, format='document')
            second, result = self.render(source.replace('Before', 'After'), first, 'document')
            self.assertEqual(result['kind'], 'patch')
            self.assertEqual(json.loads((second / 'patch.json').read_text())['changes'][0]['html'], 'After')

    def test_global_metadata_structure_math_code_and_diagram_edits_rebuild(self):
        source = ('---\ntitle: Demo\nslide-layout: structured\n---\n\n## Topic\n\nText\n\n'
                  '$x$\n\n```python\nx=1\n```\n\n```mermaid\nflowchart LR\n A-->B\n```\n')
        first, _ = self.render(source)
        for changed in (source.replace('Demo', 'Other'), source.replace('Topic', 'Renamed'),
                        source + '\nNew paragraph\n', source.replace('$x$', '$y$'),
                        source.replace('x=1', 'x=2'), source.replace('A-->B', 'A-->C')):
            self.assertEqual(self.render(changed, first)[1]['kind'], 'full')
        self.assertEqual(self.render(source.replace('Text', 'New text'), first)[1]['kind'], 'patch')

    def test_changed_image_and_theme_invalidate_base(self):
        image = self.root / 'image.svg'
        image.write_text('<svg/>')
        source = '## Topic\n\nText\n\n![](image.svg)\n'
        first, _ = self.render(source)
        image.write_text('<svg>changed</svg>')
        self.assertEqual(self.render(source, first)[1]['kind'], 'full')
        theme = self.root / 'themes/default'
        shutil.copytree(Path(core.__file__).parent / 'themes/default', theme)
        third, _ = self.render(source)
        css = theme / core.read_json(theme / 'theme.json')['document']
        css.write_text(css.read_text() + '\n/* theme change */')
        self.assertEqual(self.render(source, third)[1]['kind'], 'full')

    def test_format_switch_and_expired_snapshot_rebuild(self):
        first, _ = self.render('## Topic\n\nText\n')
        self.assertEqual(self.render('## Topic\n\nText\n', first, 'document')[1]['kind'], 'full')
        self.assertEqual(self.render('## Topic\n\nText\n', self.root / 'expired')[1]['kind'], 'full')

    def test_many_rows_change_only_one_cell(self):
        source = '## Table\n\n| Label | Value |\n|---|---|\n' + ''.join(f'| Row {i} | Value {i} |\n' for i in range(300))
        first, _ = self.render(source)
        second, result = self.render(source.replace('Value 299', '**Updated**'), first)
        self.assertEqual(result['changed'], 1)
        self.assertLess((second / 'patch.json').stat().st_size, 200)
