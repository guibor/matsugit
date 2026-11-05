import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from copy import deepcopy

from matsugit.source import visible_sources, visible_notes, read
from matsugit.layout import metadata, plain
from matsugit.core import config, normalize, render
from matsugit.preview import pandoc_command, annotate

QUARTO = os.environ.get('QUARTO', shutil.which('quarto'))


class SourceVisibilityTests(unittest.TestCase):
    def test_notes_filter_only_removes_semantic_blocks_without_mutation(self):
        note = {'t':'Div','c':[['',['notes'],[]],[{'t':'Para','c':[{'t':'Str','c':'Presenter'}]}]]}
        literal = {'t':'CodeBlock','c':[['',[],[]],'::: notes\nExample\n:::']}
        ast = {'meta':{},'blocks':[note,literal,{'t':'Div','c':[['',['notebook'],[]],[]]}]}
        original = deepcopy(ast)
        self.assertEqual(visible_notes(ast)['blocks'], ast['blocks'][1:])
        self.assertEqual(ast,original)
        ast['meta']['include-notes'] = {'t':'MetaBool','c':True}
        self.assertEqual(visible_notes(ast),ast)

    def test_only_exact_semantic_divs_are_removed(self):
        source = {'t':'Div','c':[['',['source'],[]],[{'t':'Para','c':[{'t':'Str','c':'hidden'}]}]]}
        examples = [{'t':'CodeBlock','c':[['',[],[]], '::: source\nliteral\n:::']},
                    {'t':'Header','c':[2,['sources',[],[]],[{'t':'Str','c':'Sources'}]]},
                    {'t':'Div','c':[['',['attribution'],[]],[]]},
                    {'t':'Div','c':[['',['sourcebook'],[]],[]]}]
        ast = {'meta':{}, 'blocks':[source, *examples, {'t':'BlockQuote','c':[source]}]}
        original = deepcopy(ast)
        clean = visible_sources(ast)
        self.assertEqual(clean['blocks'], [*examples, {'t':'BlockQuote','c':[]}])
        self.assertEqual(ast, original)
        ast['meta']['publish-sources'] = {'t':'MetaBool','c':True}
        self.assertEqual(visible_sources(ast), ast)
        with self.assertRaisesRegex(ValueError, 'true or false'):
            metadata({'publish-sources': {'t':'MetaString','c':'false'}})


@unittest.skipUnless(QUARTO, 'Requires Quarto/Pandoc')
class SourceVisibilityParserTests(unittest.TestCase):
    def test_markdown_org_parity_and_assets_are_filtered_before_resolution(self):
        for fmt, source in [('markdown', '---\npublish-sources: false\n---\n\n## Sources\n\n::: source\nPRIVATE_SENTINEL ![](missing.png)\n:::\n\n::: attribution\nVisible Author\n:::\n'),
                            ('org', '#+PUBLISH_SOURCES: false\n\n* Sources\n\n#+begin_source\nPRIVATE_SENTINEL [[file:missing.png]]\n#+end_source\n\n#+begin_attribution\nVisible Author\n#+end_attribution\n')]:
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                file = root / ('deck.org' if fmt == 'org' else 'deck.md')
                file.write_text(source)
                out = root / 'out'
                out.mkdir()
                ast = normalize(config(file, {'quarto':QUARTO, '_preview_pandoc':pandoc_command(QUARTO)}), out)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(ast))
                self.assertNotIn('PRIVATE', plain(ast['blocks']))
                self.assertIn('Visible Author', plain(ast['blocks']))
                self.assertIn('Sources', json.dumps(ast))
                self.assertEqual(file.read_text(), source)
                visible = read(source.replace('false','true').replace(' ![](missing.png)','').replace(' [[file:missing.png]]',''), fmt, pandoc_command(QUARTO))
                self.assertIn('PRIVATESENTINEL' if fmt == 'org' else 'PRIVATE_SENTINEL', plain(visible_sources(visible)['blocks']))
                self.assertNotEqual(annotate(visible)[1]['shape'], annotate(ast)[1]['shape'])

    @unittest.skipUnless(os.environ.get('MATSUGIT_VISIBILITY_RENDER'), 'Opt-in full HTML regression')
    def test_real_document_and_slides(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'deck.md'
            text = '---\ntitle: Visibility\nslide-layout: structured\npublish-sources: %s\n---\n\n## Evidence\n\nVisible evidence\n\n::: source\nPRIVATE_SENTINEL\n:::\n\n::: attribution\nVisible Author\n:::\n'
            for flag in ('false', 'true'):
                file.write_text(text % flag)
                out = root / flag
                render(config(file, {'quarto':QUARTO, 'theme':'default', 'themes_dir':str(root/'themes')}), out)
                for name in ('index.html','slides.html'):
                    html = (out/name).read_text()
                    self.assertEqual('PRIVATE_SENTINEL' in html, flag == 'true')
                    self.assertIn('Visible Author', html)


if __name__ == '__main__':
    unittest.main()
