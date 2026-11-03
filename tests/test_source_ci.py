import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from matsugit.core import config, git, Error
from matsugit.publish import setup_ci, publish
from matsugit import source_ci, targets
from matsugit.converter import converter
from matsugit.source import convert


class SourceCITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.source = self.root / 'deck.md'
        self.source.write_text('---\ntitle: Demo\nslide-layout: structured\n---\n\n## Evidence\n### Claim\n\n| Item | Value |\n|---|---|\n| Caf\u00e9 | 42 |\n\n```text\n<a>&code\n```\n\n![Evidence](figure.svg)\n')
        (self.root / 'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="blue"/></svg>')
        env = patch.dict(os.environ, {'MATSUGIT_CONFIG':str(self.root / 'empty.json')})
        env.start(); self.addCleanup(env.stop)
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'remote', 'add', 'origin', 'https://git.example.invalid/team/docs.git')
        self.settings = config(self.source, {'repo':str(self.repo), 'build':'ci'})
        setup_ci(self.settings, 'gitlab')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Install synthetic CI')

    def test_plan_is_source_only_and_nonmutating(self):
        first = targets.plan(self.settings)
        self.assertEqual(first['build'], 'ci')
        self.assertEqual(first['directory'], 'matsugit-site/deck')
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        changed = targets.plan(dict(self.settings, theme='another'))
        self.assertNotEqual(first['fingerprint'], changed['fingerprint'])

    def test_missing_ci_and_unsafe_source_directory(self):
        (self.repo / '.matsugit-ci/build.py').unlink()
        with self.assertRaisesRegex(Error, 'not installed'): source_ci.layout(self.settings)
        with self.assertRaises(Error): source_ci.layout(dict(self.settings, ci_layout='topics', source_dir='../topics'))

    def test_prepare_markdown_org_assets_without_rendering(self):
        for fmt in ('markdown', 'org'):
            settings = self.settings
            if fmt == 'org':
                org = self.root / 'deck.org'
                org.write_text(convert(self.source.read_text(), 'markdown', 'org', converter()))
                settings = dict(settings, source=org)
            output = self.root / fmt
            with patch('matsugit.core.render', side_effect=AssertionError('Must not render locally')):
                source_ci.prepare(settings, output, targets.plan(settings))
            files = [p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()]
            self.assertFalse(any(p.endswith('.html') for p in files))
            self.assertIn('source.org' if fmt == 'org' else 'source.md', files)
            self.assertEqual(sum(p.endswith('.svg') for p in files), 1)
            self.assertIn('theme/theme.json', files)
            manifest = json.loads((output / source_ci.MANIFEST).read_text())
            self.assertNotIn(str(self.root), json.dumps(manifest))
            text = (output / manifest['source_file']).read_text()
            for expected in ('Evidence', 'Claim', 'Caf\u00e9', '<a>&code'): self.assertIn(expected, text)
            source_ci.check_destination(output, settings['source'])

    def test_canvas_requires_a_capable_ci_renderer(self):
        (self.root / 'visual.html').write_text('<h1>Illustrative evidence</h1>')
        self.source.write_text('## Evidence\n\n::: {.canvas src="visual.html" title="Evidence"}\n:::\n')
        reviewed = targets.plan(self.settings)
        source_ci.prepare(self.settings, self.root / 'canvas-current', reviewed)
        self.assertEqual(len(list((self.root / 'canvas-current/assets').glob('*.html'))), 1)
        (self.repo / '.matsugit-ci/canvas.py').unlink()
        before = git(self.repo, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(Error, 'predates HTML canvases'):
            source_ci.prepare(self.settings, self.root / 'canvas-old', reviewed)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), before)

    def test_topics_uses_existing_ci_and_does_not_ship_a_new_theme(self):
        scripts = self.repo / 'scripts'; scripts.mkdir()
        (scripts / 'build_pages.py').write_text('# existing renderer\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', 'Existing pipeline')
        settings = dict(self.settings, ci_layout='topics', source_dir='topics/decks')
        reviewed = targets.plan(settings)
        self.assertEqual(reviewed['directory'], 'topics/decks/deck')
        output = self.root / 'topics'
        source_ci.prepare(settings, output, reviewed)
        self.assertFalse((output / 'theme').exists())
        self.assertIn('existing target CI', reviewed['theme'])

    def test_reject_modified_assets_untracked_files_and_symlinks(self):
        output = self.root / 'output'
        source_ci.prepare(self.settings, output, targets.plan(self.settings))
        source = output / 'source.md'
        original = source.read_text(); source.write_text('Remote edits')
        with self.assertRaisesRegex(Error, 'edited'): source_ci.check_destination(output, self.source)
        source_ci.check_destination(output, source.resolve())
        source.write_text(original)
        extra = output / 'extra.txt'; extra.write_text('keep me')
        with self.assertRaises(Error): source_ci.check_destination(output, self.source)
        extra.unlink(); extra.symlink_to(self.source)
        with self.assertRaisesRegex(Error, 'symlink'): source_ci.check_destination(output, self.source)

    def test_publish_local_remote_source_only_and_repeat_is_noop(self):
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        git(self.repo, 'remote', 'set-url', 'origin', str(remote))
        git(self.repo, 'push', 'origin', 'main')
        before = (self.repo / 'matsugit.gitlab-ci.yml').read_bytes()
        with patch.object(source_ci, 'identity', return_value=('git.example.invalid', 'team/docs', 'https://git.example.invalid/team/docs')):
            sha = publish(self.settings, confirmed=True)
            self.assertEqual(sha, publish(self.settings, confirmed=True))
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/main'), sha)
        changed = git(self.repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', sha).splitlines()
        self.assertTrue(all(p.startswith('matsugit-site/deck/') for p in changed))
        self.assertFalse(any(p.endswith('.html') for p in changed))
        self.assertEqual(before, (self.repo / 'matsugit.gitlab-ci.yml').read_bytes())
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')

    @unittest.skipUnless(os.environ.get('QUARTO'), 'Set QUARTO to verify CI HTML rendering')
    def test_installed_ci_renders_document_and_slides(self):
        for fmt in ('markdown', 'org'):
            settings = dict(self.settings, slug=fmt)
            if fmt == 'org':
                org = self.root / 'deck.org'
                org.write_text(convert(self.source.read_text(), 'markdown', 'org', converter()))
                settings['source'] = org
            reviewed = targets.plan(settings)
            output = self.repo / reviewed['directory']; output.parent.mkdir(exist_ok=True)
            source_ci.prepare(settings, output, reviewed)
            git(self.repo, 'add', '.'); git(self.repo, 'commit', '-m', fmt)
        result = subprocess.run(['python3', '.matsugit-ci/build.py'], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for fmt in ('markdown', 'org'):
            for name in ('index.html', 'slides.html'):
                html = (self.repo / 'matsugit-site' / fmt / name).read_text()
                self.assertIn('Caf\u00e9', html)
                self.assertIn('Evidence', html)
                self.assertTrue('data:image/svg+xml' in html, f'{fmt}/{name}: missing embedded evidence image')


if __name__ == '__main__': unittest.main()
