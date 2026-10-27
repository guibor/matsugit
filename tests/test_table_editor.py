import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from folioforge.core import Error
from folioforge.converter import converter
from folioforge.table_editor import TableDocument, TableHTML, signature, validate

SIMPLE = "| Name | Value |\n| --- | --- |\n| **Alpha** | 12 |\n"
MERGED = '<table><tr><th colspan="2">Group</th><th>Total</th></tr><tr><td rowspan="2">North</td><td>Alpha</td><td>12</td></tr><tr><td>Beta</td><td>18</td></tr></table>'
try:
    COMMAND = converter()
except Error:
    COMMAND = None


class ValidationTests(unittest.TestCase):
    def test_active_html_and_unknown_formatting_are_refused(self):
        for html in ('<script>alert(1)</script>', '<td onclick="bad()">x</td>',
                     '<a href="javascript:bad()">x</a>', '<td style="color:red">x</td>',
                     '<img src="https://example.invalid/tracker">'):
            with self.assertRaises(Error):
                TableHTML().feed(html)

    def test_old_pandoc_is_not_accepted(self):
        result = subprocess.CompletedProcess([], 0, "pandoc 3.6.3\n", "")
        with patch("folioforge.converter.subprocess.run", return_value=result):
            with self.assertRaisesRegex(Error, "setup-editor"):
                converter()


@unittest.skipUnless(COMMAND, "Requires span-aware Pandoc (folioforge setup-editor)")
class RoundtripTests(unittest.TestCase):
    def test_simple_table_stays_pipe_markdown(self):
        table = TableDocument(SIMPLE, COMMAND)
        result = table.serialize(table.html)
        self.assertEqual(result["format"], "pipe")
        self.assertIn("**Alpha**", result["markdown"])
        self.assertNotIn("<table", result["markdown"])

    def test_merged_cells_use_readable_grid_without_html(self):
        table = TableDocument(SIMPLE, COMMAND)
        result = table.serialize(MERGED)
        self.assertEqual(result["format"], "grid")
        self.assertTrue(result["markdown"].startswith("+"))
        self.assertNotIn("<", result["markdown"])
        again = TableDocument(result["markdown"], COMMAND)
        self.assertIn('rowspan="2"', again.html)
        self.assertIn('colspan="2"', again.html)

    def test_unicode_links_formatting_and_literal_pipe_survive(self):
        source = '| Name | More |\n| --- | --- |\n| שלום **bold** *em* ~~old~~ | [link](https://example.invalid/a) `x\\|y` |\n'
        table = TableDocument(source, COMMAND)
        result = table.serialize(table.html)
        again = TableDocument(result["markdown"], COMMAND)
        self.assertEqual(signature(table.table), signature(again.table))

    def test_multiline_and_list_cells_use_grid(self):
        table = TableDocument(SIMPLE, COMMAND)
        result = table.serialize('<table><tr><th>Name</th><th>More</th></tr><tr><td><p>Alpha</p><p>Beta</p></td><td><ul><li>One</li><li>Two</li></ul></td></tr></table>')
        self.assertEqual(result["format"], "grid")
        self.assertNotIn("<table", result["markdown"])
        self.assertIn("One", result["markdown"])

    def test_multiple_tables_prose_code_images_and_math_refuse_without_loss(self):
        for source in (SIMPLE + "\nprose\n", SIMPLE + "\n" + SIMPLE,
                       "```md\n" + SIMPLE + "```\n",
                       SIMPLE.replace("**Alpha**", "![image](x.png)"),
                       SIMPLE.replace("**Alpha**", "$x^2$")):
            with self.subTest(source=source):
                with self.assertRaises(Error):
                    TableDocument(source, COMMAND)

    def test_no_header_and_merged_body_roundtrip(self):
        table = TableDocument(SIMPLE, COMMAND)
        result = table.serialize('<table><tr><td rowspan="2">North</td><td>A</td></tr><tr><td>B</td></tr></table>')
        self.assertEqual(result["format"], "grid")
        self.assertIn('rowspan="2"', TableDocument(result["markdown"], COMMAND).html)

    def test_import_check_detects_lost_formatting_and_paragraphs(self):
        table = TableDocument(SIMPLE, COMMAND)
        self.assertEqual(table.check_import(table.html), {'ok': True})
        with self.assertRaises(Error):
            table.check_import(table.html.replace('<strong>', '').replace('</strong>', ''))
        for bad in (None, [], 'x' * (1024 * 1024 + 1)):
            with self.assertRaises(Error):
                table.serialize(bad)

    def test_larger_table_roundtrip_and_limits(self):
        source = '| Name | Value |\n| --- | --- |\n' + ''.join(f'| [Item {i}](https://example.invalid/{i}) | {i} |\n' for i in range(200))
        table = TableDocument(source, COMMAND)
        result = table.serialize(table.html)
        self.assertEqual(result['rows'], 201)
        with self.assertRaisesRegex(Error, '500 rows'):
            TableDocument(SIMPLE + '| A | B |\n' * 501, COMMAND)

    def test_old_writer_output_fails_instead_of_flattening(self):
        table = TableDocument(SIMPLE, COMMAND)
        from folioforge.table_editor import convert as real_convert
        def flatten(command, text, reader, writer, *args):
            if reader == "json" and writer.startswith("markdown"):
                return SIMPLE
            return real_convert(command, text, reader, writer, *args)
        with patch("folioforge.table_editor.convert", side_effect=flatten):
            with self.assertRaisesRegex(Error, "would change"):
                table.serialize(MERGED)
