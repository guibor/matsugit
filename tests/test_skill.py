"""Exercise portable skill examples through the real parser and theme installer."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from folioforge.charts import dataset, style
from folioforge.components import prepare
from folioforge.core import install_theme, run
from folioforge.layout import plain, slides
from folioforge.lint import inspect, walk

SKILL = Path(__file__).resolve().parents[1] / 'skills/folioforge'
QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))


class SkillThemeTests(unittest.TestCase):
    def test_installed_skill_routes_to_bundled_resources_without_repo_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / 'folioforge'
            shutil.copytree(SKILL, copied)
            links = re.findall(r'\]\(([^)#]+)(?:#[^)]*)?\)',
                               (copied / 'SKILL.md').read_text())
            self.assertIn('references/setup.md', links)
            for link in links:
                if '://' not in link:
                    target = (copied / link).resolve()
                    self.assertTrue(target.is_relative_to(copied))
                    self.assertTrue(target.is_file(), link)
            manifest = install_theme({'theme': 'starter', 'themes_dir': copied / 'assets/themes'},
                                     Path(directory) / 'preview')
            self.assertEqual(manifest['charts'], 'charts.json')

    def test_starter_manifest_copies_every_dependency(self):
        root = SKILL / 'assets/themes'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = install_theme({'theme': 'starter', 'themes_dir': root}, output)
            for key in ('document', 'slides', 'charts'):
                self.assertEqual((output / 'theme' / manifest[key]).read_bytes(),
                                 (root / 'starter' / manifest[key]).read_bytes())
            self.assertEqual(len(style(json.loads((output / 'theme/charts.json').read_text()))['series']), 4)


@unittest.skipUnless(QUARTO, 'Quarto required to validate Markdown skill examples')
class SkillRecipeTests(unittest.TestCase):
    def ast(self):
        return json.loads(run([QUARTO, 'pandoc', '-f', 'markdown', '-t', 'json'],
                              text=(SKILL / 'assets/slide-types.md').read_text()))

    def test_corpus_has_twelve_slides_and_valid_evidence(self):
        ast = self.ast()
        self.assertEqual(inspect(ast), [])
        prepared = slides(prepare(ast))
        headings = [n for n in prepared['blocks'] if n['t'] == 'Header']
        self.assertEqual(len(headings), 12)
        self.assertTrue(all(n['c'][0] == 2 for n in headings))
        self.assertEqual(plain(headings[0]['c'][2]), 'Pilot decision brief')
        self.assertIn('statement', headings[1]['c'][1][1])
        classes = {c for n in walk(prepared) if n.get('t') == 'Div' for c in n['c'][0][1]}
        self.assertTrue({'ff-rows', 'ff-metrics', 'ff-comparison', 'ff-timeline',
                         'ff-decision', 'ff-assertion', 'ff-takeaway'} <= classes)
        charts = [n for n in walk(ast) if n.get('t') == 'Div' and 'chart' in n['c'][0][1]]
        self.assertEqual(len(charts), 2)
        self.assertEqual([dataset(n)['values'] for n in charts], [[[12.0], [8.0]]] * 2)
        # Renderer and lint must not consume or rewrite the original evidence.
        self.assertEqual(ast, self.ast())


if __name__ == '__main__':
    unittest.main()
