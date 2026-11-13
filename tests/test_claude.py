"""Claude Code plugin files and the Claude Desktop setup."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from matsugit import claude_desktop
from matsugit.core import Error

ROOT = Path(__file__).resolve().parents[1]


class ClaudeCodePluginTests(unittest.TestCase):
    def test_manifest_points_at_files_that_exist(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'matsugit')
        self.assertTrue((ROOT / manifest['commands']).is_dir())
        for name in ('tour', 'new', 'slides', 'check', 'help'):
            self.assertTrue((ROOT / manifest['commands'] / f'matsugit-{name}.md').is_file(), name)
        self.assertTrue((ROOT / 'skills/matsugit/SKILL.md').is_file())
        server = manifest['mcpServers']['matsugit']
        self.assertEqual(server['args'], ['${CLAUDE_PLUGIN_ROOT}/codex-plugin/bundle/server.mjs'])
        self.assertTrue((ROOT / 'codex-plugin/bundle/server.mjs').is_file())
        self.assertTrue((ROOT / 'codex-plugin/bundle/browser.mjs').is_file())

    def test_marketplace_lists_this_repository_as_the_plugin(self):
        market = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(market['name'], 'matsugit')
        self.assertEqual([(p['name'], p['source']) for p in market['plugins']], [('matsugit', './')])


@unittest.skipUnless(shutil.which('node'), 'needs Node')
class ClaudeDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.base = claude_desktop.config_dir(self.home, 'darwin')
        self.config = self.base / 'claude_desktop_config.json'

    def tearDown(self):
        self.temporary.cleanup()

    def install(self, **options):
        return claude_desktop.install(ROOT, home=self.home, platform='darwin', **options)

    def test_adds_one_server_and_keeps_everything_else(self):
        self.base.mkdir(parents=True)
        original = {'mcpServers': {'other': {'command': 'other-server'}}, 'preferences': {'theme': 'dark'}}
        self.config.write_text(json.dumps(original))
        message = self.install(check=True)
        self.assertIn('Would add', message)
        self.assertEqual(json.loads(self.config.read_text()), original, 'check mode writes nothing')
        message = self.install()
        data = json.loads(self.config.read_text())
        self.assertEqual(data['preferences'], {'theme': 'dark'})
        self.assertEqual(data['mcpServers']['other'], {'command': 'other-server'})
        entry = data['mcpServers']['matsugit']
        self.assertEqual(entry['args'], [str(ROOT / 'codex-plugin/bundle/server.mjs')])
        self.assertIn('PATH', entry['env'])
        self.assertIn('backed up', message)
        backups = list(self.base.glob('matsugit-backup-*/claude_desktop_config.json'))
        self.assertEqual([json.loads(b.read_text()) for b in backups], [original])
        self.assertIn('Nothing changed', self.install())

    def test_creates_the_file_when_claude_desktop_has_none(self):
        self.install()
        self.assertIn('matsugit', json.loads(self.config.read_text())['mcpServers'])

    def test_refuses_to_replace_a_matsugit_entry_it_did_not_write(self):
        self.base.mkdir(parents=True)
        mine = {'mcpServers': {'matsugit': {'command': 'node', 'args': ['/somewhere/else.mjs']}}}
        self.config.write_text(json.dumps(mine))
        with self.assertRaisesRegex(Error, 'different matsugit server'):
            self.install()
        self.assertEqual(json.loads(self.config.read_text()), mine)

    def test_refuses_a_file_that_is_not_an_object(self):
        self.base.mkdir(parents=True)
        self.config.write_text('[]')
        with self.assertRaisesRegex(Error, 'nothing changed'):
            self.install()

    def test_config_folders_per_platform(self):
        home = Path('/home/someone')
        self.assertEqual(claude_desktop.config_dir(home, 'darwin'), home / 'Library/Application Support/Claude')
        self.assertEqual(claude_desktop.config_dir(home, 'linux'), home / '.config/Claude')
        self.assertEqual(claude_desktop.config_dir(home, 'win32'), home / 'AppData/Roaming/Claude')


if __name__ == '__main__':
    unittest.main()
