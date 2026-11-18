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

    def test_external_workstation_note_is_a_label_not_a_published_asset(self):
        other = self.root / 'private-technical-note.md'
        other.write_text('PRIVATE NOTE BODY')
        self.source.write_text(f'## Brief\n\nSee [the *analysis*]({other.as_posix()}#details) and [online](https://example.invalid/notes).\n')
        original = self.source.read_bytes()
        reviewed = targets.plan(self.settings)
        source_ci.prepare(self.settings, self.root/'portable', reviewed)
        md = (self.root/'portable/source.md').read_text()
        self.assertIn('the *analysis*', md)
        self.assertIn('https://example.invalid/notes', md)
        self.assertNotIn(other.as_posix(), md)
        self.assertNotIn('PRIVATE NOTE BODY', md)
        self.assertFalse((self.root/'portable/assets').exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.source.write_text(f'![Private]({other.as_posix()})')
        with self.assertRaisesRegex(Error, 'outside the source project'):
            source_ci.prepare(self.settings, self.root/'blocked', targets.plan(self.settings))

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

    def test_topics_renderer_bytecode_does_not_block_or_enter_publication(self):
        scripts = self.repo / 'scripts'
        scripts.mkdir()
        entry = scripts / 'build_pages.py'
        entry.write_text('# existing renderer\n')
        git(self.repo, 'add', 'scripts')
        git(self.repo, 'commit', '-m', 'Existing topics renderer')
        remote = self.root / 'topics.git'
        git(self.root, 'init', '--bare', str(remote))
        git(self.repo, 'remote', 'set-url', 'origin', str(remote))
        git(self.repo, 'push', 'origin', 'main')
        settings = dict(self.settings, ci_layout='topics', source_dir='topics/decks')
        cache = self.repo / '.matsugit-renderer/scripts/matsugit_semantics/__pycache__/canvas.cpython-313.pyc'
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b'local cache')
        git(self.repo, 'config', 'core.excludesFile', os.devnull)
        self.assertIn(cache.name, git(self.repo, 'ls-files', '--others', '--exclude-standard'))
        self.source.write_text('## Brief\n\n[Supporting note](/Users/example/private/analysis.md)\n')
        with patch.object(source_ci, 'identity', return_value=('git.example.invalid', 'team/docs', 'https://git.example.invalid/team/docs')):
            sha = publish(settings, confirmed=True)
            self.assertEqual(git(remote, 'rev-parse', 'main'), sha)
            shared = git(remote, 'show', 'main:topics/decks/deck/source.md')
            self.assertIn('Supporting note', shared)
            self.assertNotIn('/Users/example/', shared)
            self.assertNotIn('.pyc', git(remote, 'ls-tree', '-r', '--name-only', sha))
            self.assertEqual(cache.read_bytes(), b'local cache')
            entry.write_text('# unpublished renderer edit\n')
            with self.assertRaisesRegex(Error, 'build_pages.py'):
                source_ci.plan(settings)
            entry.write_text('# existing renderer\n')
            extra = cache.with_suffix('.py')
            extra.touch()
            with self.assertRaisesRegex(Error, 'canvas.cpython-313.py'):
                source_ci.plan(settings)
            extra.unlink()
            git(self.repo, 'add', '-f', str(cache))
            with self.assertRaisesRegex(Error, 'canvas.cpython-313.pyc'):
                source_ci.plan(settings)

    def test_publish_local_remote_source_only_and_repeat_is_noop(self):
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        git(self.repo, 'remote', 'set-url', 'origin', str(remote))
        git(self.repo, 'push', 'origin', 'main')
        before = (self.repo / 'matsugit.gitlab-ci.yml').read_bytes()
        (self.repo/'unrelated.md').write_text('Unpublished draft')
        git(self.repo, 'add', 'unrelated.md')
        (self.repo/'unrelated.md').write_text('Newer unpublished draft')
        (self.repo/'scratch').write_text('Keep me')
        dirty = git(self.repo, 'status', '--porcelain')
        with patch.object(source_ci, 'identity', return_value=('git.example.invalid', 'team/docs', 'https://git.example.invalid/team/docs')):
            sha = publish(self.settings, confirmed=True)
            self.assertEqual(sha, publish(self.settings, confirmed=True))
        self.assertEqual(git(remote, 'rev-parse', 'refs/heads/main'), sha)
        changed = git(self.repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', sha).splitlines()
        self.assertTrue(all(p.startswith('matsugit-site/deck/') for p in changed))
        self.assertFalse(any(p.endswith('.html') for p in changed))
        self.assertEqual(before, (self.repo / 'matsugit.gitlab-ci.yml').read_bytes())
        self.assertEqual(git(self.repo, 'status', '--porcelain'), dirty)
        self.assertEqual(git(self.repo, 'show', ':unrelated.md'), 'Unpublished draft')
        self.assertEqual((self.repo/'unrelated.md').read_text(), 'Newer unpublished draft')
        target = self.repo/'matsugit-site/deck/source.md'
        target.write_text('An edit to the actual destination')
        with patch.object(source_ci, 'identity', return_value=('git.example.invalid','team/docs','https://git.example.invalid/team/docs')):
            with self.assertRaisesRegex(Error, 'local changes'):
                publish(self.settings, confirmed=True)
        self.assertEqual(target.read_text(), 'An edit to the actual destination')

    def test_remote_change_to_destination_refused_before_fast_forward(self):
        # Two real commits with the second one available only on the remote.
        remote = self.root/'upstream.git'
        git(self.root, 'init', '--bare', str(remote))
        git(self.repo, 'remote', 'set-url', 'origin', str(remote))
        git(self.repo, 'push', 'origin', 'main')
        author = self.root/'other-checkout'
        git(self.root, 'clone', '-b', 'main', str(remote), str(author))
        path = author/'matsugit-site/deck/source.md'
        path.parent.mkdir(parents=True)
        path.write_text('Someone else published here')
        git(author, 'add', '.')
        git(author, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost', 'commit', '-m', 'Remote change')
        git(author, 'push', 'origin', 'main')
        before = git(self.repo, 'rev-parse', 'HEAD')
        with patch.object(source_ci, 'identity', return_value=('git.example.invalid','team/docs','https://git.example.invalid/team/docs')):
            with self.assertRaisesRegex(Error, 'remote changed'):
                publish(self.settings, confirmed=True)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), before)
        self.assertEqual(git(remote, 'show', 'main:matsugit-site/deck/source.md'), path.read_text())

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
                html = (self.repo / '.matsugit-ci/site' / fmt / name).read_text()
                self.assertIn('Caf\u00e9', html)
                self.assertIn('Evidence', html)
                self.assertTrue('data:image/svg+xml' in html, f'{fmt}/{name}: missing embedded evidence image')


if __name__ == '__main__': unittest.main()
