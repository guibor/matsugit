import realtmp  # noqa: F401  (resolve the temporary directory before any test creates one)
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import Error, config, git
from matsugit import adopt, canonical, git_sync, targets
from matsugit.publish import setup_ci, publish


class CanonicalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.notes = self.root / 'notes'; self.notes.mkdir()
        self.source = self.notes / 'Deck.md'
        self.source.write_bytes(b'---\r\ntitle: Exact\r\n---\r\n\r\n## Claim\r\n\r\n![Figure](image.svg)\r\n\r\n::: agent-comment\r\nKeep this request\r\n:::\r\n')
        (self.notes / 'image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        env = patch.dict(os.environ, {'MATSUGIT_CONFIG': str(self.root / 'absent.json')})
        env.start(); self.addCleanup(env.stop)
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        self.remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.settings = config(self.source, {'repo':str(self.repo), 'build':'ci', 'move_source':True})
        setup_ci(self.settings, 'gitlab')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Synthetic CI')
        git(self.repo, 'push', '-u', 'origin', 'main')
        identity = patch('matsugit.publish.identity', return_value=('git.example.invalid', 'team/docs', 'https://git.example.invalid/team/docs'))
        identity.start(); self.addCleanup(identity.stop)

    def other_checkout(self):
        other = self.root / 'web'
        git(self.root, 'clone', str(self.remote), str(other))
        git(other, 'config', 'user.name', 'Web editor')
        git(other, 'config', 'user.email', 'web@example.invalid')
        return other

    def test_adopt_exact_bytes_assets_symlinks_and_publish_in_place(self):
        original = self.source.read_bytes()
        reviewed = targets.plan(self.settings)
        self.assertFalse(self.source.is_symlink())
        sha = publish(self.settings, confirmed=True)
        dest = Path(reviewed['destination'])
        self.assertTrue(self.source.is_symlink())
        self.assertTrue((self.notes / 'image.svg').is_symlink())
        self.assertEqual(dest.read_bytes(), original)
        self.assertEqual(self.source.resolve(), dest)
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), sha)
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        dest.write_text('## Changed in the canonical file\n\n![Figure](image.svg)\n')
        settings = dict(self.settings, source=dest, move_source=False)
        plan = targets.plan(settings)
        self.assertFalse(plan['move_source'])
        publish(settings, confirmed=True)
        self.assertEqual(self.source.read_bytes(), dest.read_bytes())
        self.assertEqual(len(list(self.repo.rglob('source.md'))), 1)

    def test_org_adoption_is_not_conversion(self):
        source = self.notes / 'deck.org'
        source.write_text('#+title: Caf\u00e9\n\n* Evidence\n[[file:image.svg]]\n')
        before = source.read_bytes()
        plan = adopt.plan(source, self.repo, 'topics/deck.org')
        adopt.apply(plan)
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(source.is_symlink())

    def test_collision_traversal_symlink_and_changed_plan_refused(self):
        for path in ('../escape.md', '.git/config'):
            with self.assertRaises(Error): adopt.plan(self.source, self.repo, path)
        existing = self.repo / 'existing.md'; existing.write_text('Do not overwrite')
        with self.assertRaisesRegex(Error, 'overwrite'): adopt.plan(self.source, self.repo, 'existing.md')
        reviewed = adopt.plan(self.source, self.repo, 'topics/deck.md')
        (self.notes / 'image.svg').write_text('changed')
        with self.assertRaisesRegex(Error, 'changed'): adopt.apply(reviewed)
        self.assertFalse(self.source.is_symlink())
        (self.repo / 'link').symlink_to(self.notes, target_is_directory=True)
        with self.assertRaises(Error): adopt.plan(self.source, self.repo, 'link/deck.md')

    def test_partial_symlink_failure_rolls_back_without_losing_bytes(self):
        reviewed = adopt.plan(self.source, self.repo, 'topics/deck.md')
        before = {m['source']: Path(m['source']).read_bytes() for m in reviewed['moves']}
        replace = os.replace
        count = 0
        def fail_second(src, dst):
            nonlocal count
            if str(src).endswith('.link'):
                count += 1
                if count == 2: raise OSError('simulated permission failure')
            return replace(src, dst)
        with patch('matsugit.adopt.os.replace', side_effect=fail_second):
            with self.assertRaisesRegex(Error, 'permission'): adopt.apply(reviewed)
        for path, value in before.items():
            self.assertFalse(Path(path).is_symlink())
            self.assertEqual(Path(path).read_bytes(), value)

    def test_ambiguous_relative_dependencies_refused(self):
        for text in ('[Other](../other.md)', '[Other](other.md)', '![Image](/tmp/image.svg)'):
            self.source.write_text(text)
            with self.assertRaises(Error): adopt.plan(self.source, self.repo, 'topics/deck.md')
        self.assertFalse(self.source.is_symlink())

    def test_conversion_and_unrelated_staging_never_move_source(self):
        with self.assertRaisesRegex(Error, 'format'):
            adopt.plan(self.source, self.repo, 'topics/deck.org')
        (self.repo / 'unrelated.txt').write_text('Keep my staged work')
        git(self.repo, 'add', 'unrelated.txt')
        with self.assertRaisesRegex(Error, 'Staged'):
            publish(self.settings, confirmed=True)
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(git(self.repo, 'diff', '--cached', '--name-only'), 'unrelated.txt')

    def test_unrelated_unstaged_and_untracked_work_survives_publication(self):
        tracked = self.repo / 'unrelated.txt'
        tracked.write_text('Committed value\n')
        git(self.repo, 'add', 'unrelated.txt')
        git(self.repo, 'commit', '-m', 'Add unrelated file')
        git(self.repo, 'push')
        tracked.write_text('Local draft\n')
        untracked = self.repo / 'another draft.txt'
        untracked.write_text('Untracked draft\n')

        sha = publish(self.settings, confirmed=True)

        self.assertEqual(git(self.remote, 'rev-parse', 'main'), sha)
        self.assertEqual(tracked.read_text(), 'Local draft\n')
        self.assertEqual(untracked.read_text(), 'Untracked draft\n')
        self.assertEqual(git(self.repo, 'diff', '--cached', '--name-only'), '')
        self.assertEqual(git(self.repo, 'stash', 'list'), '')

    def test_inplace_topics_preserves_sibling_assets_without_copying(self):
        (self.repo / 'scripts').mkdir()
        (self.repo / 'scripts/build_pages.py').write_text('# synthetic existing renderer\n')
        (self.repo / 'topics/nested').mkdir(parents=True)
        source = self.repo / 'topics/nested/deck.md'
        (self.repo / 'topics/image.svg').write_text('<svg/>')
        source.write_text('## Claim\n\n![Image](../image.svg)\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Existing topic'); git(self.repo, 'push')
        settings = dict(self.settings, source=source, ci_layout='topics', move_source=False)
        source.write_text(source.read_text() + '\nExact new paragraph.\n')
        before = source.read_bytes()
        publish(settings, confirmed=True)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(len(list(self.repo.rglob('deck.md'))), 1)
        self.assertFalse(source.is_symlink())

    def test_project_config_cannot_enable_relocation(self):
        (self.notes / 'matsugit.json').write_text('{"move_source": true}')
        self.assertFalse(config(self.source, {'command':'publish'})['move_source'])

    def test_sync_upstream_through_symlink_without_mutating_on_check(self):
        publish(self.settings, confirmed=True)
        dest = self.source.resolve()
        other = self.other_checkout()
        (other / dest.relative_to(self.repo)).write_text('## Edited in GitLab\n')
        git(other, 'add', '.'); git(other, 'commit', '-m', 'Web edit'); git(other, 'push')
        old = self.source.read_bytes()
        checked = git_sync.sync(self.source, check=True)
        self.assertEqual(checked['status'], 'updates-available')
        self.assertEqual(self.source.read_bytes(), old)
        result = git_sync.sync(self.source, expected=checked['fingerprint'], confirmed=True)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(self.source.read_text(), '## Edited in GitLab\n')
        self.assertTrue(self.source.is_symlink())

    def test_dirty_and_diverged_sync_leave_work_untouched(self):
        source = self.repo / 'note.md'; source.write_text('# Base\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Base'); git(self.repo, 'push')
        other = self.other_checkout()
        (other / 'note.md').write_text('# Upstream\n')
        git(other, 'add', '.'); git(other, 'commit', '-m', 'Upstream'); git(other, 'push')
        source.write_text('# Local draft\n')
        with self.assertRaisesRegex(Error, 'Local changes'): git_sync.sync(source, confirmed=True)
        self.assertEqual(source.read_text(), '# Local draft\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Local')
        with self.assertRaisesRegex(Error, 'diverged'): git_sync.sync(source, confirmed=True)
        self.assertEqual(git(self.repo, 'stash', 'list'), '')
        self.assertEqual(source.read_text(), '# Local draft\n')

    def test_stale_confirmation_and_failed_fetch_do_not_modify_files(self):
        source = self.repo / 'note.md'; source.write_text('# Base\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Base'); git(self.repo, 'push')
        checked = git_sync.sync(source, check=True)
        source.write_text('# New\n')
        with self.assertRaisesRegex(Error, 'changed since review'):
            git_sync.sync(source, expected=checked['fingerprint'], confirmed=True)
        git(self.repo, 'remote', 'set-url', 'origin', str(self.root / 'absent.git'))
        with self.assertRaises(Error): git_sync.sync(source, confirmed=True)
        self.assertEqual(source.read_text(), '# New\n')

    def sync_fixture(self, upstream_path='incoming.md'):
        source = self.repo / 'note.md'; source.write_text('# Base\n')
        (self.repo / 'unrelated.txt').write_text('Original\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Base'); git(self.repo, 'push')
        other = self.other_checkout()
        (other / upstream_path).write_text('# Upstream\n')
        git(other, 'add', '.'); git(other, 'commit', '-m', 'Upstream'); git(other, 'push')
        return source

    def test_nonoverlapping_local_edits_and_untracked_files_survive_pull(self):
        source = self.sync_fixture()
        source.write_text('# My saved draft\n')
        unusual = self.repo / ' leading space\nand newline.txt'
        unusual.write_bytes(b'Untracked exact bytes\r\n')
        (self.repo / 'unrelated.txt').write_text('Uncommitted unrelated edit\n')
        checked = git_sync.sync(source, check=True)
        self.assertEqual(checked['status'], 'updates-available')
        self.assertEqual(checked['overlapping_changes'], [])
        self.assertIn(unusual.name, checked['local_changes'])
        self.assertEqual(git_sync.sync(source, expected=checked['fingerprint'], confirmed=True)['status'], 'updated')
        self.assertEqual(source.read_text(), '# My saved draft\n')
        self.assertEqual(unusual.read_bytes(), b'Untracked exact bytes\r\n')
        self.assertEqual((self.repo / 'unrelated.txt').read_text(), 'Uncommitted unrelated edit\n')
        self.assertEqual(git(self.repo, 'stash', 'list'), '')
        self.assertEqual(git(self.repo, 'diff', '--cached'), '')

    def test_same_file_overlap_is_reported_without_modification(self):
        source = self.sync_fixture('note.md')
        source.write_text('# My saved draft\n')
        head = git(self.repo, 'rev-parse', 'HEAD')
        checked = git_sync.sync(source, check=True)
        self.assertEqual(checked['status'], 'local-changes')
        self.assertEqual(checked['overlapping_changes'], ['note.md'])
        with self.assertRaisesRegex(Error, 'overlap incoming updates: note.md'):
            git_sync.sync(source, expected=checked['fingerprint'], confirmed=True)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), head)
        self.assertEqual(source.read_text(), '# My saved draft\n')

    def test_untracked_directory_and_incoming_file_overlap(self):
        source = self.sync_fixture('new-path')
        (self.repo / 'new-path').mkdir()
        (self.repo / 'new-path/local.txt').write_text('Keep\n')
        checked = git_sync.sync(source, check=True)
        self.assertEqual(checked['overlapping_changes'], ['new-path/local.txt'])
        with self.assertRaisesRegex(Error, 'Local changes'):
            git_sync.sync(source, confirmed=True)
        self.assertEqual((self.repo / 'new-path/local.txt').read_text(), 'Keep\n')

    def test_staged_changes_are_retained_and_reported_separately(self):
        source = self.sync_fixture()
        (self.repo / 'unrelated.txt').write_text('Staged work\n')
        git(self.repo, 'add', 'unrelated.txt')
        index = git(self.repo, 'write-tree')
        self.assertEqual(git_sync.sync(source, check=True)['status'], 'staged-changes')
        with self.assertRaisesRegex(Error, 'Staged changes'):
            git_sync.sync(source, confirmed=True)
        self.assertEqual(git(self.repo, 'write-tree'), index)

    def test_dirty_but_up_to_date_is_not_a_reconciliation_failure(self):
        source = self.sync_fixture()
        git_sync.sync(source, confirmed=True)
        source.write_text('# Saved not published\n')
        checked = git_sync.sync(source, check=True)
        self.assertEqual(checked['status'], 'up-to-date')
        self.assertTrue(checked['dirty'])
        self.assertEqual(git_sync.sync(source, confirmed=True)['status'], 'up-to-date')
        self.assertEqual(source.read_text(), '# Saved not published\n')

    def test_late_overlapping_edit_invalidates_review(self):
        source = self.sync_fixture()
        checked = git_sync.sync(source, check=True)
        (self.repo / 'incoming.md').write_text('Local file appeared\n')
        with self.assertRaisesRegex(Error, 'changed since review'):
            git_sync.sync(source, expected=checked['fingerprint'], confirmed=True)
        self.assertEqual((self.repo / 'incoming.md').read_text(), 'Local file appeared\n')

    def test_ignored_local_file_is_never_overwritten(self):
        source = self.sync_fixture()
        (self.repo / '.git/info/exclude').write_text('incoming.md\n')
        (self.repo / 'incoming.md').write_text('Ignored local content\n')
        head = git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaises(Error): git_sync.sync(source, confirmed=True)
        self.assertEqual((self.repo / 'incoming.md').read_text(), 'Ignored local content\n')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), head)

    def test_publish_refuses_upstream_changed_source_and_keeps_local_commit_on_failed_push(self):
        publish(self.settings, confirmed=True)
        dest = self.source.resolve(); settings = dict(self.settings, source=dest, move_source=False)
        other = self.other_checkout()
        (other / dest.relative_to(self.repo)).write_text('## Web update\n')
        git(other, 'add', '.'); git(other, 'commit', '-m', 'Web edit'); git(other, 'push')
        with self.assertRaisesRegex(Error, 'changed during pull'): publish(settings, confirmed=True)
        self.assertEqual(self.source.read_text(), '## Web update\n')
        dest.write_text('## Local update\n')
        real_git = canonical.git
        def reject_push(repo, *args):
            if args[0] == 'push': raise Error('synthetic push failure')
            return real_git(repo, *args)
        with patch.object(canonical, 'git', side_effect=reject_push):
            with self.assertRaisesRegex(Error, 'local commit'): publish(settings, confirmed=True)
        self.assertEqual(self.source.read_text(), '## Local update\n')
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        self.assertNotEqual(git(self.repo, 'rev-parse', 'HEAD'), git(self.remote, 'rev-parse', 'main'))

    def test_real_source_target_wins_over_host_default(self):
        path = self.repo / 'note.md'; path.write_text('## Local\n')
        link = self.notes / 'link.md'; link.symlink_to(path)
        prefs = self.root / 'settings.json'
        prefs.write_text(json.dumps({'default_publish_target':'other', 'publish_targets': {
            'here':{'repo':str(self.repo), 'provider':'gitlab', 'build':'ci'},
            'other':{'repo':str(self.root / 'other'), 'provider':'github'}}}))
        with patch.dict(os.environ, {'MATSUGIT_CONFIG':str(prefs)}):
            self.assertEqual(config(link, {'command':'publish'})['target'], 'here')
            self.assertEqual(config(link, {'command':'publish', 'target':'other'})['target'], 'other')


if __name__ == '__main__': unittest.main()
