"""Choose repositories through existing gh/glab authentication; never log in."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote, urlsplit

from .core import Error, git
from . import targets


def validate(provider, host, repository=None):
    if provider not in ('github', 'gitlab'):
        raise Error('Choose GitHub or GitLab')
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', host or ''):
        raise Error('Enter a hostname, without a scheme, path or credentials')
    if repository is not None and (not re.fullmatch(r'[\w.-]+(?:/[\w.-]+)+', repository) or any(p.startswith('.') for p in repository.split('/'))):
        raise Error('Enter owner/repository (or group/subgroup/project), not a URL')


def command(args):
    if not shutil.which(args[0]):
        raise Error(f'{args[0]} is not installed. Configure the provider CLI separately; no account was connected')
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GH_PROMPT_DISABLED='1', GCM_INTERACTIVE='never')
    env.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes -o ConnectTimeout=15')
    try:
        result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise Error('Repository request timed out; check network and existing authentication') from error
    if result.returncode:
        raise Error(f'{args[0]} failed: {result.stderr.strip()[-1500:]}')
    return result.stdout


def api(provider, host, endpoint):
    validate(provider, host)
    return json.loads(command(['gh' if provider == 'github' else 'glab', 'api', '--hostname', host, endpoint]))


def brief(item, provider):
    return {'name':item['full_name' if provider == 'github' else 'path_with_namespace'],
            'url':item['html_url' if provider == 'github' else 'web_url'],
            'branch':item.get('default_branch'), 'archived':bool(item.get('archived'))}


def discover(provider, host, page=1):
    validate(provider, host)
    if not isinstance(page, int) or not 1 <= page <= 1000:
        raise Error('Invalid repository page')
    endpoint = ('user/repos?affiliation=owner,collaborator,organization_member&sort=updated' if provider == 'github'
                else 'projects?membership=true&archived=false&order_by=last_activity_at&sort=desc')
    data = api(provider, host, endpoint + f'&per_page=100&page={page}')
    if not isinstance(data, list): raise Error('Unexpected repository list response')
    return {'repositories':[brief(item, provider) for item in data if not item.get('archived')],
            'page':page, 'more':len(data) == 100}


def connect(provider, host, repository):
    validate(provider, host, repository)
    endpoint = 'repos/' + repository if provider == 'github' else 'projects/' + quote(repository, safe='')
    item = api(provider, host, endpoint)
    info = brief(item, provider)
    if info['archived'] or not info['branch']:
        raise Error('Select an initialized, non-archived repository')
    if provider == 'github' and item.get('permissions', {}).get('push') is False:
        raise Error('The current GitHub account has no push access to this repository')
    # API results must refer to the selected host/project, never a credential URL.
    url = item['clone_url' if provider == 'github' else 'http_url_to_repo']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Error('Provider returned an unsupported clone URL')
    canonical = parsed.path.removesuffix('.git').strip('/')
    if canonical.casefold() != repository.casefold():
        raise Error('Repository was renamed or redirected. Select its current name first')
    from .publish import identity
    for name, profile in targets.settings().get('publish_targets', {}).items():
        if not isinstance(profile, dict) or not profile.get('repo'): continue
        path = Path(profile['repo']).expanduser()
        if not (path / '.git').exists(): continue
        try:
            found_host, found_project, _ = identity(path, profile.get('remote', 'origin'))
        except Error:
            continue
        if (found_host.casefold(), found_project.casefold()) == (host.casefold(), canonical.casefold()):
            return {'target':name, 'repo':str(path), 'status':'Existing configured target selected. Nothing pushed.'}
    root = Path(os.environ.get('MATSUGIT_REPOSITORIES_DIR', str(Path.home() / '.local/share/matsugit/repositories'))).expanduser()
    key = hashlib.sha256(url.encode()).hexdigest()[:12]
    name = re.sub(r'[^a-zA-Z0-9_-]', '-', canonical.split('/')[-1])[:50] + '-' + key
    destination = root / name
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.is_symlink(): raise Error('Repository checkout is a symlink; left untouched')
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix='.clone-', dir=root) as temporary:
            stage = Path(temporary) / 'repo'
            print(f'Cloning {host}/{canonical}...', flush=True)
            command(['git', 'clone', '--single-branch', '--branch', info['branch'], '--', url, str(stage)])
            if destination.exists(): raise Error('Checkout appeared during clone; retry')
            stage.rename(destination)
    if git(destination, 'remote', 'get-url', 'origin') != url:
        raise Error('Existing checkout has a different remote; nothing changed')
    existing = targets.settings().get('publish_targets', {}).get(name)
    profile = {'repo':str(destination), 'provider':provider, 'branch':info['branch'], 'remote':'origin',
               'expected_remote':url, 'build':'ci', 'deployment':'push'}
    if (destination / 'scripts/build_pages.py').is_file():
        profile.update(ci_layout='topics', source_dir='topics/matsugit')
    if existing is not None and existing != profile:
        raise Error('A customized target has the same name; configuration retained')
    targets.configure(name, profile)
    return {'target':name, 'repo':str(destination),
            'status':'Repository connected locally. Review target before pushing; CI/hosting settings were not changed.'}
