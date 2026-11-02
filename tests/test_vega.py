import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit import charts, vega
from test_layout import container, heading

READY = all(importlib.util.find_spec(m) for m in ('altair', 'vl_convert'))
SPEC = {'description': 'Illustrative results', 'data': {'values': [
    {'category': 'Alpha & <Beta>', 'value': 12}, {'category': 'Caf\u00e9', 'value': 18}]},
    'mark': 'bar', 'encoding': {'x': {'field': 'category', 'type': 'nominal'},
                               'y': {'field': 'value', 'type': 'quantitative'}}}


def block(spec=None):
    return {'t': 'CodeBlock', 'c': [['', ['vega-lite'], []], json.dumps(SPEC if spec is None else spec)]}


class VegaTests(unittest.TestCase):
    def test_lint_measures_exhibit_caption_not_json_but_requires_source(self):
        from matsugit.lint import inspect
        from test_layout import document
        spec = dict(SPEC, data={'values': [{'category': f'Item {i}', 'value': i} for i in range(200)]})
        findings = inspect(document([heading(2, 'Evidence'), block(spec)]))
        self.assertEqual([f['code'] for f in findings], ['chart-source'])

    def test_literal_data_field_names_are_not_options(self):
        spec = dict(SPEC, data={'values': [{'width': 3, 'height': 2, 'url': 'a literal label', 'mark': 'image'}]})
        self.assertEqual(vega.validate(spec), spec)

    def test_legacy_auto_fallback_warns_but_does_not_break(self):
        import contextlib
        import io
        stderr = io.StringIO()
        with patch.object(charts.importlib.util, 'find_spec', return_value=None), patch.object(charts, 'worker', return_value='<svg/>'), contextlib.redirect_stderr(stderr):
            result = charts.render_worker({'data': {'kind': 'bar'}, 'style': {}})
        self.assertEqual(result['backend'], 'matplotlib')
        self.assertIn('setup-charts', stderr.getvalue())

    def test_non_chart_layout_is_untouched(self):
        node = container('columns', [container('column', [heading(4, 'Single native column')])])
        self.assertEqual(charts.prepare(node, Path('/unused')), node)

    def test_inline_spec_is_data_and_source_is_unchanged(self):
        original = copy.deepcopy(SPEC)
        data = charts.dataset(block())
        self.assertEqual(data['spec'], SPEC)
        self.assertEqual(SPEC, original)
        self.assertEqual(data['backend'], 'altair')

    def test_rejects_external_and_active_or_unbounded_specs(self):
        for spec in ({'data': {'url': 'file:///etc/passwd'}},
                     {'data': {'url': 'https://example.com/data'}},
                     {'mark': 'image'}, {'mark': {'type': 'image'}},
                     {'encoding': {'href': {'value': 'https://example.com'}}},
                     {'params': [{'name': 'live'}]}, {'width': 10000}, {'height': 'container'},
                     {'facet': {}}, {'value': float('nan')}, {'values': [1] * 5001},
                     {'description': 'x' * 1_000_001}):
            with self.subTest(spec=str(spec)[:100]), self.assertRaises(ValueError):
                vega.validate(spec)
        deep = {}
        for _ in range(42):
            deep = {'child': deep}
        with self.assertRaises(ValueError):
            vega.validate(deep)

    def test_columns_prepare_at_actual_slot_width(self):
        columns = container('columns', [heading(4, 'A'), block(), heading(4, 'B'), block()])
        widths = []
        def render(data, colours, width):
            widths.append(width)
            return {'svg': '<svg/>', 'spec': SPEC}
        with tempfile.TemporaryDirectory() as d, patch.object(charts, 'render_chart', side_effect=render):
            charts.prepare(columns, Path(d))
            self.assertEqual(widths, [466, 466])
            self.assertEqual(len(list((Path(d)/'assets').glob('*.vl.json'))), 1)

    def test_worker_timeout_becomes_useful_error(self):
        import subprocess
        with patch.object(charts.subprocess, 'run', side_effect=subprocess.TimeoutExpired('chart', 60)):
            with self.assertRaisesRegex(ValueError, '60 seconds'):
                charts.render_chart(charts.dataset(block()), {})

    @unittest.skipUnless(READY, 'Altair chart extra not installed')
    def test_native_svg_unicode_escaping_palette_and_slot_sizes(self):
        original = copy.deepcopy(SPEC)
        full = vega.render({'spec': SPEC}, charts.style({'accent': '#0033a0'}), 960)
        half = vega.render({'spec': SPEC}, charts.style({}), 466)
        self.assertEqual(SPEC, original)
        self.assertEqual(full['spec']['width'], 960)
        self.assertEqual(half['spec']['width'], 466)
        self.assertEqual(full['spec']['config']['axis']['labelFontSize'], half['spec']['config']['axis']['labelFontSize'])
        self.assertIn('Caf\u00e9', full['svg'])
        self.assertIn('&lt;Beta&gt;', full['svg'])
        self.assertIn('#0033a0', full['svg'])
        self.assertEqual(full, vega.render({'spec': SPEC}, charts.style({'accent': '#0033a0'}), 960))

    @unittest.skipUnless(READY, 'Altair chart extra not installed')
    def test_all_table_types_and_explicit_legacy_backend(self):
        data = {'unit': 'people', 'labels': ['1', '2'], 'headers': ['Group', 'Count'],
                'values': [[12], [18]], 'highlight': None}
        for kind in charts.KINDS:
            with self.subTest(kind=kind):
                result = charts.render_worker({'data': dict(data, kind=kind), 'style': {}})
                self.assertEqual(result['backend'], 'altair')
                self.assertIn('<svg', result['svg'])
        result = charts.render_worker({'data': dict(data, kind='bar', backend='matplotlib'), 'style': {}})
        self.assertEqual(result['backend'], 'matplotlib')

    @unittest.skipUnless(READY, 'Altair chart extra not installed')
    def test_invalid_schema_rejected_not_rendered_as_blank(self):
        with self.assertRaises(Exception):
            vega.render({'spec': {'mark': 'not-a-real-mark'}}, charts.style({}), 960)

    @unittest.skipUnless(READY, 'Altair chart extra not installed')
    def test_layers_and_calculations_use_vega_not_a_new_drawing_engine(self):
        spec = dict(SPEC, transform=[{'calculate': 'datum.value * 2', 'as': 'double'}])
        self.assertIn('<svg', vega.render({'spec': spec}, charts.style({}), 960)['svg'])


if __name__ == '__main__':
    unittest.main()
