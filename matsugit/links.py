"""Where a shared deck can be opened: its slides, its reading document and its
source in the GitLab or GitHub project. Pure functions over a push receipt; the
one network lookup (the project's Pages address) lives in publication.inspect.
"""
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit


def safe(url, *, site=False):
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        parsed = urlsplit(url)
        return url if parsed.scheme in (('https', 'http') if site else ('https',)) and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def describe(repo, source, profile):
    """What a receipt needs to know to build links later. `source` is the file
    as it lives in the checkout `repo` after sharing."""
    from pathlib import Path
    path = Path(source).resolve().relative_to(Path(repo).resolve()).as_posix()
    return {'source_path': path, 'ci_layout': profile.get('ci_layout', 'native'),
            'site_dir': profile.get('site_dir') or _site_dir(repo),
            'document_url': profile.get('document_url'), 'slides_url': profile.get('slides_url')}


def _site_dir(repo):
    from pathlib import Path
    return 'folioforge-site' if (Path(repo) / 'folioforge-site').is_dir() and not (Path(repo) / 'matsugit-site').is_dir() else 'matsugit-site'


def links(receipt):
    """{slides, document, source, edit, site, project}; a key is absent when unknown."""
    result = {}
    project, branch, path = safe(receipt.get('project_url')), receipt.get('branch'), receipt.get('source_path')
    if project:
        result['project'] = project
    if project and branch and path:
        encoded = '/'.join(quote(part) for part in PurePosixPath(path).parts)
        gitlab = receipt.get('provider') != 'github'
        result['source'] = f"{project}/{'-/' if gitlab else ''}blob/{quote(branch, safe='')}/{encoded}"
        result['edit'] = f"{project}/{'-/' if gitlab else ''}edit/{quote(branch, safe='')}/{encoded}"
    site = safe(receipt.get('site_url'), site=True)
    if site:
        result['site'] = site
    if site and path:
        root = site.rstrip('/')
        folder = PurePosixPath(path).parent
        values = {'site': root, 'dir': quote(folder.as_posix()), 'slug': quote(folder.name, safe=''),
                  'path': quote(path), 'name': quote(PurePosixPath(path).stem, safe='')}
        templates = {'document': receipt.get('document_url'), 'slides': receipt.get('slides_url')}
        site_dir = receipt.get('site_dir') or 'matsugit-site'
        # The project's own CI publishes the site folder as the site root, one folder per deck.
        if receipt.get('ci_layout', 'native') == 'native' and folder.is_relative_to(site_dir):
            inside = quote(folder.relative_to(site_dir).as_posix())
            templates = {'document': templates['document'] or '{site}/' + inside + '/index.html',
                         'slides': templates['slides'] or '{site}/' + inside + '/slides.html'}
        elif receipt.get('ci_layout') == 'topics':
            # The legacy Git Pages renderer mirrors source paths under public/.
            prefix = '{site}/' + ('{dir}/' if folder != PurePosixPath('.') else '')
            templates = {'document': templates['document'] or prefix + '{name}.html',
                         'slides': templates['slides'] or prefix + '{name}-slides.html'}
        for key, template in templates.items():
            if template:
                try:
                    url = safe(template.format(**values), site=True)
                except (KeyError, IndexError, ValueError, AttributeError):
                    url = None
                if url:
                    result[key] = url
    return result


def build_step(log):
    """Which part of a running site build the log has reached. Quarto-based
    renderers print one line per output; matsugit's own prints the format."""
    step = None
    for line in log.splitlines()[-400:]:
        lower = line.lower()
        if 'rendering html' in lower or ('output created' in lower and 'slides' not in lower and '.html' in lower):
            step = 'document'
        if 'rendering revealjs' in lower or ('output created' in lower and 'slides' in lower):
            step = 'slides'
        if 'uploading artifacts' in lower or 'pages:deploy' in lower or 'deploying' in lower:
            step = 'publishing'
    return step
