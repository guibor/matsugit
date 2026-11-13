"""Read-only first-use checks; never call setup, render, or account discovery.

Only known executables' version flags are run (at most seven probes, each with
a three-second timeout, one-second cleanup and 64 KiB limit per output stream).
Optional packages are inspected through metadata, not imported. This is
prerequisite detection, not a render test or a sandbox for
untrusted executables supplied through PATH/environment overrides.
"""
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

from . import __version__, converter, diagrams
from .compat import env, existing

PROBE_TIMEOUT = 3
PROBE_CLEANUP_TIMEOUT = 1
PROBE_OUTPUT_LIMIT = 65536
WINDOWS = os.name == 'nt'
ROOT = Path(__file__).resolve().parents[1]
GROUPS = ('python', 'git', 'node', 'quarto', 'converter', 'workspace', 'charts', 'export', 'd2')


def _setup(action):
    return f"{'py -3' if WINDOWS else 'python3'} -m matsugit {action}"


def _probe(command):
    """Bound memory as bytes arrive, including stderr, without temporary files."""
    deadline = time.monotonic() + PROBE_TIMEOUT
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, shell=False, bufsize=0)
    output = queue.Queue(maxsize=2)

    def read(name, stream):
        data = bytearray()
        try:
            while len(data) <= PROBE_OUTPUT_LIMIT:
                chunk = stream.read(min(4096, PROBE_OUTPUT_LIMIT + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            output.put((name, data))
        except (OSError, ValueError) as error:
            output.put((name, error))

    try:
        # A raw pipe and daemon reader also bound the caller if a child inherits
        # the pipe. Never communicate() after timeout: it can drain without bound.
        for name in ('stdout', 'stderr'):
            threading.Thread(target=read, args=(name, getattr(process, name)), daemon=True).start()
        stdout = b''
        for _ in range(2):
            try:
                name, data = output.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as error:
                raise subprocess.TimeoutExpired(command, PROBE_TIMEOUT) from error
            if isinstance(data, Exception):
                raise data
            if len(data) > PROBE_OUTPUT_LIMIT:
                raise ValueError(f'Version probe output exceeds {PROBE_OUTPUT_LIMIT} bytes.')
            if name == 'stdout':
                stdout = data
        returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
        return returncode, stdout.decode('utf-8', 'replace')
    finally:
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=PROBE_CLEANUP_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            pass
        process.stdout.close()
        process.stderr.close()


def _check(id, label, status, required, detail, remedy=None, **extra):
    result = dict(id=id, label=label, status=status, required=required, detail=detail, **extra)
    if remedy and status != 'ready':
        result['remedy'] = remedy
    return result


def _version(command, pattern, minimum=()):
    """Resolve exactly one executable, without a shell or installation fallback."""
    try:
        executable = shutil.which(command[0]) if command[0] else None
        if not executable:
            return dict(status='missing', detail='Executable not found: ' + (command[0] or '(empty command)'))
        command = [executable, *command[1:]]
        returncode, output = _probe([*command, '--version'])
    except subprocess.TimeoutExpired:
        return dict(status='error', detail=f'Version probe timed out after {PROBE_TIMEOUT}s.', command=command)
    except (OSError, subprocess.SubprocessError) as error:
        return dict(status='error', detail=f'Cannot run version probe ({type(error).__name__}).', command=command)
    except ValueError:
        return dict(status='error', detail='Invalid command or version probe output limit exceeded.', command=command)
    if returncode:
        return dict(status='error', detail=f'Version probe exited {returncode}.', command=command)
    match = re.search(pattern, output, re.MULTILINE)
    if not match:
        return dict(status='error', detail='Unrecognized version output.', command=command)
    version = match[1]
    if len(version) > 64:
        return dict(status='error', detail='Invalid version number.', command=command)
    numbers = tuple(int(n) for n in version.split('.'))
    supported = numbers + (0,) * max(0, len(minimum) - len(numbers)) >= minimum
    detail = f'Found {version}.' if supported else f'Found {version}; need >= {".".join(map(str, minimum))}.'
    return dict(status='ready' if supported else 'unsupported', detail=detail, version=version, command=command)


def _converter():
    # Follow converter.converter's search order, but retain failures/old versions
    # and use our shorter timeout. That API only returns a supported command.
    override = env('MATSUGIT_PANDOC')
    tools = converter.tools_dir()
    candidates = [[override]] if override else []
    candidates.append([str(tools / ('pandoc.exe' if WINDOWS else 'pandoc'))])
    candidates.extend([[os.environ.get('QUARTO') or 'quarto', 'pandoc'], ['pandoc']])
    attempts = []
    for command in candidates:
        if command in [item[0] for item in attempts]:
            continue
        result = _version(command, r'^pandoc (\d+(?:\.\d+)+)', converter.MINIMUM)
        attempts.append((command, result))
        if result['status'] == 'ready':
            break
    selected = next((item for _, item in attempts if item['status'] == 'ready'), None)
    if selected is None:
        selected = next((item for _, item in attempts if item['status'] == 'unsupported'), None)
    if selected is None:
        selected = next((item for _, item in attempts if item['status'] == 'error'), attempts[-1][1])
    selected = dict(selected)
    selected['detail'] += ' Candidates: ' + '; '.join(' '.join(cmd) + ': ' + item['detail'] for cmd, item in attempts)
    return _check('converter', 'Formatted editor (Pandoc)', required=True,
                  remedy=f'Run {_setup("setup-editor")} explicitly, or provide Pandoc >= 3.7.0.2 via MATSUGIT_PANDOC.',
                  **selected)


def _versions(python, names):
    """Read installed metadata without importing packages or starting venv Python."""
    if python == Path(sys.executable):
        result = {}
        for name in names:
            try:
                result[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                result[name] = None
        return result
    if not python.is_file():
        return dict.fromkeys(names)
    root = python.parent.parent
    paths = [root / 'Lib/site-packages'] if WINDOWS else [
        path for lib in ('lib', 'lib64') for path in (root / lib).glob('python*/site-packages')]
    result = {}
    for name in names:
        dist = next(iter(metadata.distributions(name=name, path=[str(p) for p in paths])), None)
        result[name] = dist.version if dist else None
    return result


def _packages(id, label, python, names, remedy):
    try:
        versions = _versions(python, names)
    except (OSError, ValueError, UnicodeError) as error:
        return _check(id, label, 'error', False, f'Cannot read package metadata ({type(error).__name__}).', remedy)
    missing = [name for name, version in versions.items() if not version]
    detail = f'Python: {python}. ' + ', '.join(f'{name}: {version or "missing"}' for name, version in versions.items())
    detail += '. Metadata only; imports and rendering were not tested.'
    return _check(id, label, 'missing' if missing else 'ready', False, detail, remedy,
                  versions=versions, python=str(python))


def _manifest(path):
    with path.open('rb') as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError('Package manifest exceeds 64 KiB')
    data = json.loads(data)
    if not isinstance(data, dict) or not isinstance(data.get('version'), str) or not data['version'].strip():
        raise ValueError('Package manifest has no version')
    return data['version']


def _workspace():
    bundle = ROOT / 'codex-plugin/bundle'
    if (ROOT.name.startswith('matsugit-runtime-') and
            (ROOT / 'codex-plugin/worker.py').is_file() and not bundle.is_dir() and
            not (ROOT / 'codex-plugin/src').is_dir()):
        return _check('workspace', 'Plugin workspace runtime', 'ready', False,
                      'Embedded plugin runtime; a standalone checkout bundle does not apply. '
                      'Host/plugin registration is not checked.')
    missing = [name for name in ('server.mjs', 'browser.mjs', 'story-cli.mjs') if not (bundle / name).is_file()]
    return _check('workspace', 'Checkout workspace bundle', 'missing' if missing else 'ready', False,
                 ('Missing: ' + ', '.join(missing) if missing else 'Bundled entry points present.') +
                 ' This checks the standalone checkout only, not host/plugin registration.',
                 'Use a complete matsugit checkout for open/check; a separate CLI install can pass --checkout /path/to/matsugit.')


def _charts():
    executable = 'Scripts/python.exe' if WINDOWS else 'bin/python'
    chart_python = Path(env('MATSUGIT_CHART_PYTHON', existing(
        '~/.local/share/matsugit/charts/' + executable,
        '~/.local/share/folioforge/charts/' + executable))).expanduser()
    if not chart_python.is_file():
        chart_python = Path(sys.executable)
    return _packages('charts', 'Optional charts (Altair/Vega-Lite)', chart_python,
                     ('altair', 'vl-convert-python'), f'For charts, run {_setup("setup-charts")} explicitly.')


def _export():
    executable = 'Scripts/python.exe' if WINDOWS else 'bin/python'
    export_python = Path(sys.executable)
    # This top-level lookup does not import Playwright and matches exports'
    # interpreter selection even when importable code and metadata disagree.
    if importlib.util.find_spec('playwright') is None:
        export_python = Path(os.environ.get('MATSUGIT_EXPORT_PYTHON',
            str(Path.home() / '.local/share/matsugit/export-tools' / executable)))
    result = _packages('export', 'Optional PDF/diagram export', export_python, ('playwright',),
                       f'For PDF/diagram export, run {_setup("setup-export")} explicitly.')
    result['detail'] += ' Chromium installation/launch is not checked; package presence alone does not prove export works.'
    return result


def _d2(node_ready):
    runtime = diagrams.runtime_path()
    package = runtime / 'node_modules/@d2lang/d2/package.json'
    remedy = f'For D2, install Node 22+ and npm, then run {_setup("setup-diagrams")} explicitly.'
    try:
        version = _manifest(package)
        return _check('d2', 'Optional D2 diagrams', 'ready' if node_ready else 'unsupported', False,
                     f'@d2lang/d2 {version} at {runtime}. Metadata only; rendering not tested.' +
                     ('' if node_ready else ' Node 22+ is also required.'), remedy, version=version)
    except FileNotFoundError:
        return _check('d2', 'Optional D2 diagrams', 'missing', False, f'No D2 runtime at {runtime}.', remedy)
    except (OSError, ValueError, UnicodeError) as error:
        return _check('d2', 'Optional D2 diagrams', 'error', False,
                     f'Cannot read D2 metadata ({type(error).__name__}).', remedy)


def _local_check(id, label, required, detect):
    try:
        return detect()
    except (OSError, ValueError, RuntimeError) as error:
        return _check(id, label, 'error', required,
                      f'Cannot inspect local prerequisites ({type(error).__name__}).',
                      'Check local paths, permissions and environment overrides, then retry.')


def diagnose():
    """Return schema 1 JSON data. Optional tools never affect top-level ready."""
    python_version = '.'.join(map(str, sys.version_info[:3]))
    checks = [_check('python', 'Python', 'ready' if sys.version_info >= (3, 10) else 'unsupported', True,
                     f'Running {python_version} at {sys.executable}; need >= 3.10.',
                     'Run matsugit with Python 3.10 or newer.', version=python_version)]
    quarto = os.environ.get('QUARTO', 'quarto')
    for id, label, command, pattern, minimum, remedy in (
        ('git', 'Git', 'git', r'^git version (\d+(?:\.\d+)+)', (), 'Install Git and make git available on PATH.'),
        ('node', 'Node workspace runtime', 'node', r'^v(\d+(?:\.\d+)+)', (22,), 'Install Node.js 22 or newer and make node available on PATH.'),
        ('quarto', 'Quarto core previews', quarto, r'^(?:quarto\s+)?(\d+(?:\.\d+)+)', (),
         'Install Quarto and make quarto available on PATH, or set QUARTO to its executable.'),
    ):
        checks.append(_check(id, label, required=True, remedy=remedy,
                             **_version([command], pattern, minimum)))
    checks.append(_local_check('converter', 'Formatted editor (Pandoc)', True, _converter))
    node_ready = next(c['status'] == 'ready' for c in checks if c['id'] == 'node')
    for id, label, detect in (
        ('workspace', 'Checkout workspace bundle', _workspace),
        ('charts', 'Optional charts (Altair/Vega-Lite)', _charts),
        ('export', 'Optional PDF/diagram export', _export),
        ('d2', 'Optional D2 diagrams', lambda: _d2(node_ready)),
    ):
        checks.append(_local_check(id, label, False, detect))
    return dict(schema=1, ready=all(c['status'] == 'ready' for c in checks if c['required']),
                checks=checks, version=__version__)


def report(data):
    lines = [f"matsugit {data['version']} setup: " + ('ready' if data['ready'] else 'not ready')]
    for check in data['checks']:
        lines.append(f"[{check['status']}] {check['label']} ({'required' if check['required'] else 'optional'}): {check['detail']}")
        if check.get('remedy'):
            lines.append('  Next: ' + check['remedy'])
    lines.append('Read-only prerequisite checks; no installs, renders, network requests, logins, or config changes.')
    return '\n'.join(lines)
