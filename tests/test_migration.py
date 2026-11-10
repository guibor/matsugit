"""Renaming never discards settings, managed outputs, or legacy integrations."""
import realtmp  # noqa: F401  (resolve the temporary directory before any test creates one)
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from matsugit.compat import env
from matsugit.core import Error, config
from matsugit.converter import tools_dir
from matsugit.publish import check_destination, setup_ci, site_index


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'PATH': os.environ['PATH']}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.source = self.home / 'deck.md'
        self.source.write_text('# Synthetic\n')

    def write(self, path, value):
        dest = self.home / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(value))

    def test_legacy_global_project_and_environment_are_read(self):
        self.write('.config/folioforge/config.json', {'theme': 'legacy', 'custom': 1})
        self.write('folioforge.json', {'theme': 'project'})
        (self.home / 'folioforge-site').mkdir()
        (self.home / '.config/folioforge/themes').mkdir()
        settings = config(self.source)
        self.assertEqual(settings['theme'], 'project')
        self.assertEqual(settings['custom'], 1)
        self.assertEqual(settings['site_dir'], 'folioforge-site')
        self.assertEqual(settings['themes_dir'], self.home / '.config/folioforge/themes')

    def test_new_settings_win_without_dropping_legacy_keys(self):
        self.write('.config/folioforge/config.json', {'theme': 'old', 'custom': 1})
        self.write('.config/matsugit/config.json', {'theme': 'global'})
        self.write('folioforge.json', {'theme': 'old-project', 'branch': 'work'})
        self.write('matsugit.json', {'theme': 'new-project'})
        self.assertEqual(config(self.source)['theme'], 'new-project')
        self.assertEqual(config(self.source)['branch'], 'work')
        self.assertEqual(config(self.source)['custom'], 1)
        self.assertEqual(config(self.source, {'theme': 'explicit'})['theme'], 'explicit')

    def test_environment_precedence_and_explicit_config(self):
        self.write('old-config.json', {'theme': 'old'})
        self.write('new-config.json', {'theme': 'new'})
        os.environ['FOLIOFORGE_CONFIG'] = str(self.home / 'old-config.json')
        self.assertEqual(config(self.source)['theme'], 'old')
        os.environ['MATSUGIT_CONFIG'] = str(self.home / 'new-config.json')
        self.assertEqual(config(self.source)['theme'], 'new')
        os.environ['FOLIOFORGE_DEFAULT_THEME'] = 'old'
        os.environ['MATSUGIT_DEFAULT_THEME'] = 'new'
        self.assertEqual(env('MATSUGIT_DEFAULT_THEME'), 'new')

    def test_legacy_tools_are_reused(self):
        old = self.home / '.local/share/folioforge/tools'
        old.mkdir(parents=True)
        self.assertEqual(tools_dir(), old)
        os.environ['MATSUGIT_TOOLS_DIR'] = str(self.home / 'custom')
        self.assertEqual(tools_dir(), self.home / 'custom')

    def test_legacy_python_imports_are_the_same_modules(self):
        for module in ('core', 'cli', 'authoring', 'charts', 'converter', 'publish', 'updates'):
            self.assertIs(importlib.import_module('folioforge.' + module),
                          importlib.import_module('matsugit.' + module))

    def test_both_cli_entrypoints_work(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('matsugit', 'folioforge'):
            result = subprocess.run([sys.executable, str(root / 'bin' / name), '--help'],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('render', result.stdout)

    def test_legacy_managed_destination_accepted_but_extra_files_rejected(self):
        dest = self.home / 'site/deck'
        dest.mkdir(parents=True)
        (dest / 'source.md').write_bytes(self.source.read_bytes())
        manifest = {'version': 1, 'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
                    'files': ['source.md']}
        (dest / 'folioforge-manifest.json').write_text(json.dumps(manifest))
        check_destination(dest, self.source)
        site_index(dest.parent)
        self.assertIn('deck/index.html', (dest.parent / 'index.html').read_text())
        (dest / 'unmanaged.txt').write_text('Keep me')
        with self.assertRaisesRegex(Error, 'Unmanaged'):
            check_destination(dest, self.source)

    def test_legacy_ci_is_not_silently_duplicated_or_replaced(self):
        self.write('.github/workflows/folioforge-pages.yml', {'synthetic': True})
        with self.assertRaisesRegex(Error, 'legacy CI retained'):
            setup_ci(config(self.source), 'github')
        self.assertFalse((self.home / '.github/workflows/matsugit-pages.yml').exists())
