"""Synthetic publishing target on a local bare remote, for tests only.

The remote is addressed as git@git.example.invalid:team/docs.git and served by a
fake ssh that runs the requested Git service locally. Nothing leaves the machine.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def create(root):
    root = Path(root).resolve()
    root.mkdir(parents=True)
    ssh = root / 'fakessh'
    ssh.write_text('#!/bin/sh\nfor last; do :; done\ncd "%s" && eval "$last"\n' % (root / 'remotes'))
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, GIT_SSH_COMMAND=str(ssh))

    def git(cwd, *args):
        subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, env=env)
    (root / 'remotes/team').mkdir(parents=True)
    git(root, 'init', '--bare', '--initial-branch=main', str(root / 'remotes/team/docs.git'))
    repo = root / 'docs'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'remote', 'add', 'origin', 'git@git.example.invalid:team/docs.git')
    notes = root / 'notes'
    notes.mkdir()
    source = notes / 'Deck.md'
    source.write_text('---\ntitle: Pilot\nslide-layout: structured\n---\n\n## One claim\n\nEvidence.\n')
    config_file = root / 'config.json'
    config_file.write_text(json.dumps({'default_publish_target': 'docs', 'publish_targets': {
        'docs': {'repo': str(repo), 'build': 'ci', 'provider': 'gitlab'}}}))
    os.environ.update(MATSUGIT_CONFIG=str(config_file), GIT_SSH_COMMAND=str(ssh))
    from matsugit.core import config
    from matsugit.publish import setup_ci
    setup_ci(config(source, {'repo': str(repo), 'build': 'ci'}), 'gitlab')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'Synthetic CI')
    git(repo, 'push', '-u', 'origin', 'main')
    return {'source': str(source), 'config': str(config_file), 'ssh': str(ssh), 'repo': str(repo),
            'destination': str(repo / 'matsugit-site/deck/source.md')}


if __name__ == '__main__':
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        data = create(sys.argv[1])
    print(json.dumps(data))
