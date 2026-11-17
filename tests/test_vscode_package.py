import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_vscode', ROOT / 'vscode-extension/package_vscode.py')
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


class VSCodePackageTests(unittest.TestCase):
    def test_allowlisted_portable_archive_and_separate_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'extension.vsix'
            pack.package(ROOT, output, name='matsugit-work', profile={'name':'matsugit-work','theme':'example'},
                         theme_files={'example/theme.json':b'{}'})
            first = output.read_bytes()
            pack.package(ROOT, output, name='matsugit-work', profile={'name':'matsugit-work','theme':'example'},
                         theme_files={'example/theme.json':b'{}'})
            self.assertEqual(first, output.read_bytes())
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertFalse(any('/tests/' in name or 'node_modules' in name for name in names))
                manifest = json.loads(archive.read('extension/package.json'))
                self.assertEqual(manifest['name'], 'matsugit-work')
                self.assertEqual(manifest['contributes']['commands'][0]['command'], 'matsugit-work.open')
                self.assertEqual(manifest['contributes']['customEditors'][0]['viewType'], 'matsugit-work.editor')
                self.assertIn('matsugit-work.nodePath', manifest['contributes']['configuration']['properties'])
                self.assertEqual(manifest['version'], json.loads((ROOT / 'plugin.json').read_text())['version'])
                self.assertEqual(archive.read('extension/runtime/server.mjs'), (ROOT / 'codex-plugin/bundle/server.mjs').read_bytes())
                ET.fromstring(archive.read('extension.vsixmanifest'))
                ET.fromstring(archive.read('[Content_Types].xml'))

    def test_unsafe_names_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'extension.vsix'
            for kwargs in ({'name':'../other'}, {'theme_files':{'../outside':b'bad'}}, {'version':'latest'}):
                with self.assertRaises(ValueError):
                    pack.package(ROOT, output, **kwargs)
                self.assertFalse(output.exists())

    def test_windows_cli_bypasses_cmd_shell(self):
        with tempfile.TemporaryDirectory(prefix='VS Code with spaces ') as temp:
            root = Path(temp)
            for name in ('bin/code.cmd','Code.exe','resources/app/out/cli.js'):
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('fixture')
            command, env = pack.code_command(str(root / 'bin/code.cmd'))
            self.assertEqual(command, [str(root / 'Code.exe'), str(root / 'resources/app/out/cli.js')])
            self.assertEqual(env['ELECTRON_RUN_AS_NODE'], '1')
            with self.assertRaisesRegex(ValueError, 'VS Code CLI'):
                pack.code_command(str(root / 'missing'))
