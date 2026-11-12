import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from matsugit import converter
from matsugit.core import Error


class PinnedConverterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'tools'

    def archive(self, system, arch, member=None):
        member = member or (f'pandoc-3.13/pandoc.exe' if system == 'Windows' else
                            f'pandoc-3.13-{arch}/bin/pandoc' if system == 'Darwin' else
                            'pandoc-3.13/bin/pandoc')
        output = io.BytesIO()
        data = b'synthetic binary; must never execute'
        if system == 'Linux':
            with tarfile.open(fileobj=output, mode='w:gz') as archive:
                item = tarfile.TarInfo(member)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        else:
            with zipfile.ZipFile(output, 'w') as archive:
                archive.writestr(member, data)
        return output.getvalue()

    def install(self, system='Linux', arch='x86_64', payload=None, expected=None, version='3.13'):
        key = system, 'amd64' if arch == 'x86_64' else arch
        name, _ = converter.PINNED_ASSETS[key]
        payload = payload if payload is not None else self.archive(system, arch)
        with patch.object(converter, 'tools_dir', return_value=self.root), \
             patch.object(converter, 'converter', side_effect=[Error('missing'), ['approved']]), \
             patch.object(converter.platform, 'system', return_value=system), \
             patch.object(converter.platform, 'machine', return_value=arch), \
             patch.dict(converter.PINNED_ASSETS, {key: (name, expected or hashlib.sha256(payload).hexdigest())}), \
             patch.object(converter.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as download, \
             patch.object(converter.subprocess, 'run', return_value=
                          subprocess.CompletedProcess([], 0, f'pandoc {version}\n')) as execute:
            self.download, self.execute = download, execute
            converter.install_converter()
            download.assert_called_once_with(
                f'https://github.com/jgm/pandoc/releases/download/3.13/{name}', timeout=30)
            execute.assert_called_once()

    def test_all_five_platforms_have_exact_offline_pins(self):
        self.assertEqual(converter.PINNED_VERSION, '3.13')
        self.assertEqual(len(converter.PINNED_ASSETS), 5)
        for (system, arch), (name, digest) in converter.PINNED_ASSETS.items():
            with self.subTest(system=system, arch=arch):
                self.assertRegex(digest, r'\A[0-9a-f]{64}\Z')
                self.assertTrue(name.startswith('pandoc-3.13-'))
                self.install(system, 'x86_64' if arch == 'amd64' else arch)
                receipt = json.loads((self.root / 'pandoc-install.json').read_text())
                self.assertEqual(receipt['version'], '3.13')
                self.assertEqual(receipt['asset'], name)

    def test_changed_asset_is_rejected_before_execution(self):
        with self.assertRaisesRegex(Error, 'checksum mismatch'):
            self.install(expected='0' * 64)
        self.execute.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_metadata_response_cannot_choose_a_different_download(self):
        with self.assertRaisesRegex(Error, 'checksum mismatch'):
            self.install(payload=b'{"assets":[{"url":"https://untrusted.invalid/pandoc"}]}',
                         expected='0' * 64)
        self.download.assert_called_once()
        self.execute.assert_not_called()

    def test_unexpected_archive_member_is_not_extracted(self):
        with self.assertRaisesRegex(Error, 'archive layout'):
            self.install(payload=self.archive('Linux', 'x86_64', '../bin/pandoc'))
        self.execute.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_wrong_version_never_replaces_existing_managed_binary(self):
        self.root.mkdir()
        (self.root / 'pandoc').write_bytes(b'old approved binary')
        (self.root / 'pandoc-install.json').write_text('{}')
        with self.assertRaisesRegex(Error, 'version differs'):
            self.install(version='99.0')
        self.assertEqual((self.root / 'pandoc').read_bytes(), b'old approved binary')
        self.assertEqual((self.root / 'pandoc-install.json').read_text(), '{}')

    def test_existing_compatible_converter_needs_no_download(self):
        with patch.object(converter, 'converter', return_value=['approved-pandoc']), \
             patch.object(converter.urllib.request, 'urlopen') as download:
            converter.install_converter()
        download.assert_not_called()


    def test_unmanaged_binary_and_unsupported_platform_fail_before_network(self):
        self.root.mkdir()
        (self.root / 'pandoc').write_bytes(b'locally installed')
        with self.assertRaisesRegex(Error, 'unmanaged'):
            self.install()
        self.download.assert_not_called()
        with patch.object(converter, 'converter', side_effect=Error('missing')), \
             patch.object(converter.platform, 'system', return_value='Windows'), \
             patch.object(converter.platform, 'machine', return_value='arm64'), \
             patch.object(converter.urllib.request, 'urlopen') as download:
            with self.assertRaisesRegex(Error, 'Install Pandoc'):
                converter.install_converter()
        download.assert_not_called()


@unittest.skipUnless(os.environ.get('MATSUGIT_PINNED_ARCHIVE_DIR'), 'Opt-in downloaded Pandoc archive smoke test')
class RealConverterTests(unittest.TestCase):
    def test_verified_platform_binary_installs_and_converts(self):
        arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}[platform.machine().lower()]
        name, _ = converter.PINNED_ASSETS[platform.system(), arch]
        archive = Path(os.environ['MATSUGIT_PINNED_ARCHIVE_DIR']) / name
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ('pandoc.exe' if os.name == 'nt' else 'pandoc')
            with patch.object(converter, 'tools_dir', return_value=Path(directory)), \
                 patch.object(converter, 'converter', side_effect=[Error('isolated install'), [str(target)]]), \
                 patch.object(converter.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs: archive.open('rb')):
                converter.install_converter()
            html = converter.convert([str(target)], '| Item | Count |\n|---|---:|\n| Test | 3 |\n', 'markdown', 'html')
            self.assertIn('<table>', html)
            self.assertIn('Test', html)
