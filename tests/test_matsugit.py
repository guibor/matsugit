import realtmp  # noqa: F401  (resolve the temporary directory before any test creates one)
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
from unittest.mock import patch

from matsugit.core import Error, ResourceHTML, config, expand_runtime, git, inside, normalize, read_json, render, run, write_json
from matsugit.publish import check_destination, identity, preflight, publish, setup_ci


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "test.md"
        self.source.write_text("# Synthetic\n\n## Example\n\nHello.\n")
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"MATSUGIT_CONFIG": str(self.root / "absent.json")}).start()

    def test_paths(self):
        for path in ("../secret", "/tmp/file", ".env", "a/.credentials", "."):
            with self.assertRaises(Error):
                inside(self.root, path)
        (self.root / "outside").symlink_to("/tmp")
        with self.assertRaises(Error):
            inside(self.root, "outside/file")

    def test_config_precedence(self):
        write_json(self.root / "matsugit.json", {"theme": "project", "repo": "site"})
        settings = config(self.source, {"theme": "explicit"})
        self.assertEqual(settings["theme"], "explicit")
        self.assertEqual(settings["repo"], self.root / "site")

    def test_html_table_is_kept_and_links_are_rewritten(self):
        parser = ResourceHTML(lambda value: "safe/" + value)
        parser.feed('<table><tr><td rowspan="2">A &amp; B</td></tr></table><img src="x.png">')
        output = "".join(parser.output)
        self.assertIn('rowspan="2"', output)
        self.assertIn('src="safe/x.png"', output)
        self.assertIn("A &amp; B", output)

    def test_active_html_rejected(self):
        for text in ('<SCRIPT src="x">', '<img onerror="bad()">', '<img srcset="x 1x">', '<style>bad</style>'):
            with self.assertRaises(Error):
                ResourceHTML(lambda value: value).feed(text)

    def test_identity_has_no_credentials(self):
        for origin in ("git@github.com:someone/docs.git", "https://github.com/someone/docs.git"):
            with patch("matsugit.publish.git", return_value=origin):
                self.assertEqual(identity(self.root, "origin"), ("github.com", "someone/docs", "https://github.com/someone/docs"))
        with patch("matsugit.publish.git", return_value="https://token@github.com/x/y.git"):
            with self.assertRaises(Error):
                identity(self.root, "origin")

    def test_ci_setup_is_opt_in_and_never_overwrites(self):
        settings = config(self.source)
        setup_ci(settings, "github")
        self.assertTrue((self.root / ".matsugit-ci/sugar.py").is_file())
        for name in ('math-config.js', 'mathjax-tex-svg.js', 'MATHJAX-LICENSE'):
            self.assertTrue((self.root / '.matsugit-ci/runtime' / name).is_file())
        workflow = (self.root / ".github/workflows/matsugit-pages.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertNotIn("__SITE_DIR__", workflow)
        with self.assertRaisesRegex(Error, "overwrite"):
            setup_ci(settings, "github")

    def test_unowned_destination_refused(self):
        target = self.root / "existing"
        target.mkdir()
        with self.assertRaisesRegex(Error, "unowned"):
            check_destination(target, self.source)

    def test_ci_setup_from_expanded_plugin_runtime(self):
        import matsugit.publish as publishing
        package = self.root / 'snapshot/matsugit'
        shutil.copytree(Path(publishing.__file__).parent, package,
                        ignore=shutil.ignore_patterns('__pycache__'))
        expand_runtime(package / 'runtime')
        self.assertFalse((package / 'runtime/mathjax-tex-svg.js.gz').exists())
        for provider in ('github', 'gitlab'):
            with self.subTest(provider=provider):
                repo = self.root / provider
                repo.mkdir()
                with patch.object(publishing, '__file__', str(package / 'publish.py')):
                    setup_ci(config(self.source, {'repo': str(repo)}), provider)
                self.assertEqual((repo / '.matsugit-ci/runtime/mathjax-tex-svg.js').read_bytes(),
                                 (package / 'runtime/mathjax-tex-svg.js').read_bytes())


QUARTO = os.environ.get("QUARTO", shutil.which("quarto"))


@unittest.skipUnless(QUARTO, "Set QUARTO for real rendering tests")
class RenderTests(CoreTests):
    def test_unsaved_snapshot_keeps_original_and_relative_assets(self):
        original = self.source.read_text()
        (self.root / 'image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40"><rect width="80" height="40" fill="blue"/></svg>')
        draft = '---\ntitle: Unsaved\n---\n\n## Draft evidence\n\n![Local image](image.svg)\n'
        out = self.root / 'snapshot'
        render(config(self.source, {'quarto': QUARTO, 'theme': 'default'}), out, source_text=draft)
        self.assertEqual(self.source.read_text(), original)
        for name in ('index.html', 'slides.html'):
            html = (out / name).read_text()
            self.assertIn('Draft evidence', html)
            self.assertIn('data:image/svg+xml', html)
        self.assertIn('Unsaved', (out / 'source.md').read_text())

    def test_handout_keeps_theme_and_embedded_assets_after_cleanup(self):
        theme = self.root / 'themes/handout-test'
        theme.mkdir(parents=True)
        (theme / 'theme.json').write_text('{"document":"document.css","slides":"slides.scss"}')
        (theme / 'document.css').write_text(':root { --handout-theme-marker: #164c76; }')
        (theme / 'slides.scss').write_text('/*-- scss:defaults --*/\n$body-bg: #ffffff;\n')
        self.source.write_text('---\ntitle: Handout test\nslide-layout: structured\n---\n\n'
                               '## Evidence\n\n![](image.svg)\n\n::: notes\nPresenter detail.\n:::\n')
        (self.root / 'image.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40"><rect width="80" height="40"/></svg>')
        out = self.root / 'output'
        render(config(self.source, {'quarto': QUARTO, 'handout': True,
                                    'theme': 'handout-test', 'themes_dir': str(theme.parent)}), out)
        text = (out / 'handout.html').read_text()
        self.assertIn('--handout-theme-marker', text)
        self.assertIn('Presenter detail.', text)
        self.assertIn('ff-speaker-notes', text)
        assets = []
        class Resources(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                key = 'href' if tag == 'link' else 'src'
                if tag in ('script', 'link', 'img') and key in attrs:
                    assets.append(attrs[key])
        Resources().feed(text)
        self.assertTrue(assets)
        for ref in assets:
            url = urlsplit(ref)
            if not url.scheme and not url.netloc and url.path:
                self.assertTrue((out / unquote(url.path)).is_file(), ref)
        self.assertIn('handout.qmd', read_json(out / '_quarto.yml')['project']['render'])
        self.assertFalse((out / 'handout_files').exists())

    def test_merged_grid_table_is_not_flattened(self):
        self.source.write_text("+---------------+-------+\n| Area and team | Total |\n"
                               "+=======+=======+=======+\n| North | Alpha | 12    |\n"
                               "|       +-------+-------+\n|       | Beta  | 18    |\n"
                               "+-------+-------+-------+\n")
        out = self.root / "normalized"
        out.mkdir()
        normalize(config(self.source, {"quarto": QUARTO}), out)
        text = (out / "source.md").read_text()
        self.assertIn('rowspan="2"', text)
        self.assertIn('colspan="2"', text)

    def test_portable_ci_rebuild_retains_edit_link_and_web_changes(self):
        out = self.root / "matsugit-site/test"
        render(config(self.source, {"quarto": QUARTO}), out, edit_url="https://example.invalid/edit")
        with (out / "source.md").open("a") as stream:
            stream.write("\n## Web edit\n\nLatest revision from browser editor.\n")
        setup_ci(config(self.source), "github")
        run([os.sys.executable, ".matsugit-ci/build.py"], cwd=self.root)
        for name in ("index.html", "slides.html"):
            self.assertIn("Latest revision from browser editor", (out / name).read_text())
        self.assertIn('href="https://example.invalid/edit"', (out / "index.html").read_text())

    def test_real_html_and_slides_keep_spans_unicode_code_and_links(self):
        self.source.write_text('# Example\n\n## Merged\n\n<table><tr><th colspan="2">Pair</th></tr>'
                               '<tr><td rowspan="2">North</td><td>Alpha</td></tr>'
                               '<tr><td>Beta</td></tr></table>\n\n'
                               'שלום [label](https://example.invalid)\n\n```python\nx = "<tag>&"\n```\n', encoding="utf-8")
        out = self.root / "output"
        settings = config(self.source, {"quarto": QUARTO})
        render(settings, out, edit_url="https://example.invalid/edit")
        for file in ("index.html", "slides.html"):
            text = (out / file).read_text()
            for expected in ('rowspan="2"', 'colspan="2"', "שלום", "https://example.invalid", "North", "Beta"):
                self.assertIn(expected, text)
        self.assertIn('href="index.html"', (out / "slides.html").read_text())
        self.assertIn('href="slides.html"', (out / "index.html").read_text())
        self.assertTrue((out / "theme/theme.json").is_file())
        check_destination(out, self.source)
        (out / "source.md").write_text("# A web edit\n")
        with self.assertRaisesRegex(Error, "edited"):
            check_destination(out, self.source)

    def test_org_normalizes_to_editable_markdown(self):
        source = self.root / "test.org"
        source.write_text("#+title: Org title\n* Topic\n| Key | Value |\n|-----+-------|\n| x | 12 |\n", encoding="utf-8")
        out = self.root / "normalized"
        out.mkdir()
        normalize(config(source, {"quarto": QUARTO}), out)
        markdown = (out / "source.md").read_text()
        self.assertIn("Org title", markdown)
        self.assertIn("12", markdown)
        self.assertIn("Topic", markdown)

    def test_metadata_filters_not_propagated_and_hidden_resources_fail(self):
        self.source.write_text("---\nfilters: [evil.lua]\n---\n\n# Fine\n")
        out = self.root / "normalized"
        out.mkdir()
        normalize(config(self.source, {"quarto": QUARTO}), out)
        self.assertNotIn("evil.lua", (out / "source.md").read_text())
        self.source.write_text("![secret](.credentials.png)\n")
        with self.assertRaisesRegex(Error, "hidden"):
            normalize(config(self.source, {"quarto": QUARTO}), out)


class PublishTests(CoreTests):
    def setUp(self):
        super().setUp()
        self.remote = self.root / "remote.git"
        git(self.root, "init", "--bare", self.remote)
        self.repo = self.root / "checkout"
        git(self.root, "clone", self.remote, self.repo)
        git(self.repo, "checkout", "-b", "main")
        git(self.repo, "config", "user.name", "Synthetic Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / "README").write_text("unrelated\n")
        git(self.repo, "add", "README")
        git(self.repo, "commit", "-m", "Initialize")
        git(self.repo, "push", "-u", "origin", "main")
        self.settings = config(self.source, {"repo": str(self.repo)})

    def fake_render(self, settings, output, edit_url=None):
        output.mkdir()
        (output / "source.md").write_text("# Published\n")
        for name in ("index.html", "slides.html"):
            (output / name).write_text("synthetic")
        write_json(output / "matsugit-manifest.json", {
            "version": 1, "source_sha256": hashlib.sha256((output / "source.md").read_bytes()).hexdigest(),
            "files": ["source.md", "index.html", "slides.html"]})

    def test_local_remote_publication_is_scoped(self):
        with patch("matsugit.publish.identity", return_value=("github.com", "test/repo", "https://example.invalid/repo")), \
             patch("matsugit.publish.render", side_effect=self.fake_render):
            sha = publish(self.settings, confirmed=True)
        self.assertEqual(git(self.remote, "rev-parse", "main"), sha)
        self.assertEqual((self.repo / "README").read_text(), "unrelated\n")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_staged_work_refused(self):
        (self.repo / "README").write_text("user edit")
        git(self.repo, "add", "README")
        with self.assertRaisesRegex(Error, "local changes"):
            preflight(self.settings)
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only"), "README")
