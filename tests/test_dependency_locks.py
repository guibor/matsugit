import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from matsugit import charts, exports


class DependencyLockTests(unittest.TestCase):
    def test_every_optional_requirement_has_a_version_and_hash(self):
        root = Path(charts.__file__).parent / 'dependencies'
        for name in ('charts.txt', 'export.txt'):
            requirements = (root / name).read_text().replace('\\\n', '')
            count = 0
            for line in requirements.splitlines():
                if not line.strip() or line.lstrip().startswith('#'):
                    continue
                self.assertRegex(line, r'^[a-zA-Z0-9_.-]+==[0-9][^ ]*')
                self.assertRegex(line, r'--hash=sha256:[0-9a-f]{64}')
                self.assertNotIn('://', line)
                count += 1
            self.assertGreater(count, 1)

    def test_both_installers_require_hashes_and_binary_wheels(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, HOME=directory):
            for module in (charts, exports):
                with self.subTest(module=module.__name__), \
                     patch.object(module.shutil, 'which', return_value=None), \
                     patch.object(module.subprocess, 'run') as run:
                    module.setup()
                installs = [call.args[0] for call in run.call_args_list
                            if 'pip' in call.args[0] and 'install' in call.args[0]]
                self.assertEqual(len(installs), 1)
                self.assertIn('--require-hashes', installs[0])
                self.assertIn('--only-binary=:all:', installs[0])
                self.assertTrue(Path(installs[0][installs[0].index('-r') + 1]).is_file())


if __name__ == '__main__':
    unittest.main()
