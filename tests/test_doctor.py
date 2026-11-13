"""Read-only prerequisite diagnostics, independent of installed tools/accounts."""
import builtins
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from matsugit import authoring, charts, cli, converter, diagrams, doctor, exports


class DoctorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='doctor tests ')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.replace('os.environ', {'HOME': str(self.home), 'USERPROFILE': str(self.home),
                                   'PATH': ''}, dictionary=True, clear=True)
        self.replace('matsugit.doctor.ROOT', self.home / 'checkout')
        self.replace('matsugit.doctor.WINDOWS', False)
        self.replace('matsugit.doctor.shutil.which', side_effect=lambda name: name or None)
        self.probe = self.replace('matsugit.doctor._probe', side_effect=self.version_output)
        self.replace('matsugit.doctor.metadata.version', side_effect=doctor.metadata.PackageNotFoundError)
        self.replace('matsugit.doctor.importlib.util.find_spec', return_value=None)
        for target in ('subprocess.run', 'subprocess.Popen', 'urllib.request.urlopen',
                       'socket.create_connection', 'socket.socket',
                       'matsugit.converter.converter', 'matsugit.converter.install_converter',
                       'matsugit.charts.setup', 'matsugit.diagrams.setup', 'matsugit.exports.setup',
                       'matsugit.cli.config', 'matsugit.cli.render', 'matsugit.cli.publish'):
            self.replace(target, side_effect=AssertionError('Unexpected side effect: ' + target))

    def replace(self, target, *args, dictionary=False, **kwargs):
        mocked = (patch.dict if dictionary else patch)(target, *args, **kwargs)
        value = mocked.start()
        self.addCleanup(mocked.stop)
        return value

    @staticmethod
    def version_output(command):
        assert command[-1] == '--version', command
        if 'pandoc' in Path(command[0]).name or command[1:-1] == ['pandoc']:
            return 0, 'pandoc 3.7.0.2\n'
        return 0, {'git': 'git version 2.45.1.windows.1\n',
                   'node': 'v22.0.0\n', 'quarto': '1.6.42\n'}[Path(command[0]).name]

    def write(self, relative, text=''):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def distribution(self, root, name, version, windows=False):
        site = 'Lib/site-packages' if windows else 'lib/python3.10/site-packages'
        self.write(f'{root}/{site}/{name.replace("-", "_")}-{version}.dist-info/METADATA',
                   f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')

    def checks(self):
        return {check['id']: check for check in doctor.diagnose()['checks']}

    def assert_schema(self, data):
        self.assertEqual(data['schema'], 1)
        self.assertIs(type(data['ready']), bool)
        self.assertEqual([c['id'] for c in data['checks']], list(doctor.GROUPS))
        self.assertEqual({c['id'] for c in data['checks'] if c['required']},
                         {'python', 'git', 'node', 'quarto', 'converter'})
        for check in data['checks']:
            self.assertTrue(check['label'])
            self.assertIs(type(check['required']), bool)
            self.assertIsInstance(check['detail'], str)
            self.assertIn(check['status'], ('ready', 'missing', 'unsupported', 'error'))
            if check['status'] == 'ready':
                self.assertNotIn('remedy', check)
            else:
                self.assertTrue(check['remedy'])
        self.assertEqual(data['ready'], all(c['status'] == 'ready' for c in data['checks'] if c['required']))
        self.assertEqual(json.loads(json.dumps(data)), data)

    def test_core_ready_with_every_optional_requirement_missing(self):
        data = doctor.diagnose()
        self.assert_schema(data)
        self.assertTrue(data['ready'])
        self.assertTrue(all(c['status'] == 'missing' for c in data['checks'] if not c['required']))

    def test_each_required_failure_gates_readiness(self):
        original = doctor._version
        for id in ('git', 'node', 'quarto', 'converter'):
            for status in ('missing', 'unsupported', 'error'):
                with self.subTest(id=id, status=status):
                    def version(command, *args):
                        match = ('pandoc' in command[0] or 'pandoc' in command[1:]) if id == 'converter' else command == [id]
                        return {'status': status, 'detail': 'Synthetic failure.'} if match else original(command, *args)
                    with patch.object(doctor, '_version', side_effect=version):
                        data = doctor.diagnose()
                    self.assert_schema(data)
                    self.assertFalse(data['ready'])
                    self.assertEqual(next(c for c in data['checks'] if c['id'] == id)['status'], status)

    def test_python_minimum_uses_running_interpreter_without_starting_another(self):
        for version, status in (((3, 9, 99), 'unsupported'), ((3, 10, 0), 'ready'), ((3, 14, 0), 'ready')):
            with self.subTest(version=version), patch.object(sys, 'version_info', version):
                data = doctor.diagnose()
            self.assertEqual(data['checks'][0]['status'], status)
            self.assertEqual(data['ready'], status == 'ready')
        self.assertTrue(all('python' not in call.args[0][0] for call in self.probe.call_args_list))

    def test_cli_json_is_one_valid_document_with_correct_exit_code(self):
        for missing in (False, True):
            with self.subTest(missing=missing), patch.object(doctor.shutil, 'which',
                    side_effect=lambda name: None if missing else name):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = cli.main(['doctor', '--json'])
                data = json.loads(stdout.getvalue())
                self.assert_schema(data)
                self.assertEqual(data['ready'], not missing)
                self.assertEqual(result, int(missing))
                self.assertEqual(stderr.getvalue(), '')

    def test_plain_report_identifies_required_optional_remedies_and_limits(self):
        with patch.object(doctor.shutil, 'which', return_value=None), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['doctor']), 1)
        report = output.getvalue()
        for text in ('setup: not ready', '[missing] Git (required)', '(optional)',
                     'Next:', 'no installs, renders, network requests, logins, or config changes'):
            self.assertIn(text, report)
        self.assertIn('setup: ready', doctor.report(doctor.diagnose()))

    def test_local_inspection_failures_stay_in_json_and_optional_errors_do_not_gate(self):
        for method, id, required in (('_workspace', 'workspace', False), ('_charts', 'charts', False),
                                    ('_export', 'export', False), ('_d2', 'd2', False),
                                    ('_converter', 'converter', True)):
            for error in (PermissionError('private'), ValueError('malformed'), RuntimeError('symlink loop')):
                with self.subTest(method=method, error=error), patch.object(doctor, method, side_effect=error):
                    with redirect_stdout(io.StringIO()) as output:
                        code = cli.main(['doctor', '--json'])
                    data = json.loads(output.getvalue())
                    self.assert_schema(data)
                    self.assertEqual(data['ready'], not required)
                    self.assertEqual(code, int(required))
                    self.assertEqual(next(c for c in data['checks'] if c['id'] == id)['status'], 'error')

    def test_version_formats_minima_and_error_results(self):
        for output, pattern, minimum, status in (
            ('git version 2.45.1.windows.1\n', r'^git version (\d+(?:\.\d+)+)', (), 'ready'),
            ('v21.9.9\n', r'^v(\d+(?:\.\d+)+)', (22,), 'unsupported'),
            ('v22.0.0\r\n', r'^v(\d+(?:\.\d+)+)', (22,), 'ready'),
            ('1.6.42\n', r'^(?:quarto\s+)?(\d+(?:\.\d+)+)', (), 'ready'),
            ('quarto 1.7.0\n', r'^(?:quarto\s+)?(\d+(?:\.\d+)+)', (), 'ready'),
            ('pandoc 3.7\n', r'^pandoc (\d+(?:\.\d+)+)', converter.MINIMUM, 'unsupported'),
            ('pandoc 3.7.0.1\n', r'^pandoc (\d+(?:\.\d+)+)', converter.MINIMUM, 'unsupported'),
            ('pandoc 3.7.0.2\n', r'^pandoc (\d+(?:\.\d+)+)', converter.MINIMUM, 'ready'),
            ('pandoc 3.13\n', r'^pandoc (\d+(?:\.\d+)+)', converter.MINIMUM, 'ready'),
            ('broken\n', r'^v(\d+(?:\.\d+)+)', (22,), 'error'),
            ('v' + '9' * 5000 + '.0\n', r'^v(\d+(?:\.\d+)+)', (22,), 'error'),
        ):
            with self.subTest(output=output[:50]), patch.object(doctor, '_probe', return_value=(0, output)):
                self.assertEqual(doctor._version(['tool'], pattern, minimum)['status'], status)
        for error in (PermissionError('private secret'), subprocess.TimeoutExpired('tool', 3),
                      subprocess.SubprocessError('secret'), ValueError('too much output')):
            with self.subTest(error=error), patch.object(doctor, '_probe', side_effect=error):
                result = doctor._version(['tool'], r'(\d+\.\d+)')
                self.assertEqual(result['status'], 'error')
                self.assertNotIn('secret', result['detail'])
        with patch.object(doctor, '_probe', return_value=(7, 'v22.0.0')):
            self.assertIn('exited 7', doctor._version(['node'], r'^v(\d+\.\d+)')['detail'])

    def test_missing_empty_or_invalid_executable_never_starts_a_probe(self):
        for name in ('', 'not-installed'):
            with patch.object(doctor.shutil, 'which', return_value=None):
                self.assertEqual(doctor._version([name], r'(\d+)')['status'], 'missing')
        with patch.object(doctor.shutil, 'which', side_effect=ValueError('bad path')):
            self.assertEqual(doctor._version(['bad'], r'(\d+)')['status'], 'error')
        self.probe.assert_not_called()

    def test_commands_are_not_split_or_expanded_beyond_actual_runtime(self):
        command = str(self.home / 'tool with spaces; echo not-a-command')
        with patch.object(doctor, '_probe', return_value=(0, '1.2')) as probe:
            doctor._version([command, 'pandoc'], r'(\d+\.\d+)')
            probe.assert_called_once_with([command, 'pandoc', '--version'])
        with patch.object(doctor.shutil, 'which', return_value=None) as which:
            doctor._version(['~/unsupported-tilde'], r'(\d+)')
            which.assert_called_once_with('~/unsupported-tilde')

    def test_converter_search_order_continues_after_old_failed_and_missing_candidates(self):
        os.environ.update(MATSUGIT_PANDOC='override', MATSUGIT_TOOLS_DIR=str(self.home / 'tools'), QUARTO='custom quarto')
        for statuses in (('unsupported', 'error', 'missing', 'ready'), ('error', 'ready'), ('ready',)):
            with self.subTest(statuses=statuses), patch.object(doctor, '_version',
                    side_effect=[{'status': status, 'detail': status} for status in statuses]) as version:
                result = doctor._converter()
                self.assertEqual(result['status'], 'ready')
                self.assertNotIn('remedy', result)
                expected = [['override'], [str(self.home / 'tools/pandoc')], ['custom quarto', 'pandoc'], ['pandoc']]
                self.assertEqual([call.args[0] for call in version.call_args_list], expected[:len(statuses)])
                self.assertTrue(all(call.args[2] == converter.MINIMUM for call in version.call_args_list))

    def test_converter_failure_priority_preserves_all_candidate_details(self):
        for statuses, selected in ((('missing', 'unsupported', 'error'), 'unsupported'),
                                   (('error', 'missing', 'missing'), 'error'),
                                   (('missing',) * 3, 'missing')):
            with self.subTest(statuses=statuses), patch.object(doctor, '_version',
                    side_effect=[{'status': status, 'detail': f'candidate {i}'} for i, status in enumerate(statuses)]):
                result = doctor._converter()
                self.assertEqual(result['status'], selected)
                self.assertTrue(result['required'])
                self.assertIn('setup-editor', result['remedy'])
                for i in range(3):
                    self.assertIn(f'candidate {i}', result['detail'])

    def test_at_most_seven_probes_and_only_version_flags(self):
        os.environ['MATSUGIT_PANDOC'] = 'override'
        with patch.object(doctor, '_probe', return_value=(1, '')) as probe:
            doctor.diagnose()
        self.assertEqual(probe.call_count, 7)
        for call in probe.call_args_list:
            self.assertEqual(call.args[0][-1], '--version')
            self.assertIn(len(call.args[0]), (2, 3))
        os.environ.update(MATSUGIT_PANDOC='pandoc', MATSUGIT_TOOLS_DIR='')
        with patch.object(doctor, '_probe', return_value=(1, '')) as probe:
            doctor._converter()
        self.assertEqual([call.args[0] for call in probe.call_args_list],
                         [['pandoc', '--version'], ['quarto', 'pandoc', '--version']])

    def test_legacy_converter_environment_precedence_and_empty_values(self):
        self.write('.local/share/folioforge/tools/pandoc')
        with patch.object(doctor, '_version', return_value={'status': 'missing', 'detail': 'absent'}) as version:
            doctor._converter()
            self.assertEqual(version.call_args_list[0].args[0],
                             [str(self.home / '.local/share/folioforge/tools/pandoc')])
            for settings, expected in (({'FOLIOFORGE_PANDOC': 'legacy'}, 'legacy'),
                                       ({'MATSUGIT_PANDOC': 'current'}, 'current'),
                                       ({'MATSUGIT_PANDOC': '', 'MATSUGIT_TOOLS_DIR': ''}, 'pandoc'),
                                       ({'MATSUGIT_PANDOC': '   '}, '   '),
                                       ({'MATSUGIT_PANDOC': '', 'MATSUGIT_LEGACY_CONFIG': '0'}, 'pandoc')):
                with self.subTest(settings=settings):
                    os.environ.update(settings)
                    version.reset_mock()
                    doctor._converter()
                    self.assertEqual(version.call_args_list[0].args[0], [expected])

    def test_empty_quarto_does_not_claim_core_ready_but_converter_keeps_its_fallback(self):
        os.environ.update(QUARTO='', MATSUGIT_PANDOC='')
        data = self.checks()
        self.assertEqual(data['quarto']['status'], 'missing')
        with patch.object(doctor, '_version', return_value={'status': 'missing', 'detail': 'absent'}) as version:
            doctor._converter()
        self.assertIn(['quarto', 'pandoc'], [call.args[0] for call in version.call_args_list])

    def test_chart_interpreter_defaults_legacy_overrides_empty_and_missing(self):
        current = str(Path(sys.executable))
        old = self.write('.local/share/folioforge/charts/bin/python')
        new = self.home / '.local/share/matsugit/charts/bin/python'
        self.assertEqual(doctor._charts()['python'], str(old))
        self.write(new.relative_to(self.home))
        self.assertEqual(doctor._charts()['python'], str(new))
        os.environ['FOLIOFORGE_CHART_PYTHON'] = str(old)
        self.assertEqual(doctor._charts()['python'], str(old))
        for override in ('', '   ', str(self.home / 'missing')):
            with self.subTest(override=override):
                os.environ['MATSUGIT_CHART_PYTHON'] = override
                self.assertEqual(doctor._charts()['python'], current)
        os.environ['MATSUGIT_CHART_PYTHON'] = '~/.local/share/matsugit/charts/bin/python'
        self.assertEqual(doctor._charts()['python'], str(new))

    def test_optional_metadata_is_read_from_selected_environment_without_imports(self):
        for windows in (False, True):
            with self.subTest(windows=windows), patch.object(doctor, 'WINDOWS', windows):
                root = 'windows charts' if windows else 'unix charts'
                python = self.write(root + ('/Scripts/python.exe' if windows else '/bin/python'))
                self.distribution(root, 'altair', '6.0.0', windows)
                self.distribution(root, 'vl-convert-python', '1.9.0', windows)
                os.environ['MATSUGIT_CHART_PYTHON'] = str(python)
                result = doctor._charts()
                self.assertEqual(result['status'], 'ready')
                self.assertEqual(result['versions'], {'altair': '6.0.0', 'vl-convert-python': '1.9.0'})
                self.assertIn('Metadata only', result['detail'])
                python.unlink()
                self.assertEqual(doctor._versions(python, ('altair',)), {'altair': None})

    def test_export_selection_matches_importability_not_just_current_metadata(self):
        python = self.write('.local/share/matsugit/export-tools/bin/python')
        self.distribution('.local/share/matsugit/export-tools', 'playwright', '1.60.0')
        result = doctor._export()
        self.assertEqual(result['python'], str(python))
        self.assertEqual(result['status'], 'ready')
        self.assertIn('Chromium installation/launch is not checked', result['detail'])
        with patch.object(doctor.importlib.util, 'find_spec', return_value=object()):
            result = doctor._export()
            self.assertEqual(result['python'], str(Path(sys.executable)))
            self.assertEqual(result['status'], 'missing')
        with patch.object(doctor.metadata, 'version', return_value='99.0'):
            self.assertEqual(doctor._export()['python'], str(python))
        for override in ('', '~/.local/share/matsugit/export-tools/bin/python', str(self.home / 'absent')):
            with self.subTest(override=override):
                os.environ['MATSUGIT_EXPORT_PYTHON'] = override
                result = doctor._export()
                self.assertEqual(result['python'], str(Path(override)))
                self.assertEqual(result['status'], 'missing')

    def test_metadata_read_errors_do_not_abort_other_checks(self):
        with patch.object(doctor.metadata, 'version', side_effect=PermissionError('unreadable')):
            data = doctor.diagnose()
            self.assertTrue(data['ready'])
            self.assertEqual(next(c for c in data['checks'] if c['id'] == 'charts')['status'], 'error')
            self.assertEqual(data['checks'][-1]['id'], 'd2')

    def test_d2_manifest_validity_size_node_requirement_and_empty_override(self):
        path = self.write('.local/share/matsugit/diagrams/node_modules/@d2lang/d2/package.json', '{"version":"0.1.33"}')
        for ready, status in ((True, 'ready'), (False, 'unsupported')):
            self.assertEqual(doctor._d2(ready)['status'], status)
        for content in ('[]', '{}', '{"version":1}', '{"version":" "}', 'not JSON',
                        '{"version":"' + 'x' * 65536 + '"}', '[' * 2000):
            with self.subTest(content=content[:40]):
                path.write_text(content)
                result = self.checks()['d2']
                self.assertEqual(result['status'], 'error')
        path.write_bytes(b'\xff')
        self.assertEqual(doctor._d2(True)['status'], 'error')
        cwd = Path.cwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.home)
        local = self.write('node_modules/@d2lang/d2/package.json', '{"version":"0.1.33"}')
        os.environ['MATSUGIT_DIAGRAM_RUNTIME'] = ''
        result = doctor._d2(True)
        self.assertEqual(result['status'], 'ready')
        self.assertIn(str(self.home), result['detail'])
        local.unlink()
        self.assertEqual(doctor._d2(True)['status'], 'missing')

    def test_d2_manifest_read_is_bounded(self):
        stream = io.BytesIO(b' ' * 70000)
        with patch.object(Path, 'open', return_value=stream), self.assertRaises(ValueError):
            doctor._manifest(Path('package.json'))
        # BytesIO is closed by the context manager; observe read directly instead.
        stream = Mock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.read.return_value = b'{"version":"1"}'
        with patch.object(Path, 'open', return_value=stream):
            self.assertEqual(doctor._manifest(Path('package.json')), '1')
        stream.read.assert_called_once_with(65537)

    def test_checkout_installed_and_embedded_workspace_reports_are_distinct(self):
        self.assertEqual(doctor._workspace()['status'], 'missing')
        for name in ('server.mjs', 'browser.mjs', 'story-cli.mjs'):
            self.write('checkout/codex-plugin/bundle/' + name)
        result = doctor._workspace()
        self.assertEqual(result['status'], 'ready')
        self.assertIn('standalone checkout only', result['detail'])
        for folder in ('site-packages', 'broken-checkout', 'matsugit-runtime-test'):
            with self.subTest(folder=folder), patch.object(doctor, 'ROOT', self.home / folder):
                self.write(folder + '/codex-plugin/worker.py')
                result = doctor._workspace()
                self.assertFalse(result['required'])
                if folder.startswith('matsugit-runtime-'):
                    self.assertEqual(result['status'], 'ready')
                    self.assertIn('Embedded plugin runtime', result['detail'])
                    self.assertNotIn('remedy', result)
                else:
                    self.assertEqual(result['status'], 'missing')
                    self.assertIn('--checkout', result['remedy'])
        self.write('matsugit-runtime-test/codex-plugin/src/server.mjs')
        with patch.object(doctor, 'ROOT', self.home / 'matsugit-runtime-test'):
            self.assertEqual(doctor._workspace()['status'], 'missing')

    def test_windows_remedies_and_interpreter_paths(self):
        with patch.object(doctor, 'WINDOWS', True), patch.object(doctor.shutil, 'which', return_value=None):
            data = self.checks()
            for id, action in (('converter', 'editor'), ('charts', 'charts'), ('export', 'export'), ('d2', 'diagrams')):
                self.assertIn(f'py -3 -m matsugit setup-{action}', data[id]['remedy'])
                self.assertNotIn('python3', data[id]['remedy'])
            self.assertIn('pandoc.exe', data['converter']['detail'])
            self.assertTrue(data['export']['python'].endswith('Scripts/python.exe'))
            python = self.write('.local/share/matsugit/charts/Scripts/python.exe')
            self.assertEqual(doctor._charts()['python'], str(python))

    def test_diagnose_never_writes_imports_optional_code_or_uses_setup_network_or_config(self):
        self.write('matsugit.json', 'invalid and must not be read')
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        original_import, original_open, original_io_open = builtins.__import__, builtins.open, io.open

        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] in ('altair', 'vl_convert', 'playwright', 'matplotlib'):
                raise AssertionError('Imported optional package: ' + name)
            return original_import(name, *args, **kwargs)

        def read_only(opener):
            def guarded(file, mode='r', *args, **kwargs):
                self.assertFalse(any(flag in mode for flag in 'wax+'), (file, mode))
                self.assertNotEqual(Path(file).name, 'matsugit.json')
                return opener(file, mode, *args, **kwargs)
            return guarded

        with ExitStack() as stack:
            stack.enter_context(patch('builtins.__import__', side_effect=guarded_import))
            stack.enter_context(patch('builtins.open', side_effect=read_only(original_open)))
            stack.enter_context(patch('io.open', side_effect=read_only(original_io_open)))
            for target in ('os.open', 'os.mkdir', 'os.unlink', 'os.rename', 'os.replace', 'os.chmod'):
                stack.enter_context(patch(target, side_effect=AssertionError('Write attempted: ' + target)))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['doctor', '--json']), 0)
            self.assert_schema(json.loads(output.getvalue()))
        after = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


class ProbeTests(unittest.TestCase):
    def process(self, data=b'v22.0.0\n', returncode=0):
        process = Mock()
        process.stdout = io.BytesIO(data)
        process.stderr = io.BytesIO()
        process.wait.return_value = returncode
        process.poll.return_value = returncode
        return process

    def test_probe_has_no_shell_input_file_or_unbounded_capture(self):
        process = self.process(b'v22.0.0\n\xff')
        with patch.object(subprocess, 'Popen', return_value=process) as popen:
            code, output = doctor._probe(['/tools/node', '--version'])
        self.assertEqual(code, 0)
        self.assertEqual(output, 'v22.0.0\n\ufffd')
        popen.assert_called_once_with(['/tools/node', '--version'], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     shell=False, bufsize=0)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        process.kill.assert_not_called()
        process.communicate.assert_not_called()
        self.assertGreater(process.wait.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(process.wait.call_args.kwargs['timeout'], doctor.PROBE_TIMEOUT)

    def test_stderr_alone_cannot_claim_a_converter_is_usable(self):
        process = self.process(b'')
        process.stderr = io.BytesIO(b'pandoc 3.13\n')
        with patch.object(subprocess, 'Popen', return_value=process), \
             patch.object(doctor.shutil, 'which', return_value='/tools/pandoc'):
            result = doctor._version(['pandoc'], r'^pandoc (\d+(?:\.\d+)+)', converter.MINIMUM)
        self.assertEqual(result['status'], 'error')
        self.assertTrue(process.stderr.closed)

    def test_stderr_is_also_bounded_even_with_valid_stdout(self):
        process = self.process()
        process.stderr = io.BytesIO(b'x' * (doctor.PROBE_OUTPUT_LIMIT + 1))
        process.poll.return_value = None
        with patch.object(subprocess, 'Popen', return_value=process), self.assertRaisesRegex(ValueError, 'output exceeds'):
            doctor._probe(['node', '--version'])
        process.kill.assert_called_once()
        self.assertTrue(process.stderr.closed)

    def test_output_limit_is_enforced_during_read_and_process_is_reaped(self):
        process = self.process(b'x' * (doctor.PROBE_OUTPUT_LIMIT * 2))
        process.poll.return_value = None
        read = Mock(wraps=process.stdout.read)
        process.stdout.read = read
        with patch.object(subprocess, 'Popen', return_value=process), self.assertRaisesRegex(ValueError, 'output exceeds'):
            doctor._probe(['node', '--version'])
        self.assertEqual(sum(call.args[0] for call in read.call_args_list), doctor.PROBE_OUTPUT_LIMIT + 1)
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=doctor.PROBE_CLEANUP_TIMEOUT)
        self.assertTrue(process.stdout.closed)
        process.communicate.assert_not_called()

    def test_exact_output_limit_and_short_reads_are_supported(self):
        for content in (b'x' * doctor.PROBE_OUTPUT_LIMIT, b'v22.0.0\n'):
            with self.subTest(size=len(content)):
                process = self.process(content)
                read = process.stdout.read
                process.stdout.read = lambda size: read(min(size, 7))
                with patch.object(subprocess, 'Popen', return_value=process):
                    self.assertEqual(doctor._probe(['node', '--version']), (0, content.decode()))

    def test_timeout_before_eof_kills_waits_and_closes_without_draining(self):
        process = self.process()
        process.poll.return_value = None
        with patch.object(subprocess, 'Popen', return_value=process), \
             patch.object(doctor.queue.Queue, 'get', side_effect=queue.Empty), \
             self.assertRaises(subprocess.TimeoutExpired):
            doctor._probe(['node', '--version'])
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=doctor.PROBE_CLEANUP_TIMEOUT)
        self.assertTrue(process.stdout.closed)
        process.communicate.assert_not_called()

    def test_exit_wait_shares_read_deadline_and_cleanup_is_bounded(self):
        process = self.process()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('node', 3)
        with patch.object(subprocess, 'Popen', return_value=process), \
             patch.object(doctor.time, 'monotonic', side_effect=(100, 101, 102, 102.5)), \
             self.assertRaises(subprocess.TimeoutExpired):
            doctor._probe(['node', '--version'])
        self.assertEqual([c.kwargs['timeout'] for c in process.wait.call_args_list],
                         [0.5, doctor.PROBE_CLEANUP_TIMEOUT])
        process.kill.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_read_error_cleans_up_and_does_not_deadlock_the_queue(self):
        process = self.process()
        process.stdout.read = Mock(side_effect=OSError('pipe failed'))
        process.poll.return_value = None
        with patch.object(subprocess, 'Popen', return_value=process), self.assertRaises(OSError):
            doctor._probe(['node', '--version'])
        process.kill.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_launch_failure_is_reported_as_a_check_error(self):
        with patch.object(subprocess, 'Popen', side_effect=PermissionError('denied')), \
             patch.object(doctor.shutil, 'which', return_value='/tools/node'):
            result = doctor._version(['node'], r'^v(\d+(?:\.\d+)+)', (22,))
        self.assertEqual(result['status'], 'error')
        self.assertIn('PermissionError', result['detail'])


if __name__ == '__main__':
    unittest.main()
