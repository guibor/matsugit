"""`matsugit open`: the browser fallback starts privately and refuses bad input."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request

from matsugit.browser import open_in_browser
from matsugit.core import Error

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'codex-plugin/bundle/browser.mjs'


def status(url, headers=None):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10).status
    except urllib.error.HTTPError as error:
        with error:
            return error.code


class BrowserOpenTests(unittest.TestCase):
    def test_refuses_files_it_cannot_open_before_starting_anything(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch('subprocess.Popen') as popen:
            text = Path(directory) / 'notes.txt'
            text.write_text('hello')
            with self.assertRaisesRegex(Error, 'Markdown or Org'):
                open_in_browser(text, browser=False)
            with self.assertRaisesRegex(Error, 'No such file'):
                open_in_browser(Path(directory) / 'missing.md', browser=False)
            popen.assert_not_called()

    def test_without_node_says_what_to_install(self):
        with mock.patch('shutil.which', return_value=None), self.assertRaisesRegex(Error, 'Node 22'):
            open_in_browser(None, browser=False)

    @unittest.skipUnless(shutil.which('node') and BUNDLE.is_file(), 'needs Node and the built bundle')
    def test_serves_the_workspace_on_a_private_local_address(self):
        with tempfile.TemporaryDirectory() as directory:
            deck = Path(directory) / 'deck.md'
            deck.write_text('---\ntitle: Synthetic\n---\n\n## One\n\nText.\n')
            environment = {'MATSUGIT_RECOVERY_DIR': str(Path(directory) / 'recovery'),
                           'MATSUGIT_CONFIG': str(Path(directory) / 'absent.json')}
            with mock.patch.dict(os.environ, environment):
                data = open_in_browser(deck, browser=False)
            process = data.pop('process')
            try:
                self.assertEqual(data['path'], str(deck.resolve()))
                url = data['url']
                self.assertTrue(url.startswith('http://127.0.0.1:'), url)
                self.assertEqual(status(url), 200)
                self.assertEqual(status(url + 'app'), 200)
                origin = url.split('/', 3)
                self.assertEqual(status(f'{origin[0]}//{origin[2]}/'), 404)
                self.assertEqual(status(url, {'Host': 'attacker.example'}), 403)
                request = urllib.request.Request(url + 'rpc', method='POST', headers={'Content-Type': 'application/json'},
                    data=json.dumps({'method': 'tools/call', 'params': {'name': 'matsugit_check', 'arguments': {'text': '## A\n'}}}).encode())
                reply = json.loads(urllib.request.urlopen(request, timeout=30).read())
                self.assertEqual(reply['result']['structuredContent']['problems'], 0)
                # Only the workspace's own calls are relayed.
                request = urllib.request.Request(url + 'rpc', method='POST', headers={'Content-Type': 'application/json'},
                                                 data=b'{"method": "initialize", "params": {}}')
                self.assertEqual(json.loads(urllib.request.urlopen(request, timeout=30).read())['error']['code'], -32601)
                self.assertEqual(deck.read_text(), '---\ntitle: Synthetic\n---\n\n## One\n\nText.\n')
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stdout.close()


if __name__ == '__main__':
    unittest.main()
