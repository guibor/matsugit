"""Synthetic media tests; no account, publishing or executable documents."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from folioforge.core import Error, config, diagram_fences, mermaid_block, normalize, render
from folioforge.publish import setup_ci

QUARTO = os.environ.get("QUARTO", shutil.which("quarto"))
FIXTURES = Path(__file__).parent / "fixtures"


class MediaTests(unittest.TestCase):
    def test_native_fence_inside_code_example_is_not_activated(self):
        example = '````markdown\n```{mermaid}\ngraph LR\nA-->B\n```\n````\n'
        self.assertEqual(diagram_fences(example), example)
        self.assertEqual(diagram_fences(example, render=True), example)

    def test_diagram_cell_rejects_local_file_and_execution_options(self):
        for option in ("file: /etc/passwd", "include: private.txt", "eval: true"):
            with self.assertRaises(Error):
                mermaid_block(["", ["mermaid"], []], "%%| " + option + "\ngraph LR\nA-->B")

    def test_cell_preserves_backticks_and_caption(self):
        cell = mermaid_block(["demo", ["mermaid", "media-half"], []],
                             '%%| fig-cap: A diagram\ngraph LR\nA["```"]-->B')
        self.assertEqual(cell["c"][0][0], "demo")
        self.assertIn("media-half", cell["c"][0][1])
        self.assertIn("````{mermaid}", cell["c"][1][0]["c"][1])

    def test_ci_contains_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "example.md"
            source.write_text("# Example")
            setup_ci(config(source), "github")
            for name in ("media.js", "media.css"):
                self.assertTrue((root / ".folioforge-ci/runtime" / name).is_file())


@unittest.skipUnless(QUARTO, "Set QUARTO for normalization and real render tests")
class MediaRenderTests(unittest.TestCase):
    def test_org_diagram_normalizes_without_executing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'test.org'
            source.write_text('#+title: Diagram\n* Flow\n#+begin_src mermaid\ngraph LR\nA-->B\n#+end_src\n')
            output = root / 'output'
            output.mkdir()
            normalize(config(source, {'quarto': QUARTO}), output)
            self.assertIn('```{mermaid}', (output / 'source.md').read_text())

    def test_normalizing_twice_keeps_one_wrapper_and_diagram_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            normalize(config(FIXTURES / "media.md", {"quarto": QUARTO}), first)
            normalize(config(first / "source.md", {"quarto": QUARTO}), second)
            before = (first / "source.md").read_text()
            after = (second / "source.md").read_text()
            self.assertEqual(before, after)
            self.assertEqual(before.count("{mermaid}"), 3)
            self.assertEqual(before.count(".ff-media"), 7)

    def test_rendered_diagrams_images_and_ordinary_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            render(config(FIXTURES / "media.md", {"quarto": QUARTO}), root)
            for name in ("index.html", "slides.html"):
                html = (root / name).read_text()
                self.assertIn('class="mermaid', html)
                self.assertIn("Do not execute document code", html)
                self.assertIn("ff-media", html)
                self.assertNotIn('src="runtime/', html)
                self.assertNotIn('href="runtime/', html)
            self.assertIn('"engine": "markdown"', (root / "_quarto.yml").read_text())
