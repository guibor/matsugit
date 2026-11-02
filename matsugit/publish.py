"""Scoped publication; never enable hosting or repair a user's Git state."""

import hashlib
import html
from pathlib import Path
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


def preflight(settings):
    repo = settings["repo"]
    branch = settings["branch"]
    if git(repo, "rev-parse", "--show-toplevel") != str(repo):
        raise Error("--repo must be the checkout root")
    if git(repo, "branch", "--show-current") != branch:
        raise Error(f"Switch the target checkout to {branch} first")
    if git(repo, "status", "--porcelain"):
        raise Error("Target checkout has local changes; commit or move them first (nothing was stashed)")
    return git(repo, "rev-parse", "HEAD")


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
    repo = settings["repo"]
    remote, branch = settings["remote"], settings["branch"]
    preflight(settings)
    host, project, base = identity(repo, remote)
    subdir = str(Path(settings["site_dir"]) / settings["slug"])
    dest = inside(repo, subdir)
    check_destination(dest, settings["source"])
    site = inside(repo, settings["site_dir"])
    site_marker = existing(site / 'matsugit-site.json', site / 'folioforge-site.json')
    if (site / "index.html").exists() and not site_marker.is_file():
        raise Error("Refusing to overwrite an unowned site index")
    source_digest = hashlib.sha256(settings["source"].read_bytes()).hexdigest()
    edit_part = "/edit/" if host == "github.com" else "/-/edit/"
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
        git(repo, "fetch", remote, branch)
        upstream = git(repo, "rev-parse", "FETCH_HEAD")
        ahead = git(repo, "rev-list", "--count", f"{upstream}..HEAD")
        if ahead != "0":
            raise Error("Target has unpublished/divergent commits; publish them separately first")
        git(repo, "merge", "--ff-only", upstream)
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
        if git(repo, "diff", "--cached", "--name-only") or git(repo, "rev-parse", "HEAD") != revision:
            raise Error("Git state changed while rendering; outputs retained, not committed")
        paths = [subdir, str(Path(settings["site_dir"]) / "index.html"), str(site_marker.relative_to(repo))]
        git(repo, "add", "--", *paths)
        git(repo, "commit", "-m", f"Publish {settings['slug']} document and slides", "--", *paths)
        sha = git(repo, "rev-parse", "HEAD")
        git(repo, "push", remote, f"{sha}:refs/heads/{branch}")
        print(f"Pushed {sha}. Hosting availability has not been verified.", flush=True)
        if deploy:
            if host == "github.com":
                workflow = existing(repo / '.github/workflows/matsugit-pages.yml',
                                    repo / '.github/workflows/folioforge-pages.yml').name
                run(["gh", "workflow", "run", workflow, "--ref", branch, "--repo", project])
            else:
                run(["glab", "ci", "run", "--branch", branch], cwd=repo)
            print("Deployment requested; check CI before sharing a URL.", flush=True)
        return sha


def setup_ci(settings, provider):
    repo = settings["repo"]
    templates = Path(__file__).parent / "templates"
    workflow = ".github/workflows/matsugit-pages.yml" if provider == "github" else "matsugit.gitlab-ci.yml"
    legacy = workflow.replace('matsugit', 'folioforge')
    if (repo / legacy).exists() or (repo / '.folioforge-ci').exists():
        raise Error('Existing legacy CI retained. See docs/migration.org before changing deployment files.')
    sources = {
        workflow: templates / (provider + ".yml"),
        ".matsugit-ci/compat.py": Path(__file__).parent / "compat.py",
        ".matsugit-ci/core.py": Path(__file__).parent / "core.py",
        ".matsugit-ci/source.py": Path(__file__).parent / "source.py",
        ".matsugit-ci/sugar.py": Path(__file__).parent / "sugar.py",
        ".matsugit-ci/layout.py": Path(__file__).parent / "layout.py",
        ".matsugit-ci/components.py": Path(__file__).parent / "components.py",
        ".matsugit-ci/relationships.py": Path(__file__).parent / "relationships.py",
        ".matsugit-ci/charts.py": Path(__file__).parent / "charts.py",
        ".matsugit-ci/vega.py": Path(__file__).parent / "vega.py",
        ".matsugit-ci/handout.py": Path(__file__).parent / "handout.py",
        ".matsugit-ci/build.py": templates / "build.py",
        ".matsugit-ci/runtime/media.js": Path(__file__).parent / "runtime/media.js",
        ".matsugit-ci/runtime/annotations.js": Path(__file__).parent / "runtime/annotations.js",
        ".matsugit-ci/runtime/media.css": Path(__file__).parent / "runtime/media.css",
        ".matsugit-ci/runtime/layout.css": Path(__file__).parent / "runtime/layout.css",
    }
    for name in sources:
        if (repo / name).exists():
            raise Error(f"Refusing to overwrite existing CI file: {name}")
    for name, source in sources.items():
        path = repo / name
        if not path.resolve().is_relative_to(repo.resolve()):
            raise Error("CI path escapes repository")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        # JSON quoting is valid YAML and Python, including spaces in the directory.
        import json
        text = text.replace("__SITE_DIR__", json.dumps(settings["site_dir"]))
        path.write_text(text, encoding="utf-8")
    print("CI files created, not committed or pushed. Review them and the intended site visibility.")
    if provider == "github":
        print("Then select Settings > Pages > GitHub Actions. Private repository does NOT imply private Pages.")
    else:
        print("Include matsugit.gitlab-ci.yml in your existing .gitlab-ci.yml; review Pages access control.")
