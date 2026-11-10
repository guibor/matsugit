"""What the one-button Share flow needs to know about a document. Local only:
no fetch, no login, no change to any repository or setting."""
from pathlib import Path

from .core import Error, git
from .targets import settings as preferences


def project(repo, remote='origin'):
    from .publish import identity
    try:
        _, name, url = identity(Path(repo).expanduser(), remote)
        return name, url
    except (Error, OSError):
        return None, None


def target_for(repo, profiles=None):
    """The configured publishing target whose checkout is this repository."""
    profiles = preferences().get('publish_targets', {}) if profiles is None else profiles
    for name, profile in sorted(profiles.items()):
        if isinstance(profile, dict) and profile.get('repo') and Path(profile['repo']).expanduser().resolve() == Path(repo).resolve():
            return name, profile
    return None, {}


def receipt_plan(result):
    """Describe a Git push so its site build can be looked up afterwards."""
    name, profile = target_for(result['repo'])
    label, url = project(result['repo'], profile.get('remote', 'origin'))
    return {'branch': result['branch'], 'target': name or result['repo'], 'source_sha256': result['etag'],
            'build': 'ci' if name else 'git', 'project_url': url if name else None,
            'provider': (profile.get('provider') or ('github' if (url or '').startswith('https://github.com/') else 'gitlab')) if name else None,
            'site_url': profile.get('site_url')}, profile.get('deployment_environment')


def status(source):
    """mode 'sync': the file is tracked in a checkout with an upstream, so sharing
    means exchanging changes. mode 'new': it first has to be put into a project."""
    source = Path(source).expanduser().resolve()
    data = preferences()
    profiles = data.get('publish_targets', {})
    targets = []
    for name, profile in sorted(profiles.items()):
        if not isinstance(profile, dict) or profile.get('build', 'local') != 'ci':
            continue
        label, url = project(profile.get('repo', ''), profile.get('remote', 'origin'))
        targets.append({'name': name, 'label': label or name, 'project_url': url})
    result = {'mode': 'new', 'targets': targets, 'default': data.get('default_publish_target')}
    try:
        from .git_sync import inspect
        info = inspect(source, fetch=False)
        repo = Path(info['repo'])
        git(repo, 'ls-files', '--error-unmatch', '--', source.relative_to(repo).as_posix())
    except (Error, OSError, ValueError):
        return result
    name, profile = target_for(repo, profiles)
    label, url = project(repo, profile.get('remote', 'origin'))
    result.update(mode='sync', repo=str(repo), branch=info['branch'], target=name, label=label or repo.name,
                  project_url=url, site_url=profile.get('site_url'))
    return result
