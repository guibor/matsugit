"""Install the shared MCP workspace into Cursor without changing other servers."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .core import Error, read_json


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.matsugit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install(checkout=None, *, home=None, check=False):
    root = Path(checkout or Path(__file__).resolve().parents[1]).expanduser().resolve()
    server = root / 'codex-plugin/bundle/server.mjs'
    skill = root / 'skills/matsugit'
    commands = root / 'cursor-commands'
    if not server.is_file() or not (skill / 'SKILL.md').is_file() or not commands.is_dir():
        raise Error('A matsugit Git checkout with the bundled workspace is required. Use setup-cursor --checkout /path/to/matsugit')
    node = shutil.which('node')
    if not node:
        raise Error('Cursor workspace requires Node 22+ on PATH')
    from .core import run
    if int(run([node, '-p', 'process.versions.node.split(".")[0]']).strip()) < 22:
        raise Error('Cursor workspace requires Node 22+')
    base = (Path(home) if home else Path.home()) / '.cursor'
    config_path, receipt = base / 'mcp.json', base / 'matsugit-install.json'
    skill_link = base / 'skills/matsugit'
    for path in (config_path, receipt):
        if path.is_symlink(): raise Error(f'Refusing to replace symlink: {path}')
    original = config_path.read_bytes() if config_path.exists() else None
    previous = read_json(receipt) if receipt.exists() else {}
    data = read_json(config_path) if config_path.exists() else {}
    servers = data.get('mcpServers', {})
    if not isinstance(servers, dict): raise Error('Cursor mcpServers must be an object; nothing changed')
    environment = {'MATSUGIT_PYTHON':sys.executable, 'PATH':os.environ.get('PATH', '')}
    quarto = shutil.which('quarto')
    if quarto: environment['QUARTO'] = quarto
    entry = {'command':node, 'args':[str(server)], 'env':environment}
    if 'matsugit' in servers and servers['matsugit'] not in (entry, previous.get('server')):
        raise Error('Cursor already has a different matsugit server. Review it before changing configuration')
    if skill_link.exists() or skill_link.is_symlink():
        if skill_link.resolve() != skill:
            raise Error(f'Existing Cursor skill retained: {skill_link}. Reconcile it before installing')
    writes = {}
    for source in sorted(commands.glob('*.md')):
        target = base / 'commands' / source.name
        body = source.read_bytes()
        if target.is_symlink(): raise Error(f'Existing command is a symlink: {target}')
        if target.exists() and target.read_bytes() != body:
            expected = previous.get('commands', {}).get(source.name)
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise Error(f'Custom Cursor command retained: {target}')
        writes[target] = body
    if check:
        return f'Would configure matsugit MCP, shared skill and {len(writes)} commands in {base}'
    base.mkdir(parents=True, exist_ok=True)
    if original is not None and servers.get('matsugit') != entry:
        backup = Path(tempfile.mkdtemp(prefix='matsugit-backup-', dir=base)) / 'mcp.json'
        atomic(backup, original)
    if config_path.is_symlink() or (config_path.read_bytes() if config_path.exists() else None) != original:
        raise Error('Cursor configuration changed during setup; retry')
    data['mcpServers'] = dict(servers, matsugit=entry)
    atomic(config_path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())
    skill_link.parent.mkdir(parents=True, exist_ok=True)
    if not skill_link.exists(): skill_link.symlink_to(skill, target_is_directory=True)
    for path, body in writes.items(): atomic(path, body)
    atomic(receipt, (json.dumps({'server':entry, 'commands':{
        path.name:hashlib.sha256(body).hexdigest() for path,body in writes.items()}}, indent=2) + '\n').encode())
    return f'Cursor matsugit configured: {config_path}. Enable/reload its MCP server and open a new chat. No documents published.'
