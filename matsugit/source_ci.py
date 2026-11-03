"""Publish inert source bundles for an explicitly installed CI renderer."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import quote

from .core import Error, git, inside, normalize, install_theme, read_json, write_json
from .publish import preflight, identity

MANIFEST = 'matsugit-source.json'


def layout(settings):
    kind = settings.get('ci_layout', 'native')
    repo = settings['repo']
    if kind == 'native':
        builder = repo / '.matsugit-ci/build.py'
        if not builder.is_file() or 'matsugit-source.json' not in builder.read_text():
            raise Error('Source CI is not installed in this target. Run setup-ci in a new target, or review an upgrade of its existing CI first')
        return kind, settings['site_dir']
    if kind == 'topics':
        directory = settings.get('source_dir', 'topics/matsugit')
        if Path(directory).parts[0] not in ('topics', 'presentations', 'guides', 'exports'):
            raise Error('The topics CI adapter requires an existing document source directory')
        if not (repo / 'scripts/build_pages.py').is_file():
            raise Error('This target has no existing scripts/build_pages.py source renderer')
        inside(repo, directory)
        return kind, directory
    raise Error('Unknown source CI layout; choose native or topics')


def check_destination(destination, source):
    if not destination.exists():
        return
    marker = destination / MANIFEST
    if marker.is_symlink() or not marker.is_file():
        raise Error(f'Refusing to replace an unowned source directory: {destination}')
    data = read_json(marker)
    if data.get('version') != 1 or not isinstance(data.get('files'), dict):
        raise Error('Unknown source bundle ownership manifest')
    actual = {}
    for path in destination.rglob('*'):
        if path.is_symlink() or any(p.startswith('.') for p in path.relative_to(destination).parts):
            raise Error('Unexpected hidden file or symlink in source bundle')
        if path.is_file() and path != marker:
            actual[path.relative_to(destination).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = dict(data['files'])
    # Editing the tracked source in place is intentional; edits in a separate
    # target checkout must be reconciled, not silently replaced by another copy.
    name = data.get('source_file')
    if name in actual and source == (destination / name).resolve():
        expected[name] = actual[name]
    if actual != expected:
        raise Error('Published source/assets were edited or files added. Reconcile the target bundle before publishing')


def plan(settings):
    revision = preflight(settings)
    kind, directory = layout(settings)
    repo = settings['repo']
    host, _, base = identity(repo, settings['remote'])
    remote = git(repo, 'remote', 'get-url', settings['remote'])
    if settings.get('expected_remote') and remote != settings['expected_remote']:
        raise Error('Target remote changed; review expected_remote')
    destination = inside(repo, str(Path(directory) / settings['slug']))
    check_destination(destination, settings['source'])
    data = {'build':'ci', 'ci_layout':kind, 'target':settings.get('target'),
            'repo':str(repo), 'remote':remote, 'project_url':base,
            'provider':settings.get('provider', 'github' if host == 'github.com' else 'gitlab'),
            'branch':settings['branch'], 'directory':str(destination.relative_to(repo)),
            'theme':settings['theme'] if kind == 'native' else 'Managed by existing target CI',
            'revision':revision, 'source_sha256':hashlib.sha256(settings['source'].read_bytes()).hexdigest(),
            'site_url':settings.get('site_url'), 'deployment':settings.get('deployment', 'ci'),
            'warning':'Only source, referenced assets and renderer inputs are pushed. Existing CI rules decide when builds run. Hosting access is unchanged.'}
    data['fingerprint'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data


def prepare(settings, output, reviewed):
    """Normalize with Pandoc only. Never run Quarto render on the client."""
    from .converter import converter
    output.mkdir()
    ast = normalize(dict(settings, _preview_pandoc=converter()), output)
    from .canvas import contains
    if contains(ast):
        repo = settings['repo']
        if reviewed['ci_layout'] == 'native':
            installed = (repo / '.matsugit-ci/canvas.py').is_file()
        else:
            installed = any((repo / prefix / 'scripts/matsugit_semantics/canvas.py').is_file()
                            for prefix in ('', '.matsugit-renderer', '.folioforge-renderer'))
        if not installed:
            raise Error('This CI renderer predates HTML canvases. Update its reviewed renderer first; no source was committed')
    source_name = 'source.org' if settings['source'].suffix.lower() == '.org' else 'source.md'
    if source_name == 'source.org':
        (output / 'source.md').unlink()
    if reviewed['ci_layout'] == 'native':
        install_theme(settings, output)
    edit_part = '/edit/' if reviewed['provider'] == 'github' else '/-/edit/'
    edit = reviewed['project_url'] + edit_part + quote(settings['branch'], safe='') + '/' + quote(reviewed['directory'] + '/' + source_name)
    write_json(output / MANIFEST, {
        'version':1, 'source_file':source_name, 'ci_layout':reviewed['ci_layout'],
        'handout':bool(settings.get('handout')), 'edit_url':edit,
        'files':{p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(output.rglob('*')) if p.is_file()}})


def publish(settings, confirmed=False, deploy=False):
    from .publish import request_deployment
    reviewed = plan(settings)
    if not confirmed and input('Commit and push source + assets for CI? [y/N] ').strip().lower() != 'y':
        print('Cancelled; target unchanged')
        return None
    repo, remote, branch = settings['repo'], settings['remote'], settings['branch']
    with tempfile.TemporaryDirectory(prefix='matsugit-source-') as temporary:
        bundle = Path(temporary) / 'bundle'
        prepare(settings, bundle, reviewed)
        if plan(settings)['fingerprint'] != reviewed['fingerprint']:
            raise Error('Source or target changed while preparing; review again')
        git(repo, 'fetch', remote, branch)
        upstream = git(repo, 'rev-parse', 'FETCH_HEAD')
        if git(repo, 'rev-list', '--count', f'{upstream}..HEAD') != '0':
            raise Error('Target has unpublished/divergent commits; publish them separately first')
        git(repo, 'merge', '--ff-only', upstream)
        updated = plan(settings)
        if any(updated[key] != reviewed[key] for key in reviewed if key not in ('revision', 'fingerprint')):
            raise Error('Source or publishing target changed during pull; review again')
        dest = inside(repo, reviewed['directory'])
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(bundle, dest)
        if git(repo, 'diff', '--cached', '--name-only') or git(repo, 'rev-parse', 'HEAD') != updated['revision']:
            raise Error('Git state changed; source bundle retained locally, not committed')
        git(repo, 'add', '--', reviewed['directory'])
        if not git(repo, 'diff', '--cached', '--name-only'):
            print('Source bundle is unchanged; no new commit')
            if deploy:
                request_deployment(settings, reviewed['provider'], reviewed['project_url'])
            return git(repo, 'rev-parse', 'HEAD')
        git(repo, 'commit', '-m', f"Publish {settings['slug']} source for CI", '--', reviewed['directory'])
        sha = git(repo, 'rev-parse', 'HEAD')
        if git(repo, 'remote', 'get-url', remote) != reviewed['remote']:
            raise Error('Remote changed; commit retained locally, not pushed')
        try:
            git(repo, 'push', remote, f'{sha}:refs/heads/{branch}')
        except Error as error:
            raise Error(f'Push failed; local source commit {sha} is retained in {repo}. Review it and retry git push there; no commit was discarded. {error}') from error
        print(f'Pushed source {sha}. CI build/deployment is not yet verified.', flush=True)
        if deploy:
            request_deployment(settings, reviewed['provider'], reviewed['project_url'])
        return sha
