"""The repository, as committed, stays under 8 MB (8,000,000 bytes).

This guards the source tree, not downstream archives that add themes or review
evidence. When it fails, the message lists the largest files.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 8_000_000


@unittest.skipUnless(shutil.which('git') and (ROOT / '.git').exists(), 'Needs a Git checkout')
class PackageSizeTests(unittest.TestCase):
    def test_tracked_files_stay_under_eight_megabytes(self):
        names = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True).stdout.decode().split('\0')
        sizes = sorted(((ROOT / name).stat().st_size, name) for name in names if name and (ROOT / name).is_file())
        total = sum(size for size, _ in sizes)
        largest = '\n'.join(f'{size / 1e6:6.2f} MB  {name}' for size, name in sizes[-10:][::-1])
        self.assertLess(total, LIMIT, f'Tracked files total {total / 1e6:.2f} MB; the limit is {LIMIT / 1e6:.0f} MB. Largest:\n{largest}')

    def test_the_committed_server_carries_no_second_copy_of_the_page(self):
        self.assertFalse((ROOT / 'codex-plugin/bundle/app.html').exists(),
                         'The workspace page lives inside bundle/server.mjs; read it with codex-plugin/app-html.mjs')
        self.assertFalse((ROOT / 'codex-plugin/bundle/merge-worker.cjs').exists(),
                         'The merge worker is extracted from the same embedded runtime')


if __name__ == '__main__':
    unittest.main()
