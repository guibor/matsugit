"""Add the matsugit workspace to Claude Desktop without changing anything else.

Claude Desktop shows MCP Apps, so the same panel as in Cursor and Codex opens in
the conversation. It reads local servers from claude_desktop_config.json; this
adds one entry, keeps every other server and setting, backs up the previous file
and refuses to replace a matsugit entry it did not write.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .core import Error, read_json
from .cursor import atomic


def config_dir(home=None, platform=None):
    """Where Claude Desktop keeps claude_desktop_config.json."""
    platform = platform or sys.platform
    base = Path(home) if home else Path.home()
    if platform == 'darwin':
        return base / 'Library/Application Support/Claude'
    if platform == 'win32':
        appdata = os.environ.get('APPDATA') if home is None else None
        return (Path(appdata) if appdata else base / 'AppData/Roaming') / 'Claude'
    return base / '.config/Claude'


def install(checkout=None, *, home=None, check=False, platform=None):
    root = Path(checkout or Path(__file__).resolve().parents[1]).expanduser().resolve()
    server = root / 'codex-plugin/bundle/server.mjs'
    if not server.is_file():
        raise Error('A matsugit checkout with the bundled workspace is required. Use setup-claude-desktop --checkout /path/to/matsugit')
    node = shutil.which('node')
    if not node:
        raise Error('Claude Desktop needs Node 22+ for matsugit (nodejs.org)')
    from .core import run
    if int(run([node, '-p', 'process.versions.node.split(".")[0]']).strip()) < 22:
        raise Error('Claude Desktop needs Node 22+ for matsugit')
    base = config_dir(home, platform)
    config_path, receipt = base / 'claude_desktop_config.json', base / 'matsugit-install.json'
    for path in (config_path, receipt):
        if path.is_symlink():
            raise Error(f'Refusing to replace symlink: {path}')
    original = config_path.read_bytes() if config_path.exists() else None
    previous = read_json(receipt) if receipt.exists() else {}
    try:
        data = read_json(config_path) if original is not None else {}
    except (Error, ValueError) as error:
        raise Error(f'{config_path} is not a JSON object Claude Desktop can use; nothing changed') from error
    servers = data.get('mcpServers', {})
    if not isinstance(servers, dict):
        raise Error('Claude Desktop mcpServers must be an object; nothing changed')
    # A desktop app does not start from a shell, so give the server the PATH and
    # tools this shell finds (Python, Quarto, Git).
    environment = {'MATSUGIT_PYTHON': sys.executable, 'PATH': os.environ.get('PATH', '')}
    if os.name == 'nt':
        environment['PYTHONUTF8'] = '1'
    quarto = shutil.which('quarto')
    if quarto:
        environment['QUARTO'] = quarto
    entry = {'command': node, 'args': [str(server)], 'env': environment}
    if 'matsugit' in servers and servers['matsugit'] not in (entry, previous.get('server')):
        raise Error('Claude Desktop already has a different matsugit server. Review it in '
                    f'{config_path} before changing configuration; nothing changed')
    if servers.get('matsugit') == entry:
        return f'Claude Desktop already has matsugit configured: {config_path}. Nothing changed.'
    if check:
        return f'Would add the matsugit server to {config_path}, keeping {len(servers)} other server(s).'
    base.mkdir(parents=True, exist_ok=True)
    backup = None
    if original is not None:
        backup = Path(tempfile.mkdtemp(prefix='matsugit-backup-', dir=base)) / 'claude_desktop_config.json'
        atomic(backup, original)
    if (config_path.read_bytes() if config_path.exists() else None) != original:
        raise Error('Claude Desktop configuration changed during setup; retry')
    data['mcpServers'] = dict(servers, matsugit=entry)
    atomic(config_path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())
    atomic(receipt, (json.dumps({'server': entry}, indent=2) + '\n').encode())
    return (f'Claude Desktop matsugit configured: {config_path}.'
            + (f' Previous file backed up to {backup}.' if backup else '')
            + ' Quit and reopen Claude Desktop, then ask: "Show me how matsugit works".'
            + ' No documents published.')
