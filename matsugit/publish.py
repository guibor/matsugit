"""Scoped publication; never enable hosting or repair a user's Git state."""

import hashlib
import html
from pathlib import Path
import gzip
import re
import shutil
import tempfile
from urllib.parse import quote

from .core import Error, git, inside, read_json, render, run
from .compat import existing


def identity(repo, remote):
    url = git(repo, "remote", "get-url", remote)
    match = re.fullmatch(r"(?:https://|ssh://git@|git@)([^/:]+)[:/]([^\s?#]+?)(?:\.git)?", url)
    if not match or "@" in match[1] or "/" not in match[2]:
        raise Error("Use a credential-free HTTPS or git@ remote for publishing")
    host, project = match.groups()
    return host, project, f"https://{host}/{project}"


def preflight(settings, paths=None, *, renderer_paths=()):
    repo = settings["repo"]
    branch = settings["branch"]
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve():
        raise Error("--repo must be the checkout root")
    if git(repo, "branch", "--show-current") != branch:
        raise Error(f"Switch the target checkout to {branch} first")
    gitdir = Path(git(repo, 'rev-parse', '--absolute-git-dir'))
    if any((gitdir / name).exists() for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD',
                                                  'rebase-merge', 'rebase-apply', 'sequencer')):
        raise Error(f'Finish the in-progress Git operation in {repo}; nothing published')
    # Rendered output also regenerates the common site index from sibling manifests.
    scope = list(paths) if paths is not None else [settings['site_dir']]
    if settings['source'].is_relative_to(repo):
        scope.append(str(settings['source'].relative_to(repo)))
    changes = git(repo, '--literal-pathspecs', 'status', '--porcelain', '--untracked-files=all', '--', *scope)
    if renderer_paths:
        # Never exempt indexed changes. Bytecode under the renderer is generated
        # locally and is not part of the document bundle we stage or replace.
        tracked = git(repo, '--literal-pathspecs', 'status', '--porcelain', '--untracked-files=no', '--', *renderer_paths)
        untracked = git(repo, '--literal-pathspecs', 'ls-files', '--others', '--exclude-standard',
                        '--exclude=**/__pycache__/*.pyc', '--', *renderer_paths)
        changes = '\n'.join(filter(None, (changes, tracked, untracked)))
    if changes:
        raise Error(f'Publishing would use or replace paths with local changes in {repo}:\n{changes}\n'
                    'Reconcile these paths only; nothing stashed or published.')
    return git(repo, "rev-parse", "HEAD")


def fast_forward(repo, upstream, destination):
    if git(repo, 'rev-parse', 'HEAD') == upstream:
        return
    if git(repo, '--literal-pathspecs', 'diff', '--name-only', 'HEAD', upstream, '--', destination):
        raise Error(f'The remote changed {destination} since the target checkout was updated. Review that change before publishing; nothing replaced.')
    if git(repo, 'diff', '--cached', '--name-only'):
        raise Error(f'Target {repo} needs a fast-forward and has staged work. Finish the staged commit or reconcile the branch first.')
    git(repo, '-c', 'merge.autoStash=false', 'merge', '--ff-only', '--no-overwrite-ignore', upstream)


def check_destination(dest, source):
    if not dest.exists():
        return
    manifest_path = existing(dest / "matsugit-manifest.json", dest / "folioforge-manifest.json")
    if not manifest_path.is_file():
        raise Error(f"Refusing to replace an unowned directory: {dest}")
    manifest = read_json(manifest_path)
    source_name = manifest.get('source_file', 'source.md')
    if source_name not in ('source.md', 'source.org'):
        raise Error('Unknown editable source format')
    published_source = dest / source_name
    if manifest.get("version") != 1 or not published_source.is_file():
        raise Error("Unknown or incomplete matsugit output")
    digest = hashlib.sha256(published_source.read_bytes()).hexdigest()
    if digest != manifest["source_sha256"] and source != published_source.resolve():
        raise Error(f"Published source was edited. Reconcile {published_source} with the local source before publishing")
    if source_name == 'source.org' and manifest.get('normalized_sha256'):
        normalized = dest / 'source.md'
        if not normalized.is_file() or hashlib.sha256(normalized.read_bytes()).hexdigest() != manifest['normalized_sha256']:
            raise Error('Generated source.md was edited; reconcile those edits into source.org before publishing')
    for path in dest.rglob("*"):
        if path.is_symlink() or any(p.startswith(".") for p in path.relative_to(dest).parts):
            raise Error(f"Unexpected hidden file or symlink in output: {path}")
        if path.is_file() and str(path.relative_to(dest)) not in [*manifest.get("files", []), manifest_path.name]:
            raise Error(f"Unmanaged file in output; move it before republishing: {path}")


def site_index(site):
    entries = sorted({p.parent for pattern in ('*/matsugit-manifest.json', '*/folioforge-manifest.json')
                      for p in site.glob(pattern)})
    links = "\n".join(f'<li><a href="{quote(p.name)}/index.html">{html.escape(p.name)}</a></li>' for p in entries)
    (site / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Documents</title><h1>Documents</h1><ul>' + links + '</ul>', encoding="utf-8")


def publish(settings, confirmed=False, deploy=False):
    if settings.get('move_source') and settings.get('build', 'local') != 'ci':
        raise Error('Move-and-link requires Source to CI, not rendered-output publication')
    if settings.get('build', 'local') == 'ci':
        from .source_ci import publish as publish_source
        return publish_source(settings, confirmed, deploy)
    repo = settings["repo"]
    remote, branch = settings["remote"], settings["branch"]
    preflight(settings)
    host, project, base = identity(repo, remote)
    original_remote = git(repo, 'remote', 'get-url', remote)
    if settings.get('expected_remote') and git(repo, 'remote', 'get-url', remote) != settings['expected_remote']:
        raise Error('Target remote does not match expected_remote; nothing published')
    subdir = str(Path(settings["site_dir"]) / settings["slug"])
    dest = inside(repo, subdir)
    check_destination(dest, settings["source"])
    site = inside(repo, settings["site_dir"])
    site_marker = existing(site / 'matsugit-site.json', site / 'folioforge-site.json')
    if (site / "index.html").exists() and not site_marker.is_file():
        raise Error("Refusing to overwrite an unowned site index")
    source_digest = hashlib.sha256(settings["source"].read_bytes()).hexdigest()
    provider = settings.get('provider', 'github' if host == 'github.com' else 'gitlab')
    edit_part = "/edit/" if provider == "github" else "/-/edit/"
    source_name = 'source.org' if settings['source'].suffix.lower() == '.org' else 'source.md'
    edit = base + edit_part + quote(branch, safe="") + "/" + quote(subdir + '/' + source_name)
    with tempfile.TemporaryDirectory(prefix="matsugit-render-") as temp:
        artifact = Path(temp) / "rendered"
        render(settings, artifact, edit_url=edit)
        print(f"Ready: document + slides + editable source -> {base}/{subdir}", flush=True)
        if not confirmed:
            if input("Commit and push these artifacts? [y/N] ").strip().lower() != "y":
                print("Cancelled; target checkout unchanged")
                return None
        preflight(settings)
        if git(repo, 'remote', 'get-url', remote) != original_remote:
            raise Error('Remote changed during rendering; nothing published')
        git(repo, "fetch", remote, branch)
        upstream = git(repo, "rev-parse", "FETCH_HEAD")
        ahead = git(repo, "rev-list", "--count", f"{upstream}..HEAD")
        if ahead != "0":
            raise Error("Target has unpublished/divergent commits; publish them separately first")
        fast_forward(repo, upstream, subdir)
        revision = preflight(settings)
        if hashlib.sha256(settings["source"].read_bytes()).hexdigest() != source_digest:
            raise Error("Source changed during rendering/pull; rerun to render the new version")
        check_destination(dest, settings["source"])
        site = inside(repo, settings["site_dir"])
        site_marker = existing(site / 'matsugit-site.json', site / 'folioforge-site.json')
        if (site / "index.html").exists() and not site_marker.is_file():
            raise Error("Unowned site index after pull; no output replaced")
        # Replacing only a managed artifact folder; unknown sibling files are untouched.
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(artifact, dest)
        site_index(site)
        site_marker.write_text('{"version": 1}\n')
        if git(repo, '--literal-pathspecs', 'diff', '--cached', '--name-only', '--', settings['site_dir']) or git(repo, "rev-parse", "HEAD") != revision:
            raise Error("Git state changed while rendering; outputs retained, not committed")
        paths = [subdir, str(Path(settings["site_dir"]) / "index.html"), str(site_marker.relative_to(repo))]
        git(repo, '--literal-pathspecs', "add", "--", *paths)
        git(repo, '--literal-pathspecs', "commit", "--only", "-m", f"Publish {settings['slug']} document and slides", "--", *paths)
        sha = git(repo, "rev-parse", "HEAD")
        if git(repo, 'remote', 'get-url', remote) != original_remote:
            raise Error('Remote changed; local publication commit retained, not pushed')
        git(repo, "push", remote, f"{sha}:refs/heads/{branch}")
        print(f"Pushed {sha}. Hosting availability has not been verified.", flush=True)
        from .links import report_published
        report_published(dict(settings, ci_layout='native'), dest / source_name, base, provider)
        if deploy:
            request_deployment(settings, provider, base)
        return sha


def request_deployment(settings, provider, base):
    repo, branch = settings['repo'], settings['branch']
    if provider == 'github':
        workflow = existing(repo / '.github/workflows/matsugit-pages.yml',
                            repo / '.github/workflows/folioforge-pages.yml').name
        run(['gh', 'workflow', 'run', workflow, '--ref', branch, '--repo', base])
    else:
        run(['glab', 'ci', 'run', '--branch', branch], cwd=repo)
    print('Deployment requested; check CI before sharing a URL.', flush=True)


def setup_ci(settings, provider):
    repo = settings["repo"]
    templates = Path(__file__).parent / "templates"
    mathjax = Path(__file__).parent / "runtime/mathjax-tex-svg.js"
    if not mathjax.is_file():
        mathjax = mathjax.with_suffix('.js.gz')
    workflow = ".github/workflows/matsugit-pages.yml" if provider == "github" else "matsugit.gitlab-ci.yml"
    legacy = workflow.replace('matsugit', 'folioforge')
    if (repo / legacy).exists() or (repo / '.folioforge-ci').exists():
        raise Error('Existing legacy CI retained. See docs/migration.org before changing deployment files.')
    sources = {
        workflow: templates / (provider + ".yml"),
        ".matsugit-ci/compat.py": Path(__file__).parent / "compat.py",
        ".matsugit-ci/core.py": Path(__file__).parent / "core.py",
        ".matsugit-ci/source.py": Path(__file__).parent / "source.py",
        ".matsugit-ci/export_boundary.py": Path(__file__).parent / "export_boundary.py",
        ".matsugit-ci/sugar.py": Path(__file__).parent / "sugar.py",
        ".matsugit-ci/layout.py": Path(__file__).parent / "layout.py",
        ".matsugit-ci/document.py": Path(__file__).parent / "document.py",
        ".matsugit-ci/components.py": Path(__file__).parent / "components.py",
        ".matsugit-ci/canvas.py": Path(__file__).parent / "canvas.py",
        ".matsugit-ci/relationships.py": Path(__file__).parent / "relationships.py",
        ".matsugit-ci/charts.py": Path(__file__).parent / "charts.py",
        ".matsugit-ci/diagrams.py": Path(__file__).parent / "diagrams.py",
        ".matsugit-ci/vega.py": Path(__file__).parent / "vega.py",
        ".matsugit-ci/handout.py": Path(__file__).parent / "handout.py",
        ".matsugit-ci/build.py": templates / "build.py",
        ".matsugit-ci/runtime/MATSUGIT-LICENSE": Path(__file__).parent / "runtime/MATSUGIT-LICENSE",
        ".matsugit-ci/runtime/media.js": Path(__file__).parent / "runtime/media.js",
        ".matsugit-ci/runtime/fit.js": Path(__file__).parent / "runtime/fit.js",
        ".matsugit-ci/runtime/canvas.js": Path(__file__).parent / "runtime/canvas.js",
        ".matsugit-ci/runtime/canvas.css": Path(__file__).parent / "runtime/canvas.css",
        ".matsugit-ci/runtime/annotations.js": Path(__file__).parent / "runtime/annotations.js",
        ".matsugit-ci/runtime/media.css": Path(__file__).parent / "runtime/media.css",
        ".matsugit-ci/runtime/layout.css": Path(__file__).parent / "runtime/layout.css",
        ".matsugit-ci/runtime/document-fold.js": Path(__file__).parent / "runtime/document-fold.js",
        ".matsugit-ci/runtime/document-fold.css": Path(__file__).parent / "runtime/document-fold.css",
        ".matsugit-ci/runtime/math-config.js": Path(__file__).parent / "runtime/math-config.js",
        ".matsugit-ci/runtime/mathjax-tex-svg.js": mathjax,
        ".matsugit-ci/runtime/MATHJAX-LICENSE": Path(__file__).parent / "runtime/MATHJAX-LICENSE",
        ".matsugit-ci/runtime/MATHJAX-NOTICE.txt": Path(__file__).parent / "runtime/MATHJAX-NOTICE.txt",
    }
    for name in ('package.json', 'package-lock.json', 'render.mjs'):
        sources['.matsugit-ci/diagram_runtime/' + name] = Path(__file__).parent / 'diagram_runtime' / name
    for name in sources:
        if (repo / name).exists():
            raise Error(f"Refusing to overwrite existing CI file: {name}")
    for name, source in sources.items():
        path = repo / name
        if not path.resolve().is_relative_to(repo.resolve()):
            raise Error("CI path escapes repository")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Compressed assets are written out expanded; CI loads the plain file.
        text = (gzip.decompress(source.read_bytes()).decode("utf-8") if source.suffix == ".gz"
                else source.read_text(encoding="utf-8"))
        # JSON quoting is valid YAML and Python, including spaces in the directory.
        import json
        text = text.replace("__SITE_DIR__", json.dumps(settings["site_dir"]))
        path.write_text(text, encoding="utf-8")
    print("CI files created, not committed or pushed. Review them and the intended site visibility.")
    if provider == "github":
        print("Then select Settings > Pages > GitHub Actions. Private repository does NOT imply private Pages.")
    else:
        print("Include matsugit.gitlab-ci.yml in your existing .gitlab-ci.yml; review Pages access control.")
