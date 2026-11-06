import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from matsugit import cursor
from matsugit.core import Error

ROOT = Path(__file__).resolve().parents[1]


class CursorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.base = self.home / '.cursor'; self.base.mkdir()
        self.config = self.base / 'mcp.json'
        self.config.write_text(json.dumps({'mcpServers':{'other':{'url':'https://example.invalid/mcp'}}, 'keep':True}))
        mocked = patch('matsugit.core.run', return_value='22'); mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.object(cursor.shutil, 'which', side_effect=lambda name: '/usr/bin/node' if name == 'node' else None)
        mocked.start(); self.addCleanup(mocked.stop)

    def test_install_idempotent_preserves_others_and_shares_skill(self):
        cursor.install(ROOT, home=self.home)
        before = self.config.read_bytes()
        cursor.install(ROOT, home=self.home)
        self.assertEqual(self.config.read_bytes(), before)
        data = json.loads(before)
        self.assertTrue(data['keep'])
        self.assertIn('other', data['mcpServers'])
        self.assertEqual((self.base / 'skills/matsugit').resolve(), ROOT / 'skills/matsugit')
        self.assertTrue((self.base / 'commands/matsugit-slides.md').is_file())
        self.assertTrue((self.base / 'commands/matsugit-story.md').is_file())

    def test_check_does_not_write(self):
        before = self.config.read_bytes()
        cursor.install(ROOT, home=self.home, check=True)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.base / 'skills').exists())

    def test_user_command_and_server_are_not_overwritten(self):
        cursor.install(ROOT, home=self.home)
        command = self.base / 'commands/matsugit-slides.md'; command.write_text('My custom command')
        with self.assertRaisesRegex(Error, 'Custom Cursor command'): cursor.install(ROOT, home=self.home)
        self.assertEqual(command.read_text(), 'My custom command')
        data = json.loads(self.config.read_text()); data['mcpServers']['matsugit'] = {'command':'custom'}
        self.config.write_text(json.dumps(data))
        with self.assertRaisesRegex(Error, 'different matsugit server'): cursor.install(ROOT, home=self.home)

    def test_symlink_and_unknown_skill_are_preserved(self):
        target = self.home / 'original'; self.config.rename(target); self.config.symlink_to(target)
        with self.assertRaisesRegex(Error, 'symlink'): cursor.install(ROOT, home=self.home)
        self.config.unlink(); self.config.write_text('{}')
        skill = self.base / 'skills/matsugit'; skill.mkdir(parents=True)
        with self.assertRaisesRegex(Error, 'Existing Cursor skill'): cursor.install(ROOT, home=self.home)

    def test_manifest_uses_cursor_variable_not_codex_variable(self):
        manifest = json.loads((ROOT / '.cursor-plugin/plugin.json').read_text())
        mcp = (ROOT / manifest['mcpServers']).read_text()
        self.assertIn('${CURSOR_PLUGIN_ROOT}', mcp)
        self.assertNotIn('${PLUGIN_ROOT}', mcp)


if __name__ == '__main__': unittest.main()
