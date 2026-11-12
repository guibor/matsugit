"""Open the matsugit workspace in an ordinary browser tab.

The fallback for when no chat host shows the workspace: no plugin, another agent,
or a host that failed. It starts codex-plugin/bundle/browser.mjs, which runs the
same server and app as Cursor and Codex, on this computer only and behind a
private address, and stops by itself a minute after the tab is closed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import webbrowser

from .core import Error

SOURCES = ('.md', '.markdown', '.qmd', '.org')


def helper(checkout=None):
    root = Path(checkout).expanduser().resolve() if checkout else Path(__file__).resolve().parents[1]
    path = root / 'codex-plugin/bundle/browser.mjs'
    node = shutil.which('node')
    if not node:
        raise Error('Opening matsugit in the browser needs Node 22 or newer (nodejs.org).')
    if not path.is_file():
        raise Error('No bundled workspace here. Run this from a matsugit checkout, or pass --checkout /path/to/matsugit.')
    return node, path


def open_in_browser(source=None, *, checkout=None, browser=True, foreground=False):
    """Start the browser workspace for source (or the sample deck) and return {url, path}.

    By default the server keeps running in the background after this returns, so
    an agent's command finishes; it stops when the tab has been closed a minute.
    """
    if source is not None:
        source = Path(source).expanduser().resolve()
        if source.suffix.lower() not in SOURCES:
            raise Error('Open a Markdown or Org file (.md, .markdown, .qmd or .org).')
        if not source.is_file():
            raise Error(f'No such file: {source}')
    node, path = helper(checkout)
    command = [node, str(path), *([str(source)] if source else [])]
    log = Path(tempfile.gettempdir()) / 'matsugit-browser.log'
    options = {}
    if not foreground:
        if os.name == 'nt':
            options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options['start_new_session'] = True
    with open(log, 'ab') as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL, **options)
    line = process.stdout.readline().decode('utf-8', 'replace').strip()
    try:
        data = json.loads(line) if line else {'error': f'The workspace did not start. Details: {log}'}
    except json.JSONDecodeError:
        data = {'error': f'The workspace did not start. Details: {log}'}
    if 'error' in data:
        process.wait(timeout=10)
        raise Error(data['error'])
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
              ('Press Ctrl-C to stop.' if foreground else 'It stops by itself a minute after you close the tab.'), flush=True)
    if not foreground:
        process.stdout.close()
        return 0
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 0
