"""Install the shared MCP workspace into Cursor without changing other servers."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .core import Error, read_json
from .skill_install import SkillPlan


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
    receipt_original = receipt.read_bytes() if receipt.exists() else None
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
    try:
        skill_plan = SkillPlan(skill, skill_link, previous.get('skill'))
    except ValueError as exc:
        raise Error('Existing Cursor skill retained. ' + str(exc)) from exc
    writes, originals = {}, {}
    for source in sorted(commands.glob('*.md')):
        target = base / 'commands' / source.name
        body = source.read_bytes()
        if target.is_symlink(): raise Error(f'Existing command is a symlink: {target}')
        before = target.read_bytes() if target.exists() else None
        if before is not None and before != body:
            expected = previous.get('commands', {}).get(source.name)
            if hashlib.sha256(before).hexdigest() != expected:
                raise Error(f'Custom Cursor command retained: {target}')
        writes[target] = body
        originals[target] = before
    if check:
        return (f'Would configure matsugit MCP and {len(writes)} commands in {base}\n'
                + skill_plan.describe())
    for path, before in {config_path:original, receipt:receipt_original, **originals}.items():
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != before:
            raise Error(f'Cursor file changed during setup; retained: {path}')
    try:
        skill_backup = skill_plan.apply(base / 'matsugit-skill-backups')
    except ValueError as exc:
        raise Error(str(exc)) from exc
    base.mkdir(parents=True, exist_ok=True)
    if original is not None and servers.get('matsugit') != entry:
        backup = Path(tempfile.mkdtemp(prefix='matsugit-backup-', dir=base)) / 'mcp.json'
        atomic(backup, original)
    if config_path.is_symlink() or (config_path.read_bytes() if config_path.exists() else None) != original:
        raise Error('Cursor configuration changed during setup; retry')
    data['mcpServers'] = dict(servers, matsugit=entry)
    writes[config_path] = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
    writes[receipt] = (json.dumps({'server':entry, 'skill':skill_plan.receipt, 'commands':{
        path.name:hashlib.sha256(body).hexdigest() for path,body in writes.items()
        if path != config_path}}, indent=2) + '\n').encode()
    originals.update({config_path: original, receipt: receipt_original})
    for path, body in writes.items():
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != originals[path]:
            raise Error(f'Cursor file changed during setup; retained: {path}')
        if body != originals[path]:
            atomic(path, body)
    backup_message = f' Previous skill retained at {skill_backup}.' if skill_backup else ''
    return (f'Cursor matsugit configured: {config_path}. Skill follows {skill}.' + backup_message
            + ' Enable/reload its MCP server and open a new chat. No documents published.')
