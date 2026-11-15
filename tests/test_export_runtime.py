import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from matsugit import exports
from matsugit.core import Error


class ExportRuntimeTests(unittest.TestCase):
    def test_missing_dependency_in_child_never_spawns_again(self):
        with patch.dict(os.environ, {'_MATSUGIT_EXPORT_REEXEC': '1'}), \
                patch.object(exports.importlib.util, 'find_spec', return_value=None), \
                patch.object(exports.subprocess, 'run') as run:
            with self.assertRaisesRegex(Error, 'setup-export'):
                exports.browser_artifacts(Path('/tmp/render'))
            run.assert_not_called()

    def test_fallback_marks_child_and_preserves_result(self):
        result = subprocess.CompletedProcess([], 0, '["diagram-0.png"]', '')
        with patch.dict(os.environ, {'_MATSUGIT_EXPORT_REEXEC': ''}), \
                patch.object(exports.importlib.util, 'find_spec', return_value=None), \
                patch.object(Path, 'is_file', return_value=True), \
                patch.object(exports.subprocess, 'run', return_value=result) as run:
            self.assertEqual(exports.browser_artifacts(Path('/tmp/render')), ['diagram-0.png'])
            self.assertEqual(run.call_args.kwargs['env']['_MATSUGIT_EXPORT_REEXEC'], '1')
            run.assert_called_once()

    def test_failed_fallback_is_not_retried(self):
        result = subprocess.CompletedProcess([], 1, '', 'repair required')
        with patch.dict(os.environ, {'_MATSUGIT_EXPORT_REEXEC': ''}), \
                patch.object(exports.importlib.util, 'find_spec', return_value=None), \
                patch.object(Path, 'is_file', return_value=True), \
                patch.object(exports.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(Error, 'repair required'):
                exports.browser_artifacts(Path('/tmp/render'))
            run.assert_called_once()

    def test_missing_environment_does_not_spawn(self):
        with patch.dict(os.environ, {'_MATSUGIT_EXPORT_REEXEC': ''}), \
                patch.object(exports.importlib.util, 'find_spec', return_value=None), \
                patch.object(Path, 'is_file', return_value=False), \
                patch.object(exports.subprocess, 'run') as run:
            with self.assertRaisesRegex(Error, 'setup-export'):
                exports.browser_artifacts(Path('/tmp/render'))
            run.assert_not_called()

    def test_setup_refreshes_existing_python_environment(self):
        with patch.object(Path, 'exists', return_value=True), \
                patch.object(exports.subprocess, 'run') as run:
            exports.setup()
            self.assertEqual(run.call_args_list[0].args[0][:4],
                             [sys.executable, '-m', 'venv', '--upgrade'])
            self.assertIn('--require-hashes', run.call_args_list[1].args[0])

    def test_setup_creates_absent_python_environment(self):
        with patch.object(Path, 'exists', return_value=False), \
                patch.object(exports.subprocess, 'run') as run:
            exports.setup()
            self.assertEqual(run.call_args_list[0].args[0][:3],
                             [sys.executable, '-m', 'venv'])
            self.assertNotIn('--upgrade', run.call_args_list[0].args[0])


if __name__ == '__main__':
    unittest.main()
