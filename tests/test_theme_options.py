import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import Error, config, install_theme, resolve_theme, theme_options


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
        result = theme_options(self.settings)
        self.assertEqual(result['themes'], ['alpha', 'beta', 'default'])
        self.assertEqual(result['default'], 'alpha')
        self.assertEqual(result['details']['alpha']['path'], str(self.themes / 'alpha'))

    def test_missing_directory_still_offers_builtin_without_changing_default(self):
        result = theme_options(dict(self.settings, themes_dir=self.root / 'missing'))
        self.assertEqual(result['themes'], ['default'])
        self.assertEqual(result['default'], 'alpha')

    def test_project_augments_shared_and_all_resolution_uses_precedence(self):
        self.theme('alpha', {'extends': 'default'})
        shared = self.root / 'shared'
        (shared / 'alpha').mkdir(parents=True)
        (shared / 'alpha/theme.json').write_text('{"extends":"default","title":"shared"}')
        (shared / 'beta').mkdir()
        (shared / 'beta/theme.json').write_text('{"extends":"default"}')
        global_config = self.root / 'global.json'
        global_config.write_text(json.dumps({'theme': 'beta', 'themes_dir': str(shared)}))
        project_config = self.root / 'matsugit.json'
        project_config.write_text('{"themes_dir":"themes"}')
        source = self.root / 'deck.md'
        source.write_text('## Unchanged\n')
        with patch.dict(os.environ, {'MATSUGIT_CONFIG': str(global_config),
                                    'MATSUGIT_THEMES_DIR': str(self.root / 'empty')}):
            settings = config(source)
            result = theme_options(settings)
            self.assertEqual(result['themes'], ['alpha', 'beta', 'default'])
            self.assertEqual(result['details']['alpha']['origin'], 'project')
            self.assertEqual(result['details']['beta']['origin'], 'shared')
            self.assertEqual(result['default'], 'beta')
            for name in result['themes']:
                selected = dict(settings, theme=name)
                install_theme(selected, self.root / ('out-' + name))
                self.assertEqual(selected['_resolved_theme'], result['details'][name])
            # A fresh request observes config removal, without restarting the host.
            project_config.unlink()
            refreshed = config(source, {'theme': 'alpha'})
            self.assertEqual(resolve_theme(refreshed, 'alpha')[0]['origin'], 'shared')
            self.assertEqual(install_theme(refreshed, self.root / 'refreshed')['title'], 'shared')
        self.assertEqual(source.read_text(), '## Unchanged\n')

    def test_missing_and_invalid_themes_do_not_fall_back(self):
        with self.assertRaisesRegex(Error, 'was not found.*Install it'):
            install_theme(dict(self.settings, theme='absent'), self.root / 'out')
        self.theme('default', {'invalid': True})
        with self.assertRaisesRegex(Error, 'is invalid.*no other theme was substituted'):
            install_theme(dict(self.settings, theme='default'), self.root / 'out')

    def test_shared_parent_assets_are_copied_offline(self):
        shared = self.root / 'shared'
        parent = shared / 'parent'
        parent.mkdir(parents=True)
        (parent / 'theme.json').write_text('{"extends":"default","assets":["font.woff2"]}')
        (parent / 'font.woff2').write_bytes(b'synthetic-font')
        self.theme('child', {'extends': 'parent'})
        settings = dict(self.settings, theme='child',
                        _theme_roots=[('project', self.themes), ('shared', shared)])
        output = self.root / 'out'
        install_theme(settings, output)
        self.assertEqual((output / 'theme/font.woff2').read_bytes(), b'synthetic-font')
        (parent / 'font.woff2').unlink()
        with self.assertRaisesRegex(Error, 'Missing theme file'):
            install_theme(settings, self.root / 'broken')

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
