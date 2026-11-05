"""Named publishing targets; setup never clones, enables hosting or publishes."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .compat import global_config
from .core import Error, read_json

FIELDS = {'repo', 'provider', 'remote', 'branch', 'site_dir', 'site_url', 'theme',
          'expected_remote', 'deployment', 'deployment_environment', 'build', 'ci_layout', 'source_dir'}


def settings():
    result = {}
    for path in global_config():
        if path.is_file():
            result.update(read_json(path))
    return result


def save(values):
    path = global_config()[-1]
    if path.is_symlink():
        raise Error('Configuration is a symlink; edit its destination explicitly')
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_bytes() if path.exists() else None
    data = settings()
    data.update(values)
    fd, name = tempfile.mkstemp(prefix='.matsugit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != previous:
            raise Error('Configuration changed during setup; retry')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return str(path)


def resolve(name, values=None):
    values = settings() if values is None else values
    profiles = values.get('publish_targets', {})
    if not isinstance(profiles, dict) or name not in profiles:
        raise Error(f'Unknown publishing target: {name}. Run matsugit target list')
    profile = profiles[name]
    if not isinstance(profile, dict) or not profile.get('repo'):
        raise Error(f'Target {name} requires a local checkout path')
    if set(profile) - FIELDS:
        raise Error(f'Unknown target settings: {sorted(set(profile) - FIELDS)}')
    if profile.get('provider') not in ('github', 'gitlab'):
        raise Error('Target provider must be github or gitlab')
    if any(not isinstance(v, str) or not v.strip() for v in profile.values()):
        raise Error('Target settings must be nonempty strings')
    if profile.get('deployment', 'ci') not in ('ci', 'push', 'tailscale'):
        raise Error('Unknown deployment policy')
    if profile.get('build', 'local') not in ('ci', 'local'):
        raise Error('Build must be ci or local')
    if profile.get('ci_layout', 'native') not in ('native', 'topics'):
        raise Error('CI layout must be native or topics')
    return dict(profile, repo=str(Path(profile['repo']).expanduser().resolve()))


def configure(name, profile, default=False):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', name):
        raise Error('Use a short target name with letters, numbers, hyphens or underscores')
    data = settings()
    profiles = dict(data.get('publish_targets', {}))
    profiles[name] = dict(profiles.get(name, {}), **{k: v for k, v in profile.items() if k in FIELDS and v is not None})
    resolve(name, {'publish_targets': profiles})
    changes = {'publish_targets': profiles}
    if default:
        changes['default_publish_target'] = name
    return save(changes)


def plan(config):
    if config.get('move_source') and config.get('build', 'local') != 'ci':
        raise Error('Move-and-link requires Source to CI, not rendered-output publication')
    if config.get('build', 'local') == 'ci':
        from .source_ci import plan as source_plan
        return source_plan(config)
    from .publish import preflight, identity, check_destination
    from .core import inside
    revision = preflight(config)
    host, project, url = identity(config['repo'], config['remote'])
    from .core import git
    remote = git(config['repo'], 'remote', 'get-url', config['remote'])
    if config.get('expected_remote') and remote != config['expected_remote']:
        raise Error('Target remote changed; review the configured expected_remote')
    provider = config.get('provider') or ('github' if host == 'github.com' else 'gitlab')
    destination = inside(config['repo'], str(Path(config['site_dir']) / config['slug']))
    check_destination(destination, config['source'])
    from .compat import existing
    site = inside(config['repo'], config['site_dir'])
    if (site / 'index.html').exists() and not existing(site / 'matsugit-site.json', site / 'folioforge-site.json').is_file():
        raise Error('Refusing to overwrite an unowned site index')
    data = {'build':'local', 'target': config.get('target'), 'repo': str(config['repo']), 'remote': remote,
            'provider': provider, 'project_url': url, 'branch': config['branch'],
            'directory': str(destination.relative_to(config['repo'])), 'theme': config['theme'],
            'revision': revision, 'source_sha256': hashlib.sha256(config['source'].read_bytes()).hexdigest(),
            'site_url': config.get('site_url'), 'deployment': config.get('deployment', 'ci'),
            'warning': 'Push may trigger existing CI. Site visibility is controlled by the hosting project.'}
    data['fingerprint'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data
