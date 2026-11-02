import unittest
from folioforge.converter import converter
from folioforge.core import Error
from folioforge.source import read, convert
from folioforge.sugar import markdown, ratios
from folioforge.layout import plain, slides

try:
    COMMAND = converter()
except Error:
    COMMAND = None

SAMPLE = '''---
title: Synthetic
slide-layout: structured
---
## Title
### Claim

:::: columns 2:1
#### Evidence
| Item | Value |
|---|---:|
| A | 12 |

#### Implication
Keep **meaning**, [links](https://example.invalid) and Unicode: שלום.
::::

> [!TAKEAWAY]
> Act on the evidence.
>
> Keep the caveat.
'''


class SugarLexicalTests(unittest.TestCase):
    def test_expands_only_openers_and_preserves_lines(self):
        for ending in ('\n', '\r\n', ''):
            self.assertEqual(markdown('::: columns 2:1' + ending),
                             '::: {.columns ratio="2:1"}' + ending)
        self.assertEqual(len(SAMPLE.splitlines()), len(markdown(SAMPLE).splitlines()))

    def test_examples_metadata_html_comments_and_indentation_stay_literal(self):
        examples = ['```md\n::: columns 2:1\n```', '~~~~\n::: columns 2:1\n~~~~',
                    '    ::: columns 2:1', '> ::: columns 2:1',
                    '---\nexample: |\n  ::: columns 2:1\n---\n',
                    '<!--\n::: columns 2:1\n-->', '<div>\n::: columns 2:1\n</div>',
                    '<script>\n\n::: columns 2:1\n</script>',
                    ':::: agent-comment\n::: columns invalid\n:::\n::::',
                    'text ::: columns 2:1']
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(markdown(example), example)

    def test_invalid_ratios(self):
        for value in ('0:1', '1:-1', 'nan:1', '1', '1:2:3:4', '99999:1', '1:1;rm'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ratios(value)


@unittest.skipUnless(COMMAND, 'Requires Pandoc')
class SugarSemanticsTests(unittest.TestCase):
    def test_matches_explicit_columns_and_takeaway(self):
        explicit = SAMPLE.replace(':::: columns 2:1\n#### Evidence',
                                  ':::: columns\n::: {.column width="66.6667%"}\n#### Evidence')
        explicit = explicit.replace('#### Implication', ':::\n::: {.column width="33.3333%"}\n#### Implication')
        explicit = explicit.replace('\n::::\n', '\n:::\n::::\n')
        explicit = explicit.replace('> [!TAKEAWAY]\n> Act on the evidence.\n>\n> Keep the caveat.',
                                    '::: takeaway\nAct on the evidence.\n\nKeep the caveat.\n:::')
        self.assertEqual(read(SAMPLE, 'markdown', COMMAND), read(explicit, 'markdown', COMMAND))

    def test_org_roundtrip_and_native_ratio(self):
        before = read(SAMPLE, 'markdown', COMMAND)
        org = convert(SAMPLE, 'markdown', 'org', COMMAND)
        self.assertIn('#+begin_takeaway', org)
        after = read(org, 'org', COMMAND)
        self.assertEqual(plain(slides(before)), plain(slides(after)))
        native = '#+begin_columns :ratio "2:1"\n#+begin_region :title "A"\nOne\n#+end_region\n#+begin_region :title "B"\nTwo\n#+end_region\n#+end_columns'
        ast = read(native, 'org', COMMAND)
        self.assertEqual(dict(ast['blocks'][0]['c'][1][0]['c'][0][2])['width'], '66.6667%')

    def test_invalid_count_conflicting_width_and_empty_takeaway(self):
        for source in (SAMPLE.replace('2:1', '1:1:1'),
                       '::: {.columns ratio="2:1"}\n::: {.column width="50%"}\nA\n:::\n::: column\nB\n:::\n:::',
                       '> [!TAKEAWAY]\n'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                read(source, 'markdown', COMMAND)

    def test_unknown_callouts_inline_marker_and_code_stay_unchanged(self):
        for source in ('> [!NOTE]\n> Normal note.', '> [!TAKEAWAY] inline text',
                       '```text\n> [!TAKEAWAY]\n> Example\n```'):
            ast = read(source, 'markdown', COMMAND)
            self.assertNotEqual(ast['blocks'][0]['t'], 'Div')

    def test_many_slides_keep_all_content(self):
        ast = read('\n\n'.join(SAMPLE.split('---', 2)[-1] for _ in range(150)), 'markdown', COMMAND)
        self.assertEqual(sum(b['t'] == 'Div' and 'takeaway' in b['c'][0][1] for b in ast['blocks']), 150)


if __name__ == '__main__':
    unittest.main()
