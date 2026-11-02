import copy
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from matsugit.authoring import template, TEMPLATES
from matsugit.components import prepare
from matsugit.charts import dataset, worker, number
from matsugit.core import install_theme, Error, run
from matsugit.handout import prepare as handout
from matsugit.lint import inspect
from test_layout import heading, para, container, document

QUARTO = os.environ.get('QUARTO',shutil.which('quarto'))

class EvidenceTests(unittest.TestCase):
    def test_components_are_opt_in_and_do_not_mutate_source(self):
        source = container('comparison',[heading(4,'A'),para('First'),heading(4,'B'),para('Second')])
        before = copy.deepcopy(source)
        result = prepare(source)
        self.assertEqual(source,before)
        self.assertIn('ff-comparison',result['c'][0][1])
        self.assertEqual(len(result['c'][1]),2)
        self.assertEqual(prepare(para('Plain')),para('Plain'))

    def test_invalid_regions_rejected(self):
        for blocks in ([para('No heading')],[heading(4,'A'),para('Only one')],
                       [heading(4,'A'),heading(4,'B'),para('Missing body')]):
            with self.assertRaises(ValueError):
                prepare(container('comparison',blocks))

    def test_handout_keeps_notes_without_changing_slide_ast(self):
        ast = document([heading(2,'A'),container('notes',[para('Private speaker guidance')]),heading(2,'B'),para('Text')])
        before=copy.deepcopy(ast)
        result=handout(ast)
        self.assertEqual(ast,before)
        self.assertEqual(len(result['blocks']),2)
        self.assertIn('ff-speaker-notes',json.dumps(result))

    def test_templates_never_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'draft.md'
            template('chart',path)
            with self.assertRaises(FileExistsError):template('metrics',path)
            self.assertIn('unit=',path.read_text())
        for name in TEMPLATES:
            self.assertIn('## ',template(name,fragment=True))

    def test_theme_inheritance_is_flattened_and_cycles_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'base').mkdir(); (root/'child').mkdir()
            (root/'base/theme.json').write_text(json.dumps({'document':'doc.css','slides':'base.scss'}))
            (root/'base/doc.css').write_text('body{}'); (root/'base/base.scss').write_text('base')
            (root/'child/theme.json').write_text(json.dumps({'extends':'base','slides':'child.scss'}))
            (root/'child/child.scss').write_text('@import "base.scss";')
            out=root/'out'; out.mkdir()
            manifest=install_theme({'theme':'child','themes_dir':root},out)
            self.assertEqual(manifest['slides'],'child.scss')
            self.assertIn('base.scss',manifest['assets'])
            self.assertNotIn('extends',manifest)
            (root/'base/theme.json').write_text('{"extends":"child"}')
            with self.assertRaises(Error):install_theme({'theme':'child','themes_dir':root},out)

    def test_lint_excludes_notes_from_density(self):
        ast=document([heading(2,'Short'),container('notes',[para('word '*300)]),para('Concise')])
        self.assertFalse(inspect(ast))
        self.assertTrue(inspect(document([heading(2,'Long'),para('word '*300)])))

    def test_numeric_validation(self):
        self.assertEqual(number('1,200'),1200)
        for bad in ('NaN','inf','1e100','10%','__import__("os")'):
            with self.assertRaises(ValueError):number(bad)

    @unittest.skipUnless(QUARTO,'Quarto not installed')
    def test_chart_ast_and_deterministic_svg(self):
        ast=json.loads(run([QUARTO,'pandoc','-f','markdown','-t','json'],text=template('chart',fragment=True)))
        chart=next(b for b in ast['blocks'] if b['t']=='Div' and 'chart' in b['c'][0][1])
        data=dataset(chart)
        self.assertEqual(data['values'],[[64.0],[78.0]])
        try: import matplotlib
        except ImportError: self.skipTest('Optional charts extra not installed')
        payload={'data':data,'style':{}}
        a,b=worker(payload),worker(payload)
        self.assertEqual(a,b)
        self.assertIn('78',a)
        chart['c'][0][2].append(['execute','true'])
        with self.assertRaises(ValueError):dataset(chart)

if __name__ == '__main__':unittest.main()
