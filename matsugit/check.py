"""Plain-language slide check on the command line.

The check itself is the workspace's (codex-plugin/src/check.mjs), run through
the bundled Node helper so the command line, agents and the workspace agree.
It reads text only: no rendering, no file writes, no network.
"""
import json
from pathlib import Path
import shutil
import subprocess

from .core import Error


def helper():
    path = Path(__file__).resolve().parents[1] / 'codex-plugin/bundle/story-cli.mjs'
    node = shutil.which('node')
    if not node or not path.is_file():
        raise Error('matsugit check needs Node 22+ and a matsugit checkout with its bundled workspace. '
                    'Use "matsugit lint" for the density checks that need neither')
    return node, path


def check(source):
    source = Path(source)
    if source.suffix.lower() not in ('.md', '.markdown', '.qmd', '.org'):
        raise Error('Supported sources: .md, .markdown, .qmd and .org')
    node, path = helper()
    request = {'action': 'check', 'source': source.read_text(encoding='utf-8'), 'org': source.suffix.lower() == '.org'}
    try:
        result = subprocess.run([node, str(path)], input=json.dumps(request), capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise Error('The check did not finish in 60 seconds') from error
    if result.returncode:
        raise Error('The check failed: ' + result.stderr.strip()[-500:])
    return json.loads(result.stdout)


def report(data):
    """One finding per paragraph: where, what, how. Problems before tips."""
    lines = []
    for item in data['findings']:
        where = f"Slide {item['slide']} ({item['title']})" if item.get('slide') else (item.get('title') or 'Top of the file')
        kind = 'To fix' if item['severity'] == 'problem' else 'Tip'
        lines.append(f"{kind}: {where}, line {item['line']}\n  {item['message']}" + (f"\n  {item['how']}" if item.get('how') else ''))
    summary = 'No problems found. This checks slide structure; still look at the slides.' if not data['findings'] \
        else f"{data['problems']} to fix, {data['tips']} tip(s)."
    return '\n\n'.join([*lines, summary]).replace('`', '')
