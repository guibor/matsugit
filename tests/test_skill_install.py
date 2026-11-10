import realtmp  # noqa: F401  (resolve the temporary directory before any test creates one)
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from matsugit.skill_install import SkillPlan, files


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='skill install ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source/skills/example'
        self.source.mkdir(parents=True)
        (self.source / 'SKILL.md').write_text('current instructions')
        (self.source / 'references').mkdir()
        (self.source / 'references/more.md').write_text('reference')
        self.target = self.root / 'home/skills/example'
        self.backups = self.root / 'home/backups'

    def copy(self):
        shutil.copytree(self.source, self.target)

    def test_new_link_then_idempotent_and_receipt_serializable(self):
        plan = SkillPlan(self.source, self.target)
        self.assertIsNone(plan.apply(self.backups))
        before = self.target.lstat().st_mtime_ns
        receipt = json.loads(json.dumps(plan.receipt))
        again = SkillPlan(self.source, self.target, receipt)
        self.assertEqual(again.action, 'keep')
        self.assertIsNone(again.apply(self.backups))
        self.assertEqual(self.target.lstat().st_mtime_ns, before)
        self.assertFalse(self.backups.exists())

    def test_current_copy_is_adopted_and_every_file_backed_up(self):
        self.copy()
        (self.target / '.DS_Store').write_bytes(b'mac metadata')
        plan = SkillPlan(self.source, self.target)
        backup = plan.apply(self.backups)
        self.assertEqual(self.target.resolve(), self.source)
        self.assertEqual((backup / '.DS_Store').read_bytes(), b'mac metadata')
        self.assertEqual(files(backup), plan.receipt['files'])
        (self.source / 'SKILL.md').write_text('next release')
        self.assertEqual((self.target / 'SKILL.md').read_text(), 'next release')

    def test_previous_receipt_handles_archive_without_git_history(self):
        self.copy()
        receipt = SkillPlan(self.source, self.target).receipt
        (self.source / 'SKILL.md').write_text('next release')
        with patch('matsugit.skill_install.shipped_revision', side_effect=AssertionError('not needed')):
            plan = SkillPlan(self.source, self.target, receipt)
        self.assertIn('previous installation', plan.reason)
        backup = plan.apply(self.backups)
        self.assertEqual((backup / 'SKILL.md').read_text(), 'current instructions')

    def test_custom_reference_is_preserved_with_precise_diagnostic(self):
        self.copy()
        (self.target / 'references/more.md').write_text('my edits')
        with self.assertRaisesRegex(ValueError, r'references/more.md \(different\)'):
            SkillPlan(self.source, self.target)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual((self.target / 'references/more.md').read_text(), 'my edits')
        self.assertFalse(self.backups.exists())

    def test_additions_deletions_and_nested_symlinks_are_not_adopted(self):
        self.copy()
        extra = self.target / 'custom.md'
        extra.write_text('mine')
        with self.assertRaisesRegex(ValueError, 'custom.md'):
            SkillPlan(self.source, self.target)
        extra.unlink()
        reference = self.target / 'references/more.md'
        reference.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            SkillPlan(self.source, self.target)
        reference.symlink_to(self.source / 'references/more.md')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            SkillPlan(self.source, self.target)

    def test_dry_plan_writes_nothing(self):
        self.copy()
        plan = SkillPlan(self.source, self.target)
        self.assertIn('would link', plan.describe())
        self.assertFalse(self.target.is_symlink())
        self.assertFalse(self.backups.exists())

    def test_concurrent_edit_and_source_change_abort(self):
        self.copy()
        plan = SkillPlan(self.source, self.target)
        (self.target / 'SKILL.md').write_text('just edited')
        with self.assertRaisesRegex(ValueError, 'changed while'):
            plan.apply(self.backups)
        self.assertEqual((self.target / 'SKILL.md').read_text(), 'just edited')
        (self.target / 'SKILL.md').write_text('current instructions')
        plan = SkillPlan(self.source, self.target)
        (self.source / 'SKILL.md').write_text('new source')
        with self.assertRaisesRegex(ValueError, 'changed while'):
            plan.apply(self.backups)
        self.assertFalse(self.backups.exists())

    def test_copy_replaced_during_plan_is_retained_even_if_identical(self):
        self.copy()
        plan = SkillPlan(self.source, self.target)
        self.target.rename(self.target.with_name('saved'))
        self.copy()
        with self.assertRaisesRegex(ValueError, 'changed while'):
            plan.apply(self.backups)

    def test_relative_link_to_an_identical_source_can_move(self):
        old = self.root / 'home/skills/old'
        shutil.copytree(self.source, old)
        self.target.symlink_to('old')
        plan = SkillPlan(self.source, self.target)
        backup = plan.apply(self.backups)
        self.assertTrue(backup.is_symlink())
        self.assertEqual(backup.readlink(), Path('old'))
        self.assertEqual((old / 'SKILL.md').read_text(), 'current instructions')
        self.assertEqual(self.target.resolve(), self.source)

    def test_only_receipted_broken_link_is_repaired(self):
        self.target.parent.mkdir(parents=True)
        missing = self.root / 'old/skill'
        self.target.symlink_to(missing)
        with self.assertRaisesRegex(ValueError, 'retained'):
            SkillPlan(self.source, self.target)
        plan = SkillPlan(self.source, self.target, {'source': str(missing)})
        plan.apply(self.backups)
        self.assertEqual(self.target.resolve(), self.source)

    def test_failed_link_creation_restores_original(self):
        self.copy()
        plan = SkillPlan(self.source, self.target)
        with patch.object(Path, 'symlink_to', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                plan.apply(self.backups)
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(files(self.target), files(self.source))

    def test_concurrent_new_destination_is_never_replaced(self):
        self.copy()
        plan = SkillPlan(self.source, self.target)
        def concurrent_writer(*args, **kwargs):
            self.target.write_text('created during migration')
            raise FileExistsError('already exists')
        with patch.object(Path, 'symlink_to', side_effect=concurrent_writer):
            with self.assertRaisesRegex(ValueError, 'Original retained at'):
                plan.apply(self.backups)
        self.assertEqual(self.target.read_text(), 'created during migration')
        backup = next(self.backups.glob('*/example'))
        self.assertEqual(files(backup), files(self.source))

    def test_generated_files_are_backed_up_but_instruction_files_are_not_ignored(self):
        self.copy()
        cache = self.target / '__pycache__'
        cache.mkdir()
        (cache / 'helper.cpython-310.pyc').write_bytes(b'bytecode')
        plan = SkillPlan(self.source, self.target)
        self.assertIn('unchanged copy', plan.reason)
        (cache / 'instructions.md').write_text('retain these instructions too')
        with self.assertRaisesRegex(ValueError, 'instructions.md'):
            SkillPlan(self.source, self.target)

    def test_history_older_than_twenty_releases_is_recognized(self):
        repo = self.root / 'source'
        def git(*args):
            subprocess.run(['git', '-C', str(repo), *args], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        git('init', '-q')
        git('config', 'user.name', 'Synthetic Test')
        git('config', 'user.email', 'test@example.invalid')
        git('add', '.')
        git('commit', '-qm', 'initial skill')
        self.copy()
        for index in range(23):
            (self.source / 'SKILL.md').write_text(f'release {index}')
            git('commit', '-qam', f'release {index}')
        plan = SkillPlan(self.source, self.target)
        self.assertIn('shipped copy', plan.reason)
        plan.apply(self.backups)
        self.assertEqual((self.target / 'SKILL.md').read_text(), 'release 22')


if __name__ == '__main__':
    unittest.main()
