"""Recognize shipped skill copies, then link them without discarding edits.

Receipts describe installed content, not just its location. Git history is an
offline migration fallback for older installs that predate receipts.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def generated(name):
    parts = Path(name).parts
    return parts[-1] == '.DS_Store' or ('__pycache__' in parts and parts[-1].endswith('.pyc'))


def files(root, *, git_hash=None, include_generated=False):
    result = {}
    if not root.is_dir():
        raise ValueError('Expected a skill directory: ' + str(root))
    def unreadable(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        for name in [*dirs, *names]:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError('Nested skill symlink retained: ' + str(path))
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError('Non-regular skill file retained: ' + str(path))
            if not include_generated and generated(relative):
                continue
            data = path.read_bytes()
            if git_hash:
                data = b'blob ' + str(len(data)).encode() + b'\0' + data
            result[relative] = hashlib.new(git_hash or 'sha256', data).hexdigest()
    return result


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL,
                                   timeout=30).decode().strip()


def shipped_revision(source, installed):
    """Match a complete skill tree, never a basename or only SKILL.md."""
    try:
        root = Path(git(source, 'rev-parse', '--show-toplevel')).resolve()
        prefix = source.relative_to(root).as_posix()
        algorithm = git(root, 'rev-parse', '--show-object-format')
        if algorithm not in ('sha1', 'sha256'):
            return None
        actual = files(installed, git_hash=algorithm)
        # Do not limit recognition to the last N commits: an old install is not
        # a customization. No fetch or other network operation is performed.
        revisions = git(root, 'log', '--format=%H', '--', prefix).splitlines()
        for revision in revisions:
            raw = git(root, 'ls-tree', '-rz', revision + ':' + prefix)
            expected = {}
            for entry in raw.split('\0'):
                if not entry:
                    continue
                metadata, name = entry.split('\t', 1)
                mode, kind, digest = metadata.split()
                if kind != 'blob' or mode not in ('100644', '100755'):
                    break
                if not generated(name):
                    expected[name] = digest
            else:
                if 'SKILL.md' in expected and actual == expected:
                    return revision
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def state(path):
    """Identity and content, including generated files, for race detection."""
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    link = os.readlink(path) if path.is_symlink() else None
    contents = files(path, include_generated=True) if path.is_dir() else None
    return (info.st_dev, info.st_ino, info.st_mode, link, contents)


def differences(actual, baseline):
    items = []
    for name in sorted(actual.keys() | baseline.keys()):
        if actual.get(name) != baseline.get(name):
            label = 'added' if name not in baseline else 'missing' if name not in actual else 'different'
            items.append(f'{name} ({label})')
    return ', '.join(items[:8]) + (f', and {len(items) - 8} more' if len(items) > 8 else '')


class SkillPlan:
    def __init__(self, source, target, previous=None):
        self.source = Path(source).expanduser().resolve()
        self.target = Path(target).expanduser().absolute()
        expected = files(self.source)
        if 'SKILL.md' not in expected:
            raise ValueError('Source skill lacks SKILL.md: ' + str(self.source))
        self.receipt = {'source': str(self.source), 'files': expected}
        self.before = state(self.target)
        self.action = 'link'
        if self.before is None:
            self.reason = 'not installed'
            return
        if self.target.is_symlink() and self.target.resolve() == self.source:
            self.action, self.reason = 'keep', 'linked to the current source'
            return
        previous = previous if isinstance(previous, dict) else {}
        prior_files = previous.get('files', {})
        if not isinstance(prior_files, dict):
            prior_files = {}
        if (self.target.is_symlink() and not self.target.exists()
                and str(self.target.resolve()) == previous.get('source')):
            self.reason = 'previous managed link moved'
            return
        actual = files(self.target) if self.target.is_dir() else {}
        if actual == expected:
            self.reason = 'unchanged copy of the current release'
        elif 'SKILL.md' in prior_files and actual == prior_files:
            self.reason = 'unchanged copy of the previous installation'
        else:
            revision = shipped_revision(self.source, self.target) if actual else None
            if revision:
                self.reason = 'unchanged shipped copy (' + revision[:10] + ')'
            else:
                baseline = prior_files or expected
                detail = differences(actual, baseline) or 'not a recognized skill directory'
                raise ValueError(
                    f'Existing skill retained: {self.target}\n'
                    f'Source: {self.source}\n'
                    f'Cannot verify this as an unchanged installation: {detail}. '
                    'No skill files changed. This is an installed-skill difference, not Git branch divergence.')

    def describe(self):
        action = 'current' if self.action == 'keep' else 'would link'
        return f'{self.target}: {action}; {self.reason}\n  source: {self.source}'

    def check_unchanged(self):
        if files(self.source) != self.receipt['files'] or state(self.target) != self.before:
            raise ValueError('Skill changed while preparing setup; retained: ' + str(self.target))

    def apply(self, backup_root):
        self.check_unchanged()
        if self.action == 'keep':
            return None
        self.target.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if self.before is not None:
            backup_root = Path(backup_root)
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix=self.target.name + '-', dir=backup_root)) / self.target.name
            self.target.rename(backup)
        try:
            if backup is not None:
                if backup.is_symlink():
                    info = backup.lstat()
                    after = (info.st_dev, info.st_ino, info.st_mode, os.readlink(backup), self.before[4])
                else:
                    after = state(backup)
                if after != self.before:
                    raise ValueError('Skill changed during migration; original retained at ' + str(backup))
            # Exclusive creation: never replace something that appeared while
            # the previous directory/link was being backed up.
            self.target.symlink_to(self.source, target_is_directory=True)
        except BaseException as exc:
            if backup is not None and not self.target.exists() and not self.target.is_symlink():
                backup.rename(self.target)
            elif backup is not None and isinstance(exc, Exception):
                raise ValueError('Skill destination changed during migration; retained: '
                                 + str(self.target) + '. Original retained at ' + str(backup)) from exc
            raise
        if backup is not None:
            (backup.parent / 'original-location.json').write_text(json.dumps({
                'path': str(self.target), 'link': self.before[3],
                'source': self.receipt['source']}, indent=2) + '\n')
        return backup
