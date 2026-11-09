import json
import shutil
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

    def test_skill_only_copy_is_migrated_without_reinstall_conflict(self):
        skill = self.base / 'skills/matsugit'
        shutil.copytree(ROOT / 'skills/matsugit', skill)
        (skill / '.DS_Store').write_bytes(b'Finder metadata')
        result = cursor.install(ROOT, home=self.home)
        self.assertTrue(skill.is_symlink())
        self.assertIn('Previous skill retained at', result)
        backups = list((self.base / 'matsugit-skill-backups').glob('*/matsugit/.DS_Store'))
        self.assertEqual(len(backups), 1)
        receipt = json.loads((self.base / 'matsugit-install.json').read_text())
        self.assertIn('SKILL.md', receipt['skill']['files'])
        times = {p: p.stat().st_mtime_ns for p in (self.config,
                 self.base / 'matsugit-install.json', self.base / 'commands/matsugit-slides.md')}
        cursor.install(ROOT, home=self.home)
        self.assertEqual(times, {p: p.stat().st_mtime_ns for p in times})

    def test_receipted_skill_copy_can_update_without_git(self):
        root = self.home / 'archive'
        for name in ('skills', 'cursor-commands', 'codex-plugin/bundle'):
            shutil.copytree(ROOT / name, root / name)
        cursor.install(root, home=self.home)
        skill = self.base / 'skills/matsugit'
        skill.unlink()
        shutil.copytree(root / 'skills/matsugit', skill)
        (root / 'skills/matsugit/SKILL.md').write_text('new instructions')
        cursor.install(root, home=self.home)
        self.assertEqual((skill / 'SKILL.md').read_text(), 'new instructions')

    def test_custom_skill_reference_blocks_setup_before_config_changes(self):
        skill = self.base / 'skills/matsugit'
        shutil.copytree(ROOT / 'skills/matsugit', skill)
        (skill / 'references/setup.md').write_text('custom setup')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(Error, 'references/setup.md'):
            cursor.install(ROOT, home=self.home)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.base / 'matsugit-install.json').exists())


if __name__ == '__main__': unittest.main()
