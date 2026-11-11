"""Versioned, explicitly trusted renderer bundles; no document publication or CI edits."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

from .core import Error, git, read_json, run
from .compat import env, existing

VENDOR = '.matsugit-renderer'
LOCK = 'matsugit-renderer.lock.json'
LEGACY_VENDOR = '.folioforge-renderer'
LEGACY_LOCK = 'folioforge-renderer.lock.json'
SHA = re.compile(r'^[0-9a-f]{64}$')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def safe_name(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise Error('Invalid bundle path')
    p = PurePosixPath(value)
    if not p.parts or p.is_absolute() or any(x.startswith('.') for x in p.parts) or str(p) != value:
        raise Error(f'Invalid bundle path: {value}')
    return value


def target_path(repo, name):
    path = repo / name
    for parent in [path, *path.parents]:
        if parent == repo:
            break
        if parent.is_symlink():
            raise Error(f'Symlink in managed path: {name}')
    if not path.resolve().is_relative_to(repo):
        raise Error(f'Managed path escapes checkout: {name}')
    return path


def wrapper(destination):
    return ("# Managed by matsugit renderer updates.\n"
            "from pathlib import Path\nimport runpy\nimport sys\n"
            "root = Path(__file__).resolve().parents[1]\n"
            f"entry = root / {VENDOR!r} / {destination!r}\n"
            "sys.path.insert(0, str(entry.parent))\n"
            "runpy.run_path(str(entry), run_name='__main__')\n").encode()


def settings(path=None):
    path = Path(path or env('MATSUGIT_UPDATE_CONFIG', existing(
        '~/.config/matsugit/updates.json', '~/.config/folioforge/updates.json'))).expanduser()
    if not path.is_file():
        raise Error(f'No update configuration at {path}. See README: Renderer updates.')
    value = read_json(path)
    if value.get('schema') != 1 or not isinstance(value.get('projects'), list):
        raise Error('Unsupported update configuration')
    # This local configuration is the explicit trust boundary for executable releases.
    for project in value['projects']:
        project['repo'] = Path(project['repo']).expanduser().resolve()
    return value


def select(config, all_projects=False, repo=None):
    if not all_projects and repo is None:
        raise Error('Select --all or --repo PATH')
    selected = config['projects'] if all_projects else [
        p for p in config['projects'] if p['repo'] == Path(repo).expanduser().resolve()]
    if not selected:
        raise Error('No configured project matches --repo')
    return selected


class Catalog:
    def __init__(self, config, cache):
        self.repo = Path(cache)
        git(self.repo.parent, 'init', '--bare', str(self.repo))
        git(self.repo, 'fetch', '--depth=1', config['repository'], config.get('ref', 'main'))
        self.commit = git(self.repo, 'rev-parse', 'FETCH_HEAD')
        self.url = config['repository']
        self.data = json.loads(self.read(safe_name(config['catalog'])))
        if self.data.get('schema') != 1:
            raise Error('Unknown release catalog schema')

    def read(self, path):
        result = subprocess.run(['git', '-C', str(self.repo), 'show', f'{self.commit}:{path}'],
                                capture_output=True, check=False)
        if result.returncode:
            raise Error(f'Release file not found: {path}')
        if len(result.stdout) > 16 * 1024 * 1024:
            raise Error(f'Release file too large: {path}')
        return result.stdout

    def release(self, bundle, version=None):
        channel = self.data['bundles'][bundle]
        version = version or channel['latest']
        item = channel['versions'][version]
        manifest_path = safe_name(item['manifest'])
        raw = self.read(manifest_path)
        if digest(raw) != item['sha256']:
            raise Error('Release manifest checksum mismatch')
        manifest = json.loads(raw)
        if (manifest.get('schema'), manifest.get('bundle'), manifest.get('version')) != (1, bundle, version):
            raise Error('Release identity mismatch')
        prefix = str(PurePosixPath(manifest_path).parent)
        files = {}
        if not manifest.get('files'):
            raise Error('Empty renderer release')
        for name, expected in manifest['files'].items():
            safe_name(name)
            if not isinstance(expected, str) or not SHA.fullmatch(expected):
                raise Error('Invalid release checksum')
            listing = git(self.repo, 'ls-tree', self.commit, '--', f'{prefix}/{name}').split()
            mode = listing[0] if listing else ''
            if mode not in ('100644', '100755'):
                raise Error(f'Release symlink or non-file: {name}')
            content = self.read(f'{prefix}/{name}')
            if digest(content) != expected:
                raise Error(f'Release checksum mismatch: {name}')
            files[f'{VENDOR}/{name}'] = content
        for name, destination in manifest.get('entrypoints', {}).items():
            safe_name(name); safe_name(destination)
            if len(PurePosixPath(name).parts) != 2 or not name.startswith('scripts/') or not name.endswith('.py'):
                raise Error('Entrypoints must be Python scripts directly inside scripts/')
            if destination not in manifest['files']:
                raise Error('Entrypoint references a missing renderer file')
            files[name] = wrapper(destination)
        reference = dict(bundle=bundle, version=version, manifest_sha256=digest(raw),
                         source_commit=self.commit, source_repository=self.url)
        return manifest, reference, files


def installed(repo):
    current, legacy = target_path(repo, LOCK), target_path(repo, LEGACY_LOCK)
    if current.exists() and legacy.exists():
        raise Error('Both renderer lockfiles exist; reconcile them before updating')
    path = existing(current, legacy)
    if not path.exists():
        return None
    value = read_json(path)
    if value.get('schema') != 1:
        raise Error(f'Unknown installed renderer state in {repo}')
    for name in value['files']:
        vendor = next((p for p in (VENDOR, LEGACY_VENDOR) if name.startswith(p + '/')), None)
        if not vendor:
            safe_name(name)
            if not name.startswith('scripts/'):
                raise Error('Invalid managed path in lockfile')
        else:
            safe_name(name[len(vendor)+1:])
    return value


def verify_installed(repo, lock):
    for name, expected in lock['files'].items():
        p = target_path(repo, name)
        if not p.is_file() or digest(p.read_bytes()) != expected:
            raise Error(f'Installed renderer was edited: {name}. Preserve/reconcile that edit before updating.')
    for prefix in (VENDOR, LEGACY_VENDOR):
        vendor = target_path(repo, prefix)
        if not vendor.exists():
            continue
        for p in vendor.rglob('*'):
            if p.is_symlink():
                raise Error('Symlink inside installed renderer')
            if p.is_file() and p.relative_to(repo).as_posix() not in lock['files']:
                # Python bytecode is disposable, but no other unmanaged files are deleted.
                if '__pycache__' not in p.parts or p.suffix != '.pyc':
                    raise Error(f'Unmanaged file inside renderer: {p}')


def check_repo(project):
    repo = project['repo']
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo.resolve():
        raise Error(f'Not a checkout root: {repo}')
    branch = project.get('branch', 'main'); remote = project.get('remote', 'origin')
    if git(repo, 'branch', '--show-current') != branch:
        raise Error(f'{repo.name}: switch to {branch} first')
    if 'origins' in project and git(repo, 'remote', 'get-url', remote) not in project['origins']:
        raise Error(f'{repo.name}: remote does not match configured origins')
    if git(repo, 'diff', '--cached', '--name-only'):
        raise Error(f'{repo.name}: staged changes exist; finish that commit first')
    return repo, remote, branch


@contextmanager
def update_lock(repo):
    # Serialize with older installations as well; this lock is not branding.
    path = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'folioforge-update.lock'))
    if os.name == 'nt':
        import msvcrt
        # Lock the first byte, including beyond EOF; never truncate another lock.
        with path.open('a+b') as stream:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                import errno
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                raise Error('Another matsugit update is running for this checkout') from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    with path.open('w') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Error('Another matsugit update is running for this checkout') from exc
        yield


def prepare(project, catalog, rollback=False, version=None):
    repo, remote, branch = check_repo(project)
    previous = installed(repo)
    if previous:
        verify_installed(repo, previous)
    history = previous.get('history', []) if previous else []
    if rollback:
        if not history:
            raise Error(f'{repo.name}: no previous managed release to roll back to')
        version = history[-1]['version']
    manifest, reference, files = catalog.release(project['bundle'], version)
    if previous and previous['release']['bundle'] != project['bundle']:
        raise Error('Installed bundle differs from configuration')
    if previous and previous['release']['version'] == reference['version']:
        if previous['release']['manifest_sha256'] != reference['manifest_sha256']:
            raise Error('An existing release version was modified; publish a new version')
        if not target_path(repo, LEGACY_LOCK).exists():
            return dict(project=project, unchanged=True, previous=previous)
    if rollback and history[-1]['manifest_sha256'] != reference['manifest_sha256']:
        raise Error('Previous release checksum changed; cannot roll back')
    old_paths = set(previous['files']) if previous else set()
    paths = set(files) | old_paths | {LOCK}
    if previous and target_path(repo, LEGACY_LOCK).exists():
        paths.add(LEGACY_LOCK)
    for name in paths:
        p = target_path(repo, name)
        if not previous and p.exists():
            allowed = manifest.get('adopt', {}).get(name, [])
            if not p.is_file() or digest(p.read_bytes()) not in allowed:
                raise Error(f'{repo.name}: existing {name} is not an approved migration baseline; no files changed')
    if not previous and target_path(repo, VENDOR).exists():
        raise Error('Refusing to adopt an existing unmanaged renderer directory')
    if git(repo, 'diff', 'HEAD', '--name-only', '--', *sorted(paths)):
        raise Error(f'{repo.name}: local edits in renderer files; commit/reconcile them before updating')
    same_release = previous and all(previous['release'][key] == reference[key]
                                    for key in ('bundle', 'version', 'manifest_sha256'))
    next_history = history[:-1] if rollback else history + ([previous['release']] if previous and not same_release else [])
    lock = dict(schema=1, release=reference, history=next_history[-20:],
                files={name:digest(data) for name,data in files.items()})
    files[LOCK] = encoded(lock)
    return dict(project=project, unchanged=False, previous=previous, files=files,
                paths=paths, release=reference, manifest=manifest, head=git(repo,'rev-parse','HEAD'))


def check_release(plan):
    if plan['unchanged']:
        return
    with tempfile.TemporaryDirectory(prefix='matsugit-release-check-') as tmp:
        root = Path(tmp)
        for name, data in plan['files'].items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            if name.endswith('.py'):
                compile(data, name, 'exec')
        check = plan['manifest'].get('check')
        if check:
            safe_name(check)
            if check not in plan['manifest']['files']:
                raise Error('Release check is not in verified files')
            print(run([sys.executable, root / VENDOR / check], cwd=root).strip())


def pending_owned_commit(repo, upstream, lock):
    if not lock or git(repo,'rev-list','--count',f'{upstream}..HEAD') != '1':
        return False
    if git(repo,'rev-parse','HEAD^') != upstream:
        return False
    expected = f"matsugit renderer: {lock['release']['bundle']} {lock['release']['version']}"
    if git(repo,'log','-1','--format=%s') not in (expected, expected.replace('matsugit', 'Folioforge', 1)):
        return False
    names = set(git(repo,'diff','--name-only',upstream,'HEAD').splitlines())
    return all(name.startswith((VENDOR + '/', LEGACY_VENDOR + '/')) or name in lock['files']
               or name in (LOCK, LEGACY_LOCK) for name in names)


def synchronize(project, dry_run):
    repo, remote, branch = check_repo(project)
    git(repo,'fetch',remote,branch)
    upstream = git(repo,'rev-parse','FETCH_HEAD')
    if git(repo,'rev-list','--count',f'{upstream}..HEAD') != '0':
        lock = installed(repo)
        if lock:
            verify_installed(repo,lock)
        if pending_owned_commit(repo,upstream,lock):
            if not dry_run:
                git(repo,'push',remote,f'HEAD:refs/heads/{branch}')
            print(f'{repo.name}: ' + ('would retry' if dry_run else 'retried') + ' previous renderer push')
        else:
            raise Error(f'{repo.name}: unpublished/divergent commits; publish them separately first')
    elif git(repo,'rev-parse','HEAD') != upstream:
        if dry_run:
            raise Error(f'{repo.name}: behind remote; run git pull --ff-only before previewing the update')
        git(repo,'merge','--ff-only',upstream)


def apply_plan(plan):
    repo, remote, branch = check_repo(plan['project'])
    if plan['unchanged']:
        print(f"{repo.name}: already at {plan['previous']['release']['version']}")
        return
    if git(repo,'rev-parse','HEAD') != plan['head']:
        raise Error('Checkout changed during release validation; rerun')
    if plan['previous']:
        verify_installed(repo,plan['previous'])
    if git(repo,'diff','HEAD','--name-only','--',*sorted(plan['paths'])):
        raise Error('Renderer changed during validation; rerun')
    # Unknown files were rejected above. Existing project documents/CI stay untouched.
    for name in sorted(plan['paths'] - set(plan['files'])):
        target_path(repo,name).unlink()
    for name, data in plan['files'].items():
        p = target_path(repo,name); p.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as tmp:
            tmp.write(data); temporary = tmp.name
        os.replace(temporary,p)
    paths = sorted(plan['paths'])
    message = f"matsugit renderer: {plan['release']['bundle']} {plan['release']['version']}"
    # --only prevents unrelated staged changes from entering this commit.
    git(repo,'add','--',*paths)
    git(repo,'commit','--only','-m',message,'--',*paths)
    try:
        git(repo,'push',remote,f'HEAD:refs/heads/{branch}')
    except Error as exc:
        raise Error(f'{repo.name}: renderer committed, push failed. Rerun the same command to retry. {exc}') from exc
    print(f"{repo.name}: installed and pushed {plan['release']['version']}")
    url = git(repo,'remote','get-url',remote)
    match = re.match(r'(?:git@|https://)([^/:]+)[:/](.+?)(?:\.git)?$',url)
    if match and 'gitlab' in match[1]:
        print(f'https://{match[1]}/{match[2]}/-/pipelines (retain existing manual deployment gates)')
    print('Push complete; deployment has not been verified.')


def manage(command, config_path=None, all_projects=False, repo=None, dry_run=False, version=None):
    cfg = settings(config_path)
    projects = select(cfg,all_projects,repo)
    if command == 'status':
        for p in projects:
            if not p['repo'].is_dir():
                print(f"{p['name']}: checkout not present at {p['repo']}"); continue
            lock = installed(p['repo'])
            if lock:
                verify_installed(p['repo'],lock)
            print(f"{p['name']}: " + (lock['release']['version'] if lock else 'not managed yet'))
        return
    missing = [p for p in projects if not p['repo'].is_dir()]
    if missing:
        raise Error('Checkout not found: ' + ', '.join(str(p['repo']) for p in missing))
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='matsugit-catalog-') as tmp:
        for p in sorted(projects,key=lambda p:str(p['repo'])):
            stack.enter_context(update_lock(p['repo']))
        catalog = Catalog(cfg,Path(tmp)/'catalog.git')
        for p in projects:
            synchronize(p,dry_run)
        plans = [prepare(p,catalog,command=='rollback',version) for p in projects]
        for plan in plans:
            check_release(plan)
        # All selected projects pass validation before any renderer is installed.
        for plan in plans:
            if dry_run:
                label = 'unchanged' if plan['unchanged'] else plan['release']['version']
                print(f"{plan['project']['name']}: would install {label}; no renderer files, commits or pushes changed")
            else:
                apply_plan(plan)
