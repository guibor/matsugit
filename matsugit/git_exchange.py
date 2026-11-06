"""Reviewed, source-scoped Git exchange without stashing or force pushing.

Build the reviewed commit in a temporary index. When installing that commit,
selected entries already match the destination tree: Git's two-tree carry-forward
rules retain their working files. Only then write the reviewed source with a
fresh byte check. Unrelated files remain subject to Git's normal overwrite guard.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from .core import Error
from .git_sync import inspect, fingerprint

LIMIT = 2 * 1024 * 1024


def run(repo, *args, data=None, index=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never', GIT_LITERAL_PATHSPECS='1')
    env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes -o ConnectTimeout=15')
    env.pop('GIT_INDEX_FILE', None)
    if index: env['GIT_INDEX_FILE'] = str(index)
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], input=data, capture_output=True, env=env, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise Error('Git timed out. Keep the draft and check repository status before retrying.') from error
    if result.returncode:
        raise Error(result.stderr.decode('utf-8', 'replace').strip() or 'Git operation failed')
    return result.stdout


def line(repo, *args, **kwargs):
    return run(repo, *args, **kwargs).decode('utf-8').strip()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def safe_file(repo, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p.startswith('.') for p in path.parts):
        raise Error('Only ordinary files inside this checkout can be selected')
    lexical = Path(repo) / path
    if lexical.resolve() != lexical or not lexical.is_file():
        raise Error(f'Missing or symlinked file: {relative}')
    return lexical


def entry(repo, revision, relative):
    raw = run(repo, 'ls-tree', '-z', revision, '--', relative)
    if not raw: return None
    metadata, name = raw.rstrip(b'\0').split(b'\t', 1)
    mode, kind, oid = metadata.decode('ascii').split()
    if kind != 'blob' or mode not in ('100644', '100755') or name.decode('utf-8') != relative:
        raise Error(f'Only regular files can be synchronized: {relative}')
    return mode, oid


def source_text(repo, item):
    if not item: return ''
    if int(line(repo, 'cat-file', '-s', item[1])) > LIMIT:
        raise Error('A Git document version exceeds the 2 MiB editor limit')
    return run(repo, 'cat-file', 'blob', item[1]).decode('utf-8')


def remote_label(url):
    parsed = urlsplit(url)
    if parsed.scheme and parsed.hostname:
        return parsed.hostname + parsed.path
    if '@' in url and ':' in url:
        return url.split('@', 1)[1]
    return url


def plan(source, assets=(), *, fetch=True):
    data = inspect(source, fetch=fetch)
    repo = Path(data['repo']); source = Path(data['source'])
    relative = source.relative_to(repo).as_posix()
    safe_file(repo, relative)
    content = source.read_bytes()
    if len(content) > LIMIT: raise Error('Document exceeds the 2 MiB editor limit')
    if digest(content) != data['source_sha256']: raise Error('Document changed while checking Git; check again')
    outgoing_paths = set(filter(None, run(repo, 'diff', '--name-only', '--no-renames', '-z', data['upstream'], data['head']).decode('utf-8').split('\0'))) if data['ahead'] else set()
    selected = sorted(set(assets) - {relative})
    candidates, asset_warning = [], None
    try:
        from .adopt import inventory
        candidates = [p.relative_to(repo).as_posix() for p in inventory(source, root=repo)
                      if p != source and p.relative_to(repo).as_posix() in set(data['local_changes']) | outgoing_paths]
    except (Error, OSError, ValueError) as error:
        asset_warning = f'Attachment discovery unavailable: {error}'
    if set(selected) - set(candidates):
        raise Error('An attachment is no longer in the reviewed document; check again')
    paths = [relative, *selected]
    base = line(repo, 'merge-base', data['head'], data['upstream'])
    old = entry(repo, data['head'], relative)
    upstream = entry(repo, data['upstream'], relative)
    blocked = []
    push_urls = line(repo, 'remote', 'get-url', '--push', '--all', data['remote']).splitlines()
    if len(push_urls) != 1: blocked.append('Multiple push destinations require a normal Git push.')
    try:
        run(repo, 'check-ignore', '--quiet', '--', relative)
        blocked.append('The source is ignored by Git; choose a tracked document first.')
    except Error: pass
    if data['ahead'] and data['behind']:
        blocked.append('Committed histories have diverged. Merge those commits in Git first; uncommitted document edits can be reconciled here.')
    if data['staged_changes']: blocked.append('Staged work exists. Finish that commit separately before syncing.')
    if old and not upstream and data['behind']:
        blocked.append('The document was deleted or renamed upstream. Choose its new location in Git first.')
    for name in data['overlapping_changes']:
        if name not in paths:
            blocked.append(f'An incoming update overlaps an unselected local file: {name}')
    files = {}
    for name in paths:
        path = safe_file(repo, name); value = path.read_bytes()
        if len(value) > 100 * 1024 * 1024: raise Error(f'Selected file exceeds 100 MiB: {name}')
        files[name] = digest(value)
        attrs = run(repo, 'check-attr', '-z', 'filter', 'working-tree-encoding', 'eol', '--', name).split(b'\0')
        if any(attrs[i] not in (b'unspecified', b'unset') for i in range(2, len(attrs)-1, 3)):
            blocked.append(f'Custom Git file conversion requires a normal Git commit: {name}')
        if name != relative:
            start, incoming = entry(repo, base, name), entry(repo, data['upstream'], name)
            local_oid = line(repo, 'hash-object', '--no-filters', '--', str(path))
            if data['behind'] and incoming != start and (not incoming or local_oid != incoming[1]):
                blocked.append(f'Attachment changed upstream too; reconcile this binary file in Git: {name}')
    outgoing = line(repo, 'rev-list', f"{data['upstream']}..{data['head']}").splitlines()
    if len(outgoing) > 100: blocked.append('More than 100 unpublished commits require review in Git.')
    for revision in outgoing[:100]:
        changed = set(filter(None, run(repo, 'diff-tree', '--root', '-m', '--no-commit-id', '--name-only', '--no-renames', '-r', '-z', revision).decode('utf-8').split('\0')))
        if changed - set(paths):
            blocked.append('Unpublished commits include other files. Review/push those commits in Git first.'); break
    # Do not silently bypass a repository's commit policy with plumbing commits.
    hooks = line(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks')
    try: hooks = line(repo, 'config', '--get', 'core.hooksPath')
    except Error: pass
    hooks = Path(hooks).expanduser()
    if not hooks.is_absolute(): hooks = repo / hooks
    if any((hooks / name).is_file() and os.access(hooks / name, os.X_OK)
           for name in ('pre-commit', 'prepare-commit-msg', 'commit-msg', 'post-commit')):
        blocked.append('This repository uses commit hooks. Commit with Git so its checks run.')
    for setting in ('core.sparseCheckout', 'commit.gpgsign'):
        try:
            if line(repo, 'config', '--bool', '--get', setting) == 'true':
                blocked.append(f'{setting} is enabled. Use Git for this repository; its policy is unchanged.')
        except Error: pass
    try:
        if line(repo, 'config', '--get', 'core.autocrlf') not in ('false', ''):
            blocked.append('Automatic Git line-ending conversion requires a normal Git commit.')
    except Error: pass
    for identity in ('user.name', 'user.email'):
        try: line(repo, 'config', '--get', identity)
        except Error: blocked.append(f'Git {identity} is not configured.')
    data.update(relative=relative, paths=paths, assets=candidates, asset_warning=asset_warning,
                files=files, base_commit=base, outgoing_commits=outgoing,
                destination=remote_label(push_urls[0]), push_sha256=digest('\n'.join(push_urls).encode()),
                base=source_text(repo, entry(repo, base, relative)),
                local=content.decode('utf-8'), incoming=source_text(repo, upstream),
                blocked=blocked)
    data.pop('fingerprint', None)
    data['fingerprint'] = fingerprint(data)
    return data


@contextmanager
def locked(repo):
    file = Path(line(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'matsugit-sync.lock'))
    try: fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise Error('Another matsugit Git operation is running. Check again after it finishes.') from error
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally: file.unlink(missing_ok=True)


def set_entries(repo, entries, index=None):
    records = b''
    for name, item in entries.items():
        mode, oid = item or ('0', '0' * len(line(repo, 'rev-parse', 'HEAD')))
        records += f'{mode} {oid}\t{name}'.encode('utf-8') + b'\0'
    run(repo, 'update-index', '-z', '--index-info', data=records, index=index)


def checked_write(path, before, after):
    if path.is_symlink() or path.read_bytes() != before:
        raise Error('The document changed during Git sync. Its current contents were retained; review again before pushing.')
    if before == after: return
    fd, temporary = tempfile.mkstemp(prefix='.matsugit-sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        if path.is_symlink() or path.read_bytes() != before:
            raise Error('The document changed during Git sync. Your current contents were retained.')
        os.replace(temporary, path)
    finally: Path(temporary).unlink(missing_ok=True)


def exchange(source, text, *, assets=(), expected, message, confirmed=False):
    if not confirmed: raise Error('Review the versions, selected files and destination before confirming sync')
    if not isinstance(text, str) or '\0' in text or len(text.encode('utf-8')) > LIMIT:
        raise Error('Invalid reviewed document')
    if not isinstance(message, str) or not message.strip() or len(message) > 500:
        raise Error('Enter a commit message of 1-500 characters')
    initial = inspect(source, fetch=False)
    with locked(initial['repo']):
        data = plan(source, assets)
        if data['fingerprint'] != expected: raise Error('Git or file versions changed since review. Check again; nothing was written.')
        if data['blocked']: raise Error('\n'.join(data['blocked']))
        repo = Path(data['repo']); path = Path(data['source']); before = path.read_bytes()
        if digest(before) != data['source_sha256']: raise Error('Document changed since review; nothing was written.')
        after = text.encode('utf-8')
        recovery = Path(line(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'matsugit-recovery')) / str(uuid4())
        recovery.mkdir(parents=True, mode=0o700); os.chmod(recovery.parent, 0o700)
        (recovery / 'document-before').write_bytes(before)
        (recovery / 'document-reviewed').write_bytes(after)
        (recovery / 'state.json').write_text(json.dumps({k:data[k] for k in ('source','head','upstream','branch','paths','files')}, indent=2))
        for file in recovery.iterdir(): file.chmod(0o600)
        try:
            baseline = data['upstream'] if data['behind'] else data['head']
            entries = {}
            with tempfile.TemporaryDirectory(prefix='matsugit-sync-index-') as temp:
                index = Path(temp) / 'index'
                run(repo, 'read-tree', baseline, index=index)
                for name in data['paths']:
                    file = safe_file(repo, name)
                    if digest(file.read_bytes()) != data['files'][name]: raise Error(f'File changed during preparation: {name}')
                    value = after if name == data['relative'] else file.read_bytes()
                    oid = line(repo, 'hash-object', '-w', '--stdin', data=value)
                    prior = entry(repo, baseline, name) or entry(repo, data['head'], name)
                    mode = prior[0] if prior else '100755' if file.stat().st_mode & 0o111 else '100644'
                    entries[name] = (mode, oid)
                set_entries(repo, entries, index)
                tree = line(repo, 'write-tree', index=index)
                if tree == line(repo, 'rev-parse', f'{baseline}^{{tree}}') and not (data['ahead'] and data['behind']):
                    revision = baseline
                else:
                    parents = ['-p', data['head'], '-p', data['upstream']] if data['ahead'] and data['behind'] else ['-p', baseline]
                    revision = line(repo, 'commit-tree', tree, *parents, '-m', message.strip())
            # Recheck all input versions before touching the real index or HEAD.
            fresh = plan(source, assets, fetch=False)
            # A fetched SHA need not yet have updated the remote-tracking ref.
            if any(fresh[k] != data[k] for k in ('head','branch','remote_sha256','push_sha256','files','staged_changes','local_changes')):
                raise Error('Checkout changed during preparation; no branch was advanced.')
            if revision != data['head']:
                original_entries = {name:entry(repo, data['head'], name) for name in entries}
                set_entries(repo, entries)
                try:
                    staged = set(filter(None, run(repo, 'diff', '--cached', '--name-only', '-z').decode('utf-8').split('\0')))
                    if staged - set(entries): raise Error('Other files were staged concurrently; nothing was pushed.')
                    run(repo, '-c', 'merge.autoStash=false', 'merge', '--ff-only', '--no-overwrite-ignore', revision)
                except Exception:
                    if line(repo, 'rev-parse', 'HEAD') == data['head']:
                        restore = {}
                        for name in entries:
                            current = run(repo, 'ls-files', '--stage', '-z', '--', name).split(b'\t', 1)[0].decode('ascii').split()
                            if len(current) == 3 and tuple(current[:2]) == entries[name]: restore[name] = original_entries[name]
                        if restore: set_entries(repo, restore)
                    raise
            checked_write(path, before, after)
            if (line(repo, 'rev-parse', 'HEAD') != revision or line(repo, 'branch', '--show-current') != data['branch'] or
                    digest(line(repo, 'remote', 'get-url', data['remote']).encode()) != data['remote_sha256'] or
                    digest(line(repo, 'remote', 'get-url', '--push', '--all', data['remote']).encode()) != data['push_sha256']):
                raise Error('Repository identity changed. The local commit is retained, not pushed.')
            for name in data['paths']:
                expected_bytes = after if name == data['relative'] else None
                if digest(safe_file(repo, name).read_bytes()) != (digest(expected_bytes) if expected_bytes is not None else data['files'][name]):
                    raise Error('Selected files changed before push. The local commit is retained; review again.')
            run(repo, 'push', data['remote'], f"{revision}:{data['merge']}")
            return dict(status='pushed', revision=revision, etag=digest(after), repo=str(repo), source=str(path),
                        branch=data['branch'], paths=data['paths'], recovery=str(recovery),
                        message='Committed and pushed the reviewed files. Existing CI may run; deployment is not verified.')
        except (Error, OSError, UnicodeError) as error:
            raise Error(f'{error}\nDraft recovery retained at {recovery}. Local commits, if created, were not discarded. Check again before retrying.') from error
