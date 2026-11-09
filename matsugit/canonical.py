"""Scoped CI publication of a single canonical source, not a regenerated copy."""
import hashlib
from pathlib import Path
import tempfile

from .core import Error, git, inside, install_theme, read_json, write_json
from . import adopt
from .git_sync import fingerprint


def selected(settings):
    return settings.get('move_source') or settings['source'].is_relative_to(settings['repo'])


def preflight(settings, paths):
    repo = settings['repo']
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise Error('Choose the target checkout root')
    if git(repo, 'branch', '--show-current') != settings['branch']:
        raise Error(f"Switch the target to {settings['branch']} first")
    if git(repo, 'diff', '--cached', '--name-only'):
        raise Error('Staged changes exist; publish them separately first')
    # Unstaged and untracked work can coexist with a scoped publication. Git
    # rejects a fast-forward that would overwrite it, and publish() stages and
    # commits only the reviewed paths.
    return git(repo, 'rev-parse', 'HEAD')


def plan(settings):
    from .source_ci import layout, MANIFEST
    from .publish import identity
    repo, source = settings['repo'], settings['source']
    kind, directory = layout(settings)
    relocation = None
    if source.is_relative_to(repo):
        destination = source
        if kind == 'topics':
            if source.relative_to(repo).parts[0] not in ('topics', 'guides', 'presentations', 'exports'):
                raise Error('Source is in this checkout but outside its CI document directories. Move it into topics/ explicitly first')
        else:
            marker = source.parent / MANIFEST
            if not marker.is_file() or marker.is_symlink() or read_json(marker).get('source_file') != source.name:
                raise Error('Native CI requires an existing source manifest for in-place publication')
            if source.parent.parent != inside(repo, settings['site_dir']):
                raise Error('Native CI source must be in its configured site directory')
    else:
        if not settings.get('move_source'):
            raise Error('Choose move-and-link explicitly')
        folder = inside(repo, str(Path(directory) / settings['slug']))
        if folder.exists():
            raise Error('Move-and-link requires a new destination folder; reconcile an existing published copy explicitly')
        destination = folder / ('source.org' if source.suffix.lower() == '.org' else 'source.md')
        relocation = adopt.plan(source, repo, str(destination.relative_to(repo)))
    inventory = adopt.inventory(source, root=repo if source.is_relative_to(repo) and kind == 'topics' else None)
    files = {str(path if not relocation else destination if path == source else destination.parent / path.relative_to(source.parent)): adopt.digest(path)
             for path in inventory}
    if kind == 'native' and relocation:
        if any(Path(p).relative_to(destination.parent).parts[0] in ('theme', MANIFEST) for p in files):
            raise Error('Attachment collides with CI theme or manifest files')
        # Theme contents are part of the reviewed plan, not hidden mutable inputs.
        with tempfile.TemporaryDirectory(prefix='matsugit-theme-plan-') as temp:
            install_theme(settings, Path(temp))
            for p in Path(temp).rglob('*'):
                if p.is_file():
                    files[str(destination.parent / p.relative_to(temp))] = adopt.digest(p)
    paths = [str(Path(path).relative_to(repo)) for path in files]
    revision = preflight(settings, [] if relocation else paths)
    host, _, base = identity(repo, settings['remote'])
    remote = git(repo, 'remote', 'get-url', settings['remote'])
    if settings.get('expected_remote') and remote != settings['expected_remote']:
        raise Error('Remote changed; review expected_remote')
    data = dict(build='ci', canonical=True, move_source=bool(relocation), relocation=relocation,
                target=settings.get('target'), repo=str(repo), branch=settings['branch'], remote=remote,
                project_url=base, provider=settings.get('provider', 'github' if host == 'github.com' else 'gitlab'),
                directory=str(destination.parent.relative_to(repo)), destination=str(destination),
                theme=settings['theme'] if kind == 'native' else 'Managed by existing target CI',
                ci_layout=kind, files=files, revision=revision, site_url=settings.get('site_url'),
                deployment=settings.get('deployment', 'ci'),
                warning='Exact source and referenced assets are committed, including source-only comments. Existing CI rules/visibility remain unchanged. Original paths become local symlinks only when Move is selected.')
    data['fingerprint'] = fingerprint(data)
    return data


def publish(settings, confirmed=False, deploy=False):
    from .source_ci import MANIFEST
    from .publish import request_deployment
    reviewed = plan(settings)
    if not confirmed and input('Commit/push this canonical source (and move/link if selected)? [y/N] ').strip().lower() != 'y':
        return None
    repo, remote, branch = settings['repo'], settings['remote'], settings['branch']
    git(repo, 'fetch', remote, branch)
    upstream = git(repo, 'rev-parse', 'FETCH_HEAD')
    if git(repo, 'rev-list', '--count', f'{upstream}..HEAD') != '0':
        raise Error('Unpublished/divergent commits exist. Reconcile/push them in Git first')
    git(repo, '-c', 'merge.autoStash=false', 'merge', '--ff-only', upstream)
    updated = plan(settings)
    if any(updated[k] != reviewed[k] for k in reviewed if k not in ('revision', 'fingerprint')):
        raise Error('Source/assets or target changed during pull. Reload and review again; nothing overwritten')
    paths = [str(Path(p).relative_to(repo)) for p in updated['files']]
    if updated['relocation']:
        # Stage extra CI inputs before touching originals; on failure all originals
        # stay intact. Relocation itself is a checked, rollback-capable operation.
        with tempfile.TemporaryDirectory(prefix='matsugit-adopt-ci-') as temp:
            extra = Path(temp)
            if updated['ci_layout'] == 'native':
                install_theme(settings, extra)
            folder = Path(updated['destination']).parent
            if updated['ci_layout'] == 'native':
                write_json(extra / MANIFEST, dict(version=1, source_file=Path(updated['destination']).name,
                                        ci_layout='native', handout=bool(settings.get('handout')),
                                        files={str(Path(p).relative_to(folder)): h for p, h in updated['files'].items()}))
                paths.append(str((folder / MANIFEST).relative_to(repo)))
            created = []
            try:
                for file in extra.rglob('*'):
                    if file.is_file():
                        dest = folder / file.relative_to(extra)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with dest.open('xb') as stream:
                            stream.write(file.read_bytes())
                        created.append((dest, adopt.digest(file)))
                adopt.apply(updated['relocation'])
            except Exception:
                for dest, digest in created:
                    if dest.is_file() and not dest.is_symlink() and adopt.digest(dest) == digest:
                        dest.unlink()
                raise
    if any(adopt.digest(p) != digest for p, digest in updated['files'].items()):
        raise Error('Files changed before staging. Canonical files retained; review before publishing')
    if git(repo, 'rev-parse', 'HEAD') != updated['revision'] or git(repo, 'diff', '--cached', '--name-only'):
        raise Error('Git state changed; files retained, not committed')
    git(repo, 'add', '--', *paths)
    staged = set(filter(None, git(repo, 'diff', '--cached', '--name-only', '-z').split('\0')))
    if staged - set(paths):
        raise Error('Unexpected staged files; review the index, nothing committed')
    for path, digest in updated['files'].items():
        relative = str(Path(path).relative_to(repo))
        blob = git(repo, 'rev-parse', f':{relative}')
        if blob != git(repo, 'hash-object', '--no-filters', path):
            raise Error('Git filters or a concurrent edit changed staged bytes; review index before committing')
    if staged:
        git(repo, 'commit', '-m', f"Publish {Path(updated['destination']).name} source", '--', *paths)
    sha = git(repo, 'rev-parse', 'HEAD')
    if git(repo, 'remote', 'get-url', remote) != updated['remote']:
        raise Error('Remote changed; local commit retained, not pushed')
    try:
        git(repo, 'push', remote, f'{sha}:refs/heads/{branch}')
    except Error as error:
        raise Error(f'Push failed. Canonical files, symlinks and local commit {sha} are retained. Review and retry git push in {repo}. {error}') from error
    if deploy:
        request_deployment(settings, updated['provider'], updated['project_url'])
    return sha
