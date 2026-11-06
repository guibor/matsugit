"""Two-way review uses disposable local repositories, never user documents."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import Error
from matsugit import git_exchange as x


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.repo = self.root / 'repo'; self.repo.mkdir()
        self.remote = self.root / 'remote.git'; self.web = self.root / 'web'
        x.run(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        x.run(self.repo, 'init', '-b', 'main')
        for key, value in [('user.name','Test'), ('user.email','test@example.invalid'), ('commit.gpgsign','false'), ('core.autocrlf','false')]:
            x.run(self.repo, 'config', key, value)
        self.source = self.repo / 'deck.md'; self.base = '# Topic\n\n## Claim\n\nEvidence\n'
        self.source.write_text(self.base)
        (self.repo/'other.txt').write_text('Original\n')
        x.run(self.repo, 'add', '.'); x.run(self.repo, 'commit', '-m', 'Base')
        x.run(self.repo, 'remote', 'add', 'origin', str(self.remote)); x.run(self.repo, 'push', '-u', 'origin', 'main')
        x.run(self.root, 'clone', str(self.remote), str(self.web))
        for key, value in [('user.name','Web'), ('user.email','web@example.invalid'), ('commit.gpgsign','false')]:
            x.run(self.web, 'config', key, value)

    def upstream(self, changes):
        for name, text in changes.items():
            path = self.web/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        x.run(self.web, 'add', '.'); x.run(self.web, 'commit', '-m', 'Web edit'); x.run(self.web, 'push')

    def sync(self, text, assets=(), plan=None):
        plan = plan or x.plan(self.source, assets)
        self.assertEqual(plan['blocked'], [])
        return x.exchange(self.source, text, assets=assets, expected=plan['fingerprint'], message='Reviewed document', confirmed=True)

    def test_local_commit_push_only_selected_document_and_backups(self):
        self.source.write_text(self.base+'Local\n')
        (self.repo/'other.txt').write_text('Unrelated draft\n')
        (self.repo/'scratch.txt').write_text('Private scratch\n')
        result = self.sync(self.source.read_text())
        self.assertEqual(x.line(self.remote, 'show', 'main:deck.md'), self.source.read_text().strip())
        self.assertEqual(x.line(self.remote, 'show', 'main:other.txt'), 'Original')
        self.assertEqual((self.repo/'other.txt').read_text(), 'Unrelated draft\n')
        self.assertEqual((self.repo/'scratch.txt').read_text(), 'Private scratch\n')
        self.assertEqual(x.line(self.repo, 'diff', '--cached'), '')
        self.assertEqual((Path(result['recovery'])/'document-before').read_text(), self.source.read_text())

    def test_overlap_review_integrates_incoming_and_retains_other_dirty_files(self):
        self.upstream({'deck.md':self.base.replace('Claim','Upstream claim'), 'new.txt':'Web-only\n'})
        self.source.write_text(self.base.replace('Claim','Local claim'))
        (self.repo/'other.txt').write_text('Keep this\n')
        plan = x.plan(self.source)
        self.assertEqual(plan['base'], self.base)
        self.assertIn('Upstream claim', plan['incoming']); self.assertIn('Local claim', plan['local'])
        merged = self.base.replace('Claim','Reviewed claim')
        self.sync(merged, plan=plan)
        self.assertEqual(self.source.read_text(), merged)
        self.assertEqual((self.repo/'other.txt').read_text(), 'Keep this\n')
        self.assertEqual((self.repo/'new.txt').read_text(), 'Web-only\n')
        self.assertEqual(x.line(self.repo, 'rev-parse', 'HEAD'), x.line(self.remote, 'rev-parse', 'main'))

    def test_plan_cancel_and_stale_confirmation_never_write(self):
        before = x.line(self.repo, 'rev-parse', 'HEAD'); plan = x.plan(self.source)
        self.assertEqual(self.source.read_text(), self.base)
        self.assertEqual(x.line(self.repo, 'status', '--porcelain'), '')
        self.source.write_text(self.base+'Agent edit\n')
        with self.assertRaisesRegex(Error, 'changed since review'):
            x.exchange(self.source, self.base+'Stale', expected=plan['fingerprint'], message='No', confirmed=True)
        self.assertEqual(x.line(self.repo, 'rev-parse', 'HEAD'), before)
        self.assertTrue(self.source.read_text().endswith('Agent edit\n'))

    def test_staging_and_unrelated_commits_block(self):
        self.source.write_text('Edit'); x.run(self.repo, 'add', 'deck.md')
        self.assertTrue(any('Staged' in s for s in x.plan(self.source)['blocked']))
        x.run(self.repo, 'commit', '-m', 'Document')
        (self.repo/'other.txt').write_text('Unrelated commit')
        x.run(self.repo, 'add', 'other.txt'); x.run(self.repo, 'commit', '-m', 'Other')
        self.assertTrue(any('Unpublished' in s for s in x.plan(self.source)['blocked']))

    def test_push_failure_retry_keeps_local_commit(self):
        self.source.write_text(self.base+'Edit\n'); plan = x.plan(self.source)
        real_run = x.run
        def fail(repo, *args, **kwargs):
            if args[0] == 'push': raise Error('Simulated offline')
            return real_run(repo, *args, **kwargs)
        with patch.object(x, 'run', side_effect=fail):
            with self.assertRaisesRegex(Error, 'recovery retained'):
                self.sync(self.source.read_text(), plan=plan)
        commit = x.line(self.repo, 'rev-parse', 'HEAD')
        self.assertNotEqual(commit, x.line(self.remote, 'rev-parse', 'main'))
        self.assertEqual(x.line(self.repo, 'status', '--porcelain'), '')
        self.sync(self.source.read_text())
        self.assertEqual(x.line(self.remote, 'rev-parse', 'main'), commit)

    def test_changed_upstream_requires_new_review(self):
        plan = x.plan(self.source)
        self.upstream({'deck.md':self.base+'New web edit\n'})
        with self.assertRaisesRegex(Error, 'changed since review'):
            x.exchange(self.source, 'Old', expected=plan['fingerprint'], message='No', confirmed=True)
        self.assertEqual(self.source.read_text(), self.base)

    def test_ignored_incoming_file_blocks_without_staging_or_overwrite(self):
        (self.repo/'.git/info/exclude').write_text('incoming.txt\n')
        (self.repo/'incoming.txt').write_text('Ignored local data\n')
        self.upstream({'incoming.txt':'Remote data\n'})
        self.source.write_text(self.base+'Local\n'); head = x.line(self.repo, 'rev-parse','HEAD')
        with self.assertRaisesRegex(Error, 'overwritten'):
            self.sync(self.source.read_text())
        self.assertEqual((self.repo/'incoming.txt').read_text(), 'Ignored local data\n')
        self.assertEqual(x.line(self.repo, 'diff', '--cached'), '')
        self.assertEqual(x.line(self.repo, 'rev-parse', 'HEAD'), head)

    def test_referenced_assets_opt_in_and_retry(self):
        (self.repo/'figure.svg').write_text('<svg/>')
        self.source.write_text(self.base+'\n![Evidence](figure.svg)\n')
        plan = x.plan(self.source)
        self.assertIn('figure.svg', plan['assets'])
        result = self.sync(self.source.read_text(), ['figure.svg'])
        self.assertEqual(result['paths'], ['deck.md','figure.svg'])
        self.assertEqual(x.line(self.remote, 'show', 'main:figure.svg'), '<svg/>')

    def test_failed_asset_push_can_retry_without_an_extra_commit(self):
        (self.repo/'figure.svg').write_text('<svg/>')
        self.source.write_text(self.base+'\n![Evidence](figure.svg)\n')
        real_run = x.run
        def fail(repo, *args, **kwargs):
            if args[0] == 'push': raise Error('Offline')
            return real_run(repo, *args, **kwargs)
        with patch.object(x, 'run', side_effect=fail):
            with self.assertRaisesRegex(Error, 'Offline'):
                self.sync(self.source.read_text(), ['figure.svg'])
        revision = x.line(self.repo, 'rev-parse','HEAD')
        self.sync(self.source.read_text(), ['figure.svg'])
        self.assertEqual(x.line(self.remote, 'rev-parse','main'), revision)

    def test_remote_advance_after_review_rejects_push_keeps_both_histories(self):
        self.source.write_text(self.base+'Local\n')
        real_run = x.run; pushed = False
        def advance(repo, *args, **kwargs):
            nonlocal pushed
            if args[0] == 'push' and not pushed:
                pushed = True
                self.upstream({'deck.md':self.base+'Later remote edit\n'})
            return real_run(repo, *args, **kwargs)
        with patch.object(x, 'run', side_effect=advance):
            with self.assertRaisesRegex(Error, 'rejected'):
                self.sync(self.source.read_text())
        self.assertIn('Later remote edit', x.line(self.remote, 'show', 'main:deck.md'))
        self.assertEqual(self.source.read_text(), self.base+'Local\n')
        self.assertTrue(any('diverged' in reason for reason in x.plan(self.source)['blocked']))

    def test_new_file_edit_during_install_is_never_overwritten(self):
        self.upstream({'deck.md':self.base+'Remote\n'})
        real_run = x.run
        def edit(repo, *args, **kwargs):
            result = real_run(repo, *args, **kwargs)
            if '--ff-only' in args: self.source.write_text('Agent edit while committing\n')
            return result
        remote = x.line(self.remote, 'rev-parse','main')
        with patch.object(x, 'run', side_effect=edit):
            with self.assertRaisesRegex(Error, 'changed during Git sync'):
                self.sync(self.base+'Reviewed\n')
        self.assertEqual(self.source.read_text(), 'Agent edit while committing\n')
        self.assertEqual(x.line(self.remote, 'rev-parse','main'), remote)

    def test_unselected_overlap_and_selected_binary_overlap_block(self):
        (self.repo/'figure.svg').write_text('<svg>base</svg>')
        self.source.write_text(self.base+'\n![Evidence](figure.svg)\n')
        x.run(self.repo,'add','.'); x.run(self.repo,'commit','-m','Figure'); x.run(self.repo,'push')
        x.run(self.web,'pull','--ff-only')
        self.upstream({'figure.svg':'<svg>remote</svg>', 'other.txt':'Remote'})
        (self.repo/'other.txt').write_text('Local')
        (self.repo/'figure.svg').write_text('<svg>local</svg>')
        plan = x.plan(self.source, ['figure.svg'])
        self.assertTrue(any('unselected' in s for s in plan['blocked']))
        self.assertTrue(any('binary' in s for s in plan['blocked']))

    def test_push_destination_shown_and_stale_url_refused(self):
        alternate = self.root/'alternate.git'
        x.run(self.root,'clone','--bare',str(self.remote),str(alternate))
        x.run(self.repo,'remote','set-url','--push','origin',str(alternate))
        plan = x.plan(self.source)
        self.assertEqual(plan['destination'], str(alternate))
        x.run(self.repo,'remote','set-url','--push','origin',str(self.remote))
        with self.assertRaisesRegex(Error, 'changed since review'):
            x.exchange(self.source, self.base, expected=plan['fingerprint'], message='No', confirmed=True)

    def test_hooks_ignored_source_and_conversion_require_git(self):
        hook = self.repo/'.git/hooks/pre-commit'; hook.write_text('#!/bin/sh\nexit 0\n'); hook.chmod(0o700)
        self.assertTrue(any('commit hooks' in s for s in x.plan(self.source)['blocked']))
        hook.unlink()
        (self.repo/'.gitattributes').write_text('*.md filter=custom\n')
        self.assertTrue(any('conversion' in s for s in x.plan(self.source)['blocked']))
        (self.repo/'.git/info/exclude').write_text('ignored.md\n')
        ignored = self.repo/'ignored.md'; ignored.write_text('Never stage me')
        self.assertTrue(any('ignored' in s for s in x.plan(ignored)['blocked']))

    def test_symlink_entrypoint_resolves_without_replacing_link(self):
        link = self.root/'link.md'; link.symlink_to(self.source)
        plan = x.plan(link)
        x.exchange(link, self.base+'Via link\n', expected=plan['fingerprint'], message='Link', confirmed=True)
        self.assertTrue(link.is_symlink()); self.assertIn('Via link', self.source.read_text())


if __name__ == '__main__': unittest.main()
