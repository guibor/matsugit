"""Portability checks; native lock/UTF-8 checks also run on Windows runners."""
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from matsugit import adopt, charts, converter, core, diagrams, skill_install, updates


class WindowsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='matsugit portability ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def test_import_updates_without_unix_modules(self):
        code = '''import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'fcntl': raise ImportError('not available on Windows')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import matsugit.updates
'''
        subprocess.run([sys.executable, '-c', code], check=True)

    def test_windows_lock_unlocks_on_failure_without_truncating(self):
        lock = self.root / 'lock'
        lock.write_bytes(b'existing lock file')
        crt = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=Mock())
        with patch.object(updates, 'os', SimpleNamespace(name='nt')), \
             patch.object(updates, 'git', return_value=str(lock)), patch.dict(sys.modules, msvcrt=crt):
            with self.assertRaisesRegex(ValueError, 'synthetic'):
                with updates.update_lock(self.root):
                    raise ValueError('synthetic')
        self.assertEqual([call.args[1:] for call in crt.locking.call_args_list], [(2, 1), (0, 1)])
        self.assertEqual(lock.read_bytes(), b'existing lock file')

    def test_windows_busy_lock_fails_without_unlocking_another_owner(self):
        crt = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0,
                              locking=Mock(side_effect=OSError(errno.EACCES, 'locked')))
        with patch.object(updates, 'os', SimpleNamespace(name='nt')), \
             patch.object(updates, 'git', return_value=str(self.root / 'lock')), patch.dict(sys.modules, msvcrt=crt):
            with self.assertRaisesRegex(core.Error, 'Another matsugit update'):
                with updates.update_lock(self.root):
                    self.fail('must not acquire')
        self.assertEqual(crt.locking.call_count, 1)

    def test_native_lock_blocks_another_process_and_releases(self):
        core.git(self.root, 'init', '-q')
        script = '''import sys
from pathlib import Path
from matsugit.updates import update_lock
from matsugit.core import Error
try:
    with update_lock(Path(sys.argv[1])): pass
except Error:
    sys.exit(23)
'''
        with updates.update_lock(self.root):
            result = subprocess.run([sys.executable, '-c', script, str(self.root)])
        self.assertEqual(result.returncode, 23)
        subprocess.run([sys.executable, '-c', script, str(self.root)], check=True)

    def test_windows_skills_are_verified_copies_and_edits_are_protected(self):
        source, target = self.root / 'source', self.root / 'installed'
        source.mkdir()
        (source / 'SKILL.md').write_bytes(b'first')
        with patch.object(skill_install, 'WINDOWS', True), \
             patch.object(Path, 'symlink_to', side_effect=AssertionError('no privilege needed')):
            first = skill_install.SkillPlan(source, target)
            first.apply(self.root / 'backups')
            self.assertFalse(target.is_symlink())
            again = skill_install.SkillPlan(source, target, first.receipt)
            self.assertEqual(again.action, 'keep')
            self.assertIsNone(again.apply(self.root / 'backups'))
            (source / 'SKILL.md').write_bytes(b'next')
            next_plan = skill_install.SkillPlan(source, target, first.receipt)
            backup = next_plan.apply(self.root / 'backups')
            self.assertEqual((backup / 'SKILL.md').read_bytes(), b'first')
            self.assertEqual((target / 'SKILL.md').read_bytes(), b'next')
            (target / 'SKILL.md').write_bytes(b'my edit')
            with self.assertRaisesRegex(ValueError, 'Existing skill retained'):
                skill_install.SkillPlan(source, target, next_plan.receipt)
            self.assertEqual((target / 'SKILL.md').read_bytes(), b'my edit')

    def test_windows_copy_failure_restores_existing_skill(self):
        source, target = self.root / 'source', self.root / 'installed'
        source.mkdir(); target.mkdir()
        (source / 'SKILL.md').write_bytes(b'new')
        (target / 'SKILL.md').write_bytes(b'old')
        receipt = {'files': skill_install.files(target)}
        with patch.object(skill_install, 'WINDOWS', True):
            plan = skill_install.SkillPlan(source, target, receipt)
            with patch.object(skill_install.shutil, 'copytree', side_effect=OSError('copy failed')):
                with self.assertRaises(OSError):
                    plan.apply(self.root / 'backups')
        self.assertEqual((target / 'SKILL.md').read_bytes(), b'old')

    def test_no_symlink_privilege_stops_first_share_before_copying(self):
        source = self.root / 'draft.md'
        source.write_bytes(b'my draft\r\n')
        repo = self.root / 'project'
        reviewed = {'source': str(source), 'repo': str(repo),
                    'destination': str(repo / 'deck.md'), 'moves': []}
        with patch.object(adopt, 'plan', return_value=reviewed), \
             patch.object(adopt, 'os', SimpleNamespace(name='nt')), \
             patch.object(Path, 'symlink_to', side_effect=PermissionError('not permitted')):
            with self.assertRaisesRegex(core.Error, 'No files were moved'):
                adopt.apply(reviewed)
        self.assertEqual(source.read_bytes(), b'my draft\r\n')
        self.assertFalse(repo.exists())
        self.assertEqual(list(self.root.iterdir()), [source])

    def test_windows_pandoc_zip_is_verified_before_install(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('pandoc-3.13/pandoc.exe', b'synthetic executable')
        payload = data.getvalue()
        pinned = ('pandoc-3.13-windows-x86_64.zip', hashlib.sha256(payload).hexdigest())
        for tampered in (False, True):
            target = self.root / ('tampered' if tampered else 'valid')
            with patch.object(converter.platform, 'system', return_value='Windows'), \
                 patch.object(converter.platform, 'machine', return_value='AMD64'), \
                 patch.object(converter, 'tools_dir', return_value=target), \
                 patch.object(converter, 'converter', side_effect=[core.Error('missing'), ['pandoc.exe']]), \
                 patch.dict(converter.PINNED_ASSETS, {('Windows', 'amd64'): pinned}), \
                 patch.object(converter.urllib.request, 'urlopen', return_value=
                     io.BytesIO(payload + (b'x' if tampered else b''))), \
                 patch.object(converter.subprocess, 'run', return_value=SimpleNamespace(stdout='pandoc 3.13\n')) as execute:
                if tampered:
                    with self.assertRaisesRegex(core.Error, 'checksum mismatch'):
                        converter.install_converter()
                    execute.assert_not_called()
                    self.assertFalse((target / 'pandoc.exe').exists())
                else:
                    converter.install_converter()
                    self.assertEqual((target / 'pandoc.exe').read_bytes(), b'synthetic executable')
                    self.assertTrue((target / 'pandoc-install.json').is_file())

    def test_utf8_subprocess_input_and_output(self):
        text = '\u05e9\u05dc\u05d5\u05dd \u00e9\n'
        script = 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'
        self.assertEqual(core.run([sys.executable, '-c', script], text=text), text)

    def test_windows_diagrams_uses_node_not_a_batch_shell(self):
        node = self.root / 'Program Files/nodejs/node.exe'
        cli = node.parent / 'node_modules/npm/bin/npm-cli.js'
        cli.parent.mkdir(parents=True)
        cli.write_text('// synthetic npm entry point', encoding='utf-8')
        target = self.root / 'diagrams'
        with patch.object(diagrams, 'os', SimpleNamespace(name='nt')), \
             patch.object(diagrams, 'runtime_path', return_value=target), \
             patch.object(diagrams.shutil, 'which', side_effect=lambda name: str(node if name == 'node' else node.with_name('npm.cmd'))), \
             patch.object(diagrams.subprocess, 'run', return_value=SimpleNamespace(stdout='v22.0.0')) as run:
            diagrams.setup()
            self.assertEqual(run.call_args.args[0][:3], [str(node), str(cli), 'ci'])
            self.assertNotIn('shell', run.call_args.kwargs)
            cli.unlink()
            with self.assertRaisesRegex(ValueError, 'npm-cli.js'):
                diagrams.setup()
            self.assertEqual(run.call_count, 3)  # No second install attempted.

    def test_windows_chart_setup_uses_native_venv_python(self):
        target = self.root / 'charts'
        with patch.object(charts, 'os', SimpleNamespace(name='nt')), \
             patch.object(Path, 'expanduser', return_value=target), \
             patch.object(charts.shutil, 'which', return_value=None), \
             patch.object(charts.subprocess, 'run') as run:
            charts.setup()
        self.assertEqual(run.call_args.args[0][:3], [str(target / 'Scripts/python.exe'), '-m', 'pip'])


if __name__ == '__main__':
    unittest.main()
