"""Bounded, local-only Git history. No checkout, fetch, textconv or hooks."""
import os
from pathlib import Path
import re
import subprocess
import threading

LIMIT = 2 * 1024 * 1024


def run(root, *args, limit=LIMIT):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_LITERAL_PATHSPECS='1', GIT_OPTIONAL_LOCKS='0')
    with subprocess.Popen(['git', '--no-pager', '-C', str(root), '-c', 'core.fsmonitor=false', *args],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as process:
        timer = threading.Timer(10, process.kill)
        timer.start()
        try:
            value = process.stdout.read(limit + 1)
            if len(value) > limit:
                process.kill()
                raise ValueError('Git history exceeds the preview limit')
            if process.wait(timeout=2):
                raise ValueError('Local Git history is unavailable for this file')
            return value
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()


def entries(source):
    path = Path(source)
    if not path.is_absolute():
        return [], None
    root = Path(run(path.parent, 'rev-parse', '--show-toplevel', limit=16384).decode().strip())
    relative = path.relative_to(root).as_posix()
    raw = run(root, 'log', '--follow', '-30', '--no-ext-diff', '--no-textconv',
              '--format=%H%x00%at%x00%an', '--name-only', '-z', '--', relative, limit=256*1024)
    fields = raw.decode('utf-8').split('\0')
    result = []
    for offset in range(0, len(fields)-1, 4):
        revision, created, author, filename = fields[offset:offset+4]
        if not re.fullmatch('[0-9a-f]{40,64}', revision) or not created.isdecimal() or not filename.startswith('\n'):
            raise ValueError('Unsupported Git history output; local checkpoints remain available')
        result.append({'id':'git:'+revision, 'created':int(created), 'reason':'commit',
                       'author':author[:256], 'path':filename[1:], 'revision':revision})
    return result, root


def read(source, identifier):
    items, root = entries(source)
    item = next((item for item in items if item['id'] == identifier), None)
    if not item:
        raise ValueError('Commit is no longer in this document history; refresh Changes')
    name = item['path']
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Invalid historical document path')
    tree = run(root,'ls-tree','-z',item['revision'],'--',name,limit=16384)
    metadata, actual_name = tree.rstrip(b'\0').split(b'\t',1)
    mode, kind, _ = metadata.split()
    if mode not in (b'100644',b'100755') or kind != b'blob' or actual_name.decode('utf-8') != name:
        raise ValueError('Only regular source files can be restored from Git')
    target = item['revision'] + ':' + name
    size = int(run(root,'cat-file','-s',target,limit=32))
    if size > LIMIT:
        raise ValueError('Historical source exceeds 2 MiB')
    text = run(root,'cat-file','blob',target).decode('utf-8')
    if '\0' in text:
        raise ValueError('Historical source is not text')
    return {**item, 'text':text}
