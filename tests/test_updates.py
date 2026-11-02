"""Local bare remotes and synthetic renderers only; no account or organization data."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import Error, git
from matsugit.updates import (Catalog, LOCK, VENDOR, digest, encoded, manage,
                               safe_name, target_path, wrapper)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'GIT_AUTHOR_NAME':'Test', 'GIT_AUTHOR_EMAIL':'test@example.invalid',
                                         'GIT_COMMITTER_NAME':'Test','GIT_COMMITTER_EMAIL':'test@example.invalid'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.source = self.root/'releases'; self.source.mkdir()
        git(self.source,'init','-b','main')
        self.remote = self.root/'remote.git'; git(self.root,'init','--bare',self.remote)
        self.repo = self.root/'docs'; self.repo.mkdir();git(self.repo,'init','-b','main')
        (self.repo/'scripts').mkdir(); self.legacy=b'print("legacy")\n'
        (self.repo/'scripts/build.py').write_bytes(self.legacy)
        (self.repo/'.gitlab-ci.yml').write_text('existing: manual gate\n')
        (self.repo/'document.md').write_text('Original document\n')
        git(self.repo,'add','.');git(self.repo,'commit','-m','initial')
        git(self.repo,'remote','add','origin',self.remote);git(self.repo,'push','origin','main')
        self.project=dict(name='docs',repo=str(self.repo),bundle='synthetic')
        self.config=self.root/'updates.json'
        self.catalog=dict(schema=1,bundles={'synthetic':dict(latest='1.0',versions={})})
        self.make_release('1.0')
        self.write_config()

    def write_config(self, projects=None):
        self.config.write_bytes(encoded(dict(schema=1,repository=str(self.source),ref='main',catalog='catalog.json',
                                            projects=projects or [self.project])))

    def make_release(self, version, bad_check=False):
        folder=self.source/version;folder.mkdir()
        payload={'scripts/build.py':f'print("release {version}")\n'.encode(),
                 'checks/smoke.py':b'raise SystemExit(1)\n' if bad_check else b'print("synthetic check passed")\n'}
        for name,data in payload.items():
            p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        manifest=dict(schema=1,bundle='synthetic',version=version,
                      files={k:digest(v) for k,v in payload.items()},check='checks/smoke.py',
                      entrypoints={'scripts/build.py':'scripts/build.py'},
                      adopt={'scripts/build.py':[digest(self.legacy)]})
        raw=encoded(manifest);(folder/'release.json').write_bytes(raw)
        self.catalog['bundles']['synthetic']['latest']=version
        self.catalog['bundles']['synthetic']['versions'][version]=dict(manifest=f'{version}/release.json',sha256=digest(raw))
        (self.source/'catalog.json').write_bytes(encoded(self.catalog))
        git(self.source,'add','.');git(self.source,'commit','-m',f'release {version}')

    def run_update(self, command='update', **kwargs):
        manage(command,self.config,all_projects=True,**kwargs)

    def test_update_idempotent_and_preserves_unrelated_dirty_document(self):
        (self.repo/'document.md').write_text('Uncommitted document edit\n')
        (self.repo/'unrelated.html').write_text('not staged')
        self.run_update()
        head=git(self.repo,'rev-parse','HEAD')
        self.assertEqual(json.loads((self.repo/LOCK).read_text())['release']['version'],'1.0')
        self.assertEqual((self.repo/'scripts/build.py').read_bytes(),wrapper('scripts/build.py'))
        self.assertEqual(git(self.repo,'show','HEAD:document.md'),'Original document')
        self.assertEqual((self.repo/'.gitlab-ci.yml').read_text(),'existing: manual gate\n')
        self.assertIn('document.md',git(self.repo,'status','--short'))
        self.assertEqual(git(self.remote,'rev-parse','main'),head)
        self.run_update();self.assertEqual(git(self.repo,'rev-parse','HEAD'),head)

    def test_dry_run_checks_but_does_not_install_or_push(self):
        head=git(self.repo,'rev-parse','HEAD');self.run_update(dry_run=True)
        self.assertFalse((self.repo/LOCK).exists())
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),head)
        self.assertEqual(git(self.remote,'rev-parse','main'),head)

    def test_update_then_rollback_pins_previous_release(self):
        self.run_update();self.make_release('2.0');self.run_update()
        self.assertIn('2.0',(self.repo/VENDOR/'scripts/build.py').read_text())
        self.run_update('rollback')
        self.assertIn('1.0',(self.repo/VENDOR/'scripts/build.py').read_text())
        self.assertEqual(json.loads((self.repo/LOCK).read_text())['history'],[])

    def test_local_renderer_edits_stop_update(self):
        self.run_update();self.make_release('2.0')
        p=self.repo/VENDOR/'scripts/build.py';p.write_text('local custom code\n')
        with self.assertRaisesRegex(Error,'edited'):
            self.run_update()
        self.assertEqual(p.read_text(),'local custom code\n')

    def test_changed_unmanaged_migration_baseline_is_not_overwritten(self):
        p=self.repo/'scripts/build.py';p.write_text('different local renderer\n')
        with self.assertRaisesRegex(Error,'approved migration baseline'):
            self.run_update()
        self.assertFalse((self.repo/LOCK).exists())

    def test_all_preflight_before_installing_any_project(self):
        second=dict(self.project,name='other',repo=str(self.root/'missing'))
        self.write_config([self.project,second])
        with self.assertRaisesRegex(Error,'Checkout not found'):
            self.run_update()
        self.assertFalse((self.repo/LOCK).exists())

    def test_failed_smoke_does_not_change_target(self):
        self.make_release('2.0',bad_check=True)
        with self.assertRaises(Error):self.run_update()
        self.assertEqual((self.repo/'scripts/build.py').read_bytes(),self.legacy)
        self.assertFalse((self.repo/LOCK).exists())

    def test_checksums_and_mutable_release_versions_rejected(self):
        self.run_update()
        file=self.source/'1.0/scripts/build.py';file.write_text('changed without checksum')
        git(self.source,'add','.');git(self.source,'commit','-m','tamper')
        with self.assertRaisesRegex(Error,'checksum mismatch'):
            self.run_update()

    def test_staged_work_and_unpublished_commits_are_not_pushed(self):
        (self.repo/'document.md').write_text('secret draft')
        git(self.repo,'add','document.md')
        with self.assertRaisesRegex(Error,'staged changes'):self.run_update()
        git(self.repo,'commit','-m','unrelated draft')
        with self.assertRaisesRegex(Error,'unpublished'):self.run_update()
        self.assertEqual(git(self.remote,'show','main:document.md'),'Original document')

    def test_retry_own_failed_push_without_second_commit(self):
        from matsugit import updates
        original=updates.git
        def fail_push(repo,*args):
            if args[0]=='push':raise Error('network unavailable')
            return original(repo,*args)
        with patch.object(updates,'git',side_effect=fail_push):
            with self.assertRaisesRegex(Error,'push failed'):self.run_update()
        head=git(self.repo,'rev-parse','HEAD')
        self.run_update()
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),head)
        self.assertEqual(git(self.remote,'rev-parse','main'),head)

    def test_no_previous_version_is_not_a_reset(self):
        self.run_update();head=git(self.repo,'rev-parse','HEAD')
        with self.assertRaisesRegex(Error,'no previous managed release'):self.run_update('rollback')
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),head)

    def test_path_and_symlink_boundaries(self):
        for name in ('../x','/tmp/x','.git/config','a/../b','a//b','.',r'a\b'):
            with self.assertRaises(Error):safe_name(name)
        (self.repo/'outside').symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(Error):target_path(self.repo,'outside/catalog.json')

    def test_offline_status(self):
        self.run_update('status')
        self.run_update();self.run_update('status')

    def legacy_install(self):
        """Build a genuine legacy lock and wrapper against the same verified release."""
        self.run_update()
        lock = json.loads((self.repo / LOCK).read_text())
        (self.repo / VENDOR).rename(self.repo / '.folioforge-renderer')
        script = self.repo / 'scripts/build.py'
        script.write_text(script.read_text().replace('matsugit', 'folioforge'))
        lock['files'] = {name.replace(VENDOR, '.folioforge-renderer'): value
                         for name, value in lock['files'].items()}
        lock['files']['scripts/build.py'] = digest(script.read_bytes())
        (self.repo / LOCK).unlink()
        (self.repo / 'folioforge-renderer.lock.json').write_bytes(encoded(lock))
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'Synthetic legacy installation')
        git(self.repo, 'push', 'origin', 'main')

    def test_legacy_install_migrates_same_release_and_preserves_ci_and_document(self):
        self.legacy_install()
        (self.repo / 'document.md').write_text('Unsaved draft\n')
        self.run_update(dry_run=True)
        self.assertTrue((self.repo / 'folioforge-renderer.lock.json').exists())
        self.run_update()
        self.assertFalse((self.repo / 'folioforge-renderer.lock.json').exists())
        self.assertTrue((self.repo / VENDOR / 'scripts/build.py').exists())
        self.assertEqual(json.loads((self.repo / LOCK).read_text())['history'], [])
        self.assertEqual((self.repo / 'document.md').read_text(), 'Unsaved draft\n')
        self.assertEqual((self.repo / '.gitlab-ci.yml').read_text(), 'existing: manual gate\n')
        head = git(self.repo, 'rev-parse', 'HEAD')
        self.run_update()
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), head)

    def test_legacy_edited_renderer_is_preserved(self):
        self.legacy_install()
        source = self.repo / '.folioforge-renderer/scripts/build.py'
        source.write_text('Local customization\n')
        with self.assertRaisesRegex(Error, 'edited'):
            self.run_update()
        self.assertEqual(source.read_text(), 'Local customization\n')


if __name__=='__main__':unittest.main()
