import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from matsugit.core import config, Error, git
from matsugit import targets, exports
from matsugit.source import convert

QUARTO = os.environ.get('QUARTO')
ROOT = Path(__file__).resolve().parents[1]


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.global_file = self.root / 'global.json'
        self.env = patch.dict(os.environ, {'MATSUGIT_CONFIG': str(self.global_file)})
        self.env.start(); self.addCleanup(self.env.stop)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.source = self.repo / 'deck.md'
        self.source.write_text('---\ntitle: Demo\nslide-layout: structured\nslide-section-dividers: false\n---\n\n## Evidence\n### Smaller claim\n\n| Measure | Value |\n|---|---|\n| Retention | 92% |\n\n::: takeaway\nA useful conclusion.\n:::\n')

    def profile(self):
        return {'repo':str(self.root / 'target'), 'provider':'gitlab', 'theme':'work', 'site_dir':'static/decks'}

    def test_profile_precedence_and_preview_isolation(self):
        targets.configure('work', self.profile(), default=True)
        self.assertEqual(config(self.source, {'command':'publish'})['theme'], 'work')
        self.assertEqual(config(self.source, {'command':'render'})['repo'], self.repo)
        (self.repo / 'matsugit.json').write_text(json.dumps({'repo':'local', 'theme':'project'}))
        self.assertEqual(config(self.source, {'command':'publish'})['repo'], self.repo / 'local')
        explicit = config(self.source, {'command':'publish', 'target':'work', 'theme':'choice'})
        self.assertEqual(explicit['repo'], self.root / 'target')
        self.assertEqual(explicit['theme'], 'choice')

    def test_preserve_preferences_and_reject_bad_profiles(self):
        targets.save({'theme':'personal', 'export_directory':'/local/OneDrive'})
        targets.configure('work', self.profile())
        self.assertEqual(targets.settings()['export_directory'], '/local/OneDrive')
        for profile in ({'repo':'/x', 'provider':'other'}, {'repo':42, 'provider':'github'}):
            with self.assertRaises(Error): targets.configure('bad', profile)
        with self.assertRaises(Error): targets.configure('../bad', self.profile())

    def test_config_symlink_not_replaced(self):
        other = self.root / 'original.json'; other.write_text('{}')
        self.global_file.symlink_to(other)
        with self.assertRaises(Error): targets.save({'theme':'new'})
        self.assertEqual(other.read_text(), '{}')

    def git_repo(self):
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'add', 'deck.md')
        git(self.repo, 'commit', '-m', 'Synthetic')
        git(self.repo, 'remote', 'add', 'origin', 'https://gitlab.example.invalid/team/docs.git')

    def test_plan_is_read_only_and_fingerprint_changes(self):
        self.git_repo()
        settings = config(self.source)
        before = git(self.repo, 'rev-parse', 'HEAD')
        first = targets.plan(settings)
        self.assertEqual(first['provider'], 'gitlab')
        second = targets.plan(dict(settings, theme='another'))
        self.assertNotEqual(first['fingerprint'], second['fingerprint'])
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), before)
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        self.source.write_text('changed')
        with self.assertRaisesRegex(Error, 'local changes'): targets.plan(settings)

    def test_plan_rejects_unowned_index(self):
        self.git_repo()
        site = self.repo / 'matsugit-site'; site.mkdir()
        (site / 'index.html').write_text('ours')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Existing site')
        with self.assertRaisesRegex(Error, 'unowned'): targets.plan(config(self.source))

    @staticmethod
    def fake_render(settings, output, **kwargs):
        output.mkdir()
        for name in ('index.html', 'slides.html', 'source.md'):
            (output / name).write_text(kwargs.get('source_text') or 'synthetic')

    def test_exports_are_exclusive_and_keep_original(self):
        dest = self.root / 'slides.html'; original = self.source.read_text()
        with patch.object(exports, 'render', side_effect=self.fake_render):
            exports.export_file(config(self.source), 'html', dest, source_text='unsaved snapshot')
            self.assertEqual(dest.read_text(), 'unsaved snapshot')
            with self.assertRaisesRegex(Error, 'already exists'):
                exports.export_file(config(self.source), 'html', dest)
        self.assertEqual(self.source.read_text(), original)

    def test_sync_folder_keeps_previous_version_no_api(self):
        folder = self.root / 'OneDrive'; folder.mkdir()
        targets.save({'export_directory':str(folder)})
        with patch.object(exports, 'render', side_effect=self.fake_render):
            first = exports.export_file(config(self.source), 'zip', sync_folder=True)
            second = exports.export_file(config(self.source), 'zip', sync_folder=True)
        self.assertNotEqual(first['path'], second['path'])
        self.assertIn('not verified', first['sync'])
        with zipfile.ZipFile(first['path']) as archive:
            self.assertEqual(set(archive.namelist()), {'slides.html','index.html','source.md'})

    def test_missing_sync_folder_and_unknown_format(self):
        with self.assertRaisesRegex(Error, 'Configure an existing folder'):
            exports.export_file(config(self.source), 'pptx', sync_folder=True)
        with self.assertRaises(Error): exports.export_file(config(self.source), 'exe')

    def test_worker_requires_saved_source_and_fresh_plan(self):
        self.git_repo()
        spec = importlib.util.spec_from_file_location('delivery_worker', ROOT / 'codex-plugin/actions.py')
        worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
        request = {'action':'plan', 'path':str(self.source), 'text':self.source.read_text()}
        plan = worker.main(request)
        with patch.object(worker, 'publish') as publish:
            with self.assertRaisesRegex(Error, 'Save the current draft'):
                worker.main(dict(request, action='publish', text='unsaved', fingerprint=plan['fingerprint']))
            with self.assertRaisesRegex(Error, 'changed since confirmation'):
                worker.main(dict(request, action='publish', fingerprint='wrong'))
            publish.assert_not_called()

    @unittest.skipUnless(QUARTO, 'Set QUARTO for real PowerPoint export')
    def test_pptx_native_text_tables_unicode_org_parity(self):
        text = self.source.read_text() + '\n\n## Unicode\n\nCaf\u00e9, \u05e9\u05dc\u05d5\u05dd, 50% & <safe>.\n'
        self.source.write_text(text)
        for fmt in ('markdown', 'org'):
            source = self.source
            if fmt == 'org':
                source = self.repo / 'deck.org'
                source.write_text(convert(text, 'markdown', 'org', [QUARTO, 'pandoc']))
            output = self.root / (fmt + '.pptx')
            exports.export_file(config(source, {'quarto':QUARTO}), 'pptx', output)
            with zipfile.ZipFile(output) as archive:
                slides = [archive.read(name) for name in archive.namelist() if name.startswith('ppt/slides/slide') and name.endswith('.xml')]
                xml = b''.join(slides).decode()
                for expected in ('Evidence','Smaller claim','Retention','92%','A useful conclusion.','Caf\u00e9','\u05e9\u05dc\u05d5\u05dd'):
                    self.assertIn(expected, xml)
                self.assertIn('<a:tbl>', xml)
                for slide in slides: ET.fromstring(slide)
                self.assertIn(b'screen16x9', archive.read('ppt/presentation.xml'))

    @unittest.skipUnless(QUARTO and os.environ.get('MATSUGIT_EXPORT_PYTHON'), 'Set browser export environment')
    def test_mermaid_export_is_a_picture_not_code(self):
        self.source.write_text('---\nslide-layout: structured\n---\n## Flow\n\n```mermaid\nflowchart LR\n A[Evidence] --> B[Decision]\n```\n')
        output = self.root / 'diagram.pptx'
        exports.export_file(config(self.source, {'quarto':QUARTO}), 'pptx', output)
        with zipfile.ZipFile(output) as archive:
            self.assertTrue(any(name.startswith('ppt/media/') for name in archive.namelist()))
            xml = archive.read('ppt/slides/slide1.xml').decode()
            self.assertNotIn('flowchart', xml)


if __name__ == '__main__': unittest.main()
