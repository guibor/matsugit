import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import config, theme_options


class ThemeOptionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.themes = self.root / 'themes'
        self.themes.mkdir()
        self.settings = {'themes_dir': self.themes, 'theme': 'alpha'}

    def theme(self, name, data):
        directory = self.themes / name
        directory.mkdir()
        (directory / 'theme.json').write_text(json.dumps(data))

    def test_lists_installed_and_inherited_themes_without_rendering(self):
        self.theme('alpha', {'document': 'doc.css', 'slides': 'slides.scss'})
        self.theme('beta', {'extends': 'alpha'})
        self.theme('invalid', [])
        self.theme('empty', {})
        self.theme('.hidden', {'extends': 'alpha'})
        self.theme('bad name', {'extends': 'alpha'})
        self.theme('broken', {'extends': 'alpha'})
        (self.themes / 'broken/theme.json').write_text('{broken')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'theme.json').write_text('{"extends":"default"}')
        (self.themes / 'escape').symlink_to(outside, target_is_directory=True)
        self.theme('manifest-link', {'extends': 'alpha'})
        (self.themes / 'manifest-link/theme.json').unlink()
        (self.themes / 'manifest-link/theme.json').symlink_to(outside / 'theme.json')
        self.assertEqual(theme_options(self.settings),
                         {'default': 'alpha', 'themes': ['alpha', 'beta', 'default']})

    def test_missing_directory_still_offers_builtin_without_changing_default(self):
        self.assertEqual(theme_options(dict(self.settings, themes_dir=self.root / 'missing')),
                         {'default': 'alpha', 'themes': ['default']})

    def test_worker_matches_project_configuration_and_does_not_read_source(self):
        self.theme('alpha', {'extends': 'default'})
        (self.root / 'matsugit.json').write_text(json.dumps({'theme': 'alpha', 'themes_dir': 'themes'}))
        spec = importlib.util.spec_from_file_location('theme_worker',
            Path(__file__).resolve().parents[1] / 'codex-plugin/actions.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        source = self.root / 'not-yet-saved.md'
        with patch.dict(os.environ, {'MATSUGIT_CONFIG': str(self.root / 'absent.json')}):
            result = worker.main({'action': 'themes', 'path': str(source)})
            self.assertEqual(result['default'], config(source)['theme'])
        self.assertEqual(result['themes'], ['alpha', 'default'])
        self.assertFalse(source.exists())


if __name__ == '__main__':
    unittest.main()
