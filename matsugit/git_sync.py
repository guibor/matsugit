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
    return result.stdout.strip()


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


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
    dirty = bool(git(repo, 'status', '--porcelain', '--untracked-files=all'))
    status = ('local-changes' if dirty else 'diverged' if ahead and behind else
              'ahead' if ahead else 'updates-available' if behind else 'up-to-date')
    data = dict(repo=str(repo), source=str(source), branch=branch, remote=remote,
                remote_sha256=hashlib.sha256(url.encode()).hexdigest(), merge=merge, head=head, upstream=upstream,
                ahead=ahead, behind=behind, dirty=dirty, status=status,
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                changes=git(repo, 'diff', '--stat', head, upstream) if behind else '')
    data['fingerprint'] = fingerprint(data)
    return data


def sync(source, *, expected=None, confirmed=False, check=False):
    """Fetch for review; mutate only a clean checkout after explicit confirmation."""
    data = inspect(source)
    if check:
        return data
    if expected and data['fingerprint'] != expected:
        raise Error('Source or Git state changed since review. Check for updates again')
    if data['dirty']:
        raise Error('Local changes exist. Commit/reconcile them in Git first; nothing was stashed or overwritten')
    if data['ahead'] and data['behind']:
        raise Error('Local and upstream histories diverged. Compare and merge in Git; no automatic merge was attempted')
    if not data['behind']:
        return data
    if not confirmed:
        raise Error('Review updates first, then confirm Sync (CLI: --yes)')
    repo = data['repo']
    # Recheck after the network operation. Merge the reviewed SHA, not a moving ref.
    if (git(repo, 'rev-parse', 'HEAD') != data['head'] or
            git(repo, 'branch', '--show-current') != data['branch'] or
            git(repo, 'status', '--porcelain', '--untracked-files=all') or
            hashlib.sha256(git(repo, 'remote', 'get-url', data['remote']).encode()).hexdigest() != data['remote_sha256']):
        raise Error('Checkout changed while checking updates; retry')
    git(repo, '-c', 'merge.autoStash=false', 'merge', '--ff-only', data['upstream'])
    exists = Path(data['source']).is_file()
    return dict(data, status='updated' if exists else 'source-removed',
                head=git(repo, 'rev-parse', 'HEAD'), behind=0, source_exists=exists)
