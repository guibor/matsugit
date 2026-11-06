"""Explicit, fast-forward-only updates of the real source checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .core import Error


def git(repo, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes -o ConnectTimeout=15')
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], env=env,
                                capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise Error('Git timed out. Remote status is unknown; retry when connected') from error
    if result.returncode:
        raise Error((result.stderr or result.stdout).strip() or 'Git operation failed')
    return result.stdout if '-z' in args else result.stdout.strip()


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def changed_paths(repo):
    """Keep Git's NUL-delimited filenames intact, including spaces and newlines."""
    tracked = git(repo, 'diff', '--name-only', '--no-renames', '--no-ext-diff', '-z', 'HEAD', '--')
    untracked = git(repo, 'ls-files', '--others', '--exclude-standard', '-z')
    staged = git(repo, 'diff', '--cached', '--name-only', '--no-renames', '--no-ext-diff', '-z', '--')
    return sorted(set(filter(None, (tracked + untracked).split('\0')))), sorted(filter(None, staged.split('\0')))


def overlaps(local, incoming):
    return local == incoming or local.startswith(incoming + '/') or incoming.startswith(local + '/')


def inspect(source, fetch=True):
    source = Path(source).expanduser().resolve(strict=True)
    repo = Path(git(source.parent, 'rev-parse', '--show-toplevel')).resolve()
    branch = git(repo, 'branch', '--show-current')
    if not branch:
        raise Error('Detached HEAD: switch to a branch before synchronizing')
    for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        if Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', marker)).exists():
            raise Error('Finish the existing merge/rebase before synchronizing')
    try:
        remote = git(repo, 'config', '--get', f'branch.{branch}.remote')
        merge = git(repo, 'config', '--get', f'branch.{branch}.merge')
    except Error as error:
        raise Error('This branch has no upstream. Set its upstream in Git first') from error
    if remote == '.' or not merge.startswith('refs/heads/') or remote.startswith('-'):
        raise Error('Sync requires a configured remote tracking branch')
    url = git(repo, 'remote', 'get-url', remote)
    if fetch:
        git(repo, 'fetch', '--no-tags', remote, merge)
        upstream = git(repo, 'rev-parse', 'FETCH_HEAD')
    else:
        upstream = git(repo, 'rev-parse', '@{upstream}')
    head = git(repo, 'rev-parse', 'HEAD')
    ahead, behind = map(int, git(repo, 'rev-list', '--left-right', '--count', f'{head}...{upstream}').split())
    local, staged = changed_paths(repo)
    incoming = sorted(filter(None, git(repo, 'diff', '--name-only', '--no-renames', '--no-ext-diff', '-z', head, upstream, '--').split('\0'))) if behind else []
    blocked = [name for name in local if any(overlaps(name, other) for other in incoming)]
    dirty = bool(local or staged)
    status = ('diverged' if ahead and behind else 'ahead' if ahead else 'up-to-date' if not behind else
              'staged-changes' if staged else 'local-changes' if blocked else 'updates-available')
    data = dict(repo=str(repo), source=str(source), branch=branch, remote=remote,
                remote_sha256=hashlib.sha256(url.encode()).hexdigest(), merge=merge, head=head, upstream=upstream,
                ahead=ahead, behind=behind, dirty=dirty, status=status,
                local_changes=local, staged_changes=staged, overlapping_changes=blocked,
                incoming_changes=incoming,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                changes=git(repo, 'diff', '--stat', head, upstream) if behind else '')
    data['fingerprint'] = fingerprint(data)
    return data


def sync(source, *, expected=None, confirmed=False, check=False):
    """Fast-forward reviewed commits, preserving non-overlapping local work."""
    data = inspect(source)
    if check:
        return data
    if expected and data['fingerprint'] != expected:
        raise Error('Source or Git state changed since review. Check for updates again')
    if data['ahead'] and data['behind']:
        raise Error('Local and upstream histories diverged. Compare and merge in Git; no automatic merge was attempted')
    if not data['behind']:
        return data
    if data['staged_changes']:
        raise Error('Staged changes exist. Finish the staged commit in Git, then check again; nothing was stashed or overwritten')
    if data['overlapping_changes']:
        raise Error('Local changes overlap incoming updates: ' + ', '.join(data['overlapping_changes']) +
                    '. Compare/merge these files in Git, then check again; nothing was stashed or overwritten')
    if not confirmed:
        raise Error('Review updates first, then confirm Sync (CLI: --yes)')
    repo = data['repo']
    # Recheck after the network operation. Merge the reviewed SHA, not a moving ref.
    if (git(repo, 'rev-parse', 'HEAD') != data['head'] or
            git(repo, 'branch', '--show-current') != data['branch'] or
            changed_paths(repo) != (data['local_changes'], data['staged_changes']) or
            hashlib.sha256(Path(data['source']).read_bytes()).hexdigest() != data['source_sha256'] or
            hashlib.sha256(git(repo, 'remote', 'get-url', data['remote']).encode()).hexdigest() != data['remote_sha256']):
        raise Error('Checkout changed while checking updates; retry')
    # Git is the final overlap guard, including ignored files and late edits.
    git(repo, '-c', 'merge.autoStash=false', 'merge', '--ff-only', '--no-overwrite-ignore', data['upstream'])
    exists = Path(data['source']).is_file()
    return dict(data, status='updated' if exists else 'source-removed',
                head=git(repo, 'rev-parse', 'HEAD'), behind=0, source_exists=exists)
