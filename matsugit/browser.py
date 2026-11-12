"""Open the matsugit workspace in an ordinary browser tab.

The fallback for when no chat host shows the workspace: no plugin, another agent,
or a host that failed. It starts codex-plugin/bundle/browser.mjs, which runs the
same server and app as Cursor and Codex, on this computer only and behind a
private address, and stops by itself five minutes after the tab is closed.
"""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from urllib.parse import urlsplit

from .core import Error

SOURCES = ('.md', '.markdown', '.qmd', '.org')
START_TIMEOUT = 30


def helper(checkout=None):
    root = Path(checkout).expanduser().resolve() if checkout else Path(__file__).resolve().parents[1]
    path = root / 'codex-plugin/bundle/browser.mjs'
    node = shutil.which('node')
    if not node:
        raise Error('Opening matsugit in the browser needs Node 22 or newer (nodejs.org).')
    if not path.is_file():
        raise Error('No bundled workspace here. Run this from a matsugit checkout, or pass --checkout /path/to/matsugit.')
    try:
        version = subprocess.run([node, '--version'], capture_output=True, text=True, check=True, timeout=10)
        if int(version.stdout.strip().lstrip('v').split('.')[0]) < 22:
            raise ValueError('old Node')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise Error('Opening matsugit in the browser needs Node 22 or newer (nodejs.org).') from error
    return node, path


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    process.stdout.close()


def open_in_browser(source=None, *, checkout=None, browser=True, foreground=False):
    """Start the browser workspace for source (or the sample deck) and return {url, path}.

    By default the server keeps running in the background after this returns, so
    an agent's command finishes; it stops five minutes after the tab closes.
    """
    if source is not None:
        source = Path(source).expanduser().resolve()
        if source.suffix.lower() not in SOURCES:
            raise Error('Open a Markdown or Org file (.md, .markdown, .qmd or .org).')
        if not source.is_file():
            raise Error(f'No such file: {source}')
    node, path = helper(checkout)
    command = [node, str(path), *([str(source)] if source else [])]
    options = {}
    if not foreground:
        if os.name == 'nt':
            options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options['start_new_session'] = True
    fd, log = tempfile.mkstemp(prefix='matsugit-browser-', suffix='.log')
    with os.fdopen(fd, 'ab') as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL, **options)
    result = queue.Queue(maxsize=1)
    def read_ready():
        try:
            result.put(process.stdout.readline(65537))
        except (OSError, ValueError):
            result.put(b'')
    threading.Thread(target=read_ready, daemon=True).start()
    try:
        line = result.get(timeout=START_TIMEOUT)
        if len(line) > 65536:
            raise ValueError('Oversized startup response')
        line = line.decode('utf-8', 'replace').strip()
        data = json.loads(line) if line else {'error': f'The workspace did not start. Details: {log}'}
        if not isinstance(data, dict):
            raise ValueError('Invalid startup response')
        if 'error' in data:
            raise Error(str(data['error']))
        if not isinstance(data.get('url'), str):
            raise ValueError('Invalid local workspace address')
        url = urlsplit(data['url'])
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port:
            raise ValueError('Invalid local workspace address')
    except queue.Empty as error:
        stop(process)
        raise Error(f'The workspace did not start in {START_TIMEOUT} seconds. Details: {log}') from error
    except (ValueError, Error) as error:
        stop(process)
        raise Error(f'{error}. Details: {log}') from error
    if browser:
        webbrowser.open(data['url'])
    data['process'] = process
    return data


def run(source=None, *, checkout=None, browser=True, foreground=False, as_json=False):
    data = open_in_browser(source, checkout=checkout, browser=browser, foreground=foreground)
    process = data.pop('process')
    if as_json:
        print(json.dumps(data), flush=True)
    else:
        name = Path(data['path']).name if data.get('path') else 'the sample deck'
        print(f"matsugit is open in your browser on {name}:\n  {data['url']}\n"
              'The address is private to you. ' +
              ('Press Ctrl-C to stop.' if foreground else 'It stops by itself five minutes after you close the tab.'), flush=True)
    if not foreground:
        process.stdout.close()
        return 0
    try:
        return process.wait()
    except KeyboardInterrupt:
        stop(process)
        return 0
