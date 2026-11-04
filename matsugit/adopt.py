"""Move exact source/asset bytes into a checkout, retaining local symlinks.

No Git staging, commits or network access. Refuse ambiguous cross-folder
dependencies rather than silently breaking links or moving an entire project.
"""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import unquote, urlsplit

from .core import Error, ResourceHTML, inside, git
from .git_sync import fingerprint


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(source, root=None):
    from .converter import converter
    from .source import read
    source = Path(source).resolve(strict=True)
    boundary = Path(root).resolve(strict=True) if root else source.parent
    fmt = {'.md':'markdown', '.markdown':'markdown', '.org':'org'}.get(source.suffix.lower())
    if not fmt:
        raise Error('Move-and-link supports Markdown and Org, without format conversion')
    files = {source}

    def resource(value):
        url = urlsplit(value)
        if value.startswith('#') or url.scheme in ('http', 'https', 'mailto', 'tel'):
            return value
        raw = Path(unquote(url.path))
        if url.scheme or url.netloc or not url.path or raw.is_absolute() or (not root and any(p.startswith('.') for p in raw.parts)):
            raise Error(f'Move-and-link needs self-contained relative assets (no parent/hidden paths): {value}')
        lexical = Path(os.path.abspath(source.parent / raw))
        path = lexical.resolve()
        if path != lexical or not path.is_file():
            raise Error(f'Missing or symlinked attachment: {value}')
        if not path.is_relative_to(boundary) or any(p.startswith('.') for p in path.relative_to(boundary).parts):
            raise Error(f'Attachment outside the source boundary or hidden: {value}')
        if root and path.suffix.lower() in ('.md', '.markdown', '.org'):
            return value  # Existing document links are not additional files to stage.
        if path == source:
            raise Error('A self-link naming the file cannot be relocated without rewriting it; use a #section link')
        if path.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.svg','.webp','.pdf','.csv','.txt','.html','.htm','.mp4','.webm','.mp3'}:
            raise Error(f'Move-and-link cannot relocate linked documents or this attachment: {value}. Keep copy export or organize a self-contained folder first')
        files.add(path)
        return value

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            kind = node.get('t')
            if kind in ('Image', 'Link'):
                resource(node['c'][-1][0])
            if kind == 'Div' and 'canvas' in node['c'][0][1]:
                resource(dict(node['c'][0][2])['src'])
            if kind in ('RawBlock', 'RawInline') and node['c'][0] == 'html':
                parser = ResourceHTML(resource)
                parser.feed(node['c'][1]); parser.close()
            for value in node.values():
                visit(value)

    visit(read(source.read_text(encoding='utf-8'), fmt, converter()))
    return sorted(files)


def plan(source, repo, destination):
    original = Path(source).expanduser().absolute()
    source = original.resolve(strict=True)
    repo = Path(repo).expanduser().resolve(strict=True)
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise Error('Choose a checkout root')
    destination = inside(repo, destination)
    expected = ('.org',) if source.suffix.lower() == '.org' else ('.md', '.markdown')
    if destination.suffix.lower() not in expected:
        raise Error('Move-and-link preserves source format; choose the same file extension')
    if destination == source:
        raise Error('Already using the canonical source; publish in place')
    if original != source or source.is_relative_to(repo):
        raise Error('Already linked or inside the target checkout; do not move it again')
    moves = []
    for path in inventory(source):
        if path.is_relative_to(repo):
            raise Error('An attachment is already in the target repo; do not relocate it implicitly')
        target = destination if path == source else destination.parent / path.relative_to(source.parent)
        relative = target.relative_to(repo)
        if inside(repo, relative) != target or target.exists() or target.is_symlink():
            raise Error(f'Refusing to overwrite a destination or follow a target symlink: {target}')
        if any((repo / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts))):
            raise Error('Destination parent is a symlink')
        if git(repo, 'ls-files', '--', relative.as_posix()):
            raise Error(f'Destination is tracked but deleted locally: {relative}')
        moves.append(dict(source=str(path), destination=str(target), sha256=digest(path)))
    if len({m['destination'] for m in moves}) != len(moves):
        raise Error('Source filename collides with an attachment')
    data = dict(source=str(source), destination=str(destination), repo=str(repo), moves=moves)
    data['fingerprint'] = fingerprint(data)
    return data


def apply(reviewed):
    """Install all bytes before changing originals; retain recovery copies on error."""
    current = plan(reviewed['source'], reviewed['repo'],
                   str(Path(reviewed['destination']).relative_to(reviewed['repo'])))
    if current != reviewed:
        raise Error('Source/assets changed since review; nothing moved')
    installed, backups = [], []
    try:
        for move in reviewed['moves']:
            source, target = Path(move['source']), Path(move['destination'])
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as out:
                installed.append(move)
                with source.open('rb') as inp:
                    shutil.copyfileobj(inp, out)
            shutil.copymode(source, target)
            if digest(target) != move['sha256'] or digest(source) != move['sha256']:
                raise Error('Source changed while copying; original retained')
        for move in reviewed['moves']:
            source, target = Path(move['source']), Path(move['destination'])
            if source.is_symlink() or digest(source) != move['sha256']:
                raise Error('Source changed during relocation')
            fd, name = tempfile.mkstemp(prefix='.matsugit-original-', dir=source.parent)
            os.close(fd)
            backup = Path(name)
            shutil.copy2(source, backup)
            backups.append((move, backup))
            link = Path(name + '.link')
            try:
                link.symlink_to(os.path.relpath(target, source.parent))
                if digest(source) != move['sha256'] or digest(backup) != move['sha256']:
                    raise Error('Source changed during relocation; recovery copy retained')
                os.replace(link, source)
            finally:
                link.unlink(missing_ok=True)
        for _, backup in backups:
            try:
                backup.unlink()
            except OSError:
                pass  # A retained recovery copy is preferable to undoing a completed move.
        return reviewed
    except (Exception, KeyboardInterrupt) as error:
        # Never overwrite a concurrently changed file, even during rollback.
        for move, backup in backups:
            source, target = Path(move['source']), Path(move['destination'])
            if source.is_symlink() and source.resolve() == target:
                os.replace(backup, source)
        for move in installed:
            target = Path(move['destination'])
            if target.is_file() and not target.is_symlink() and digest(target) == move['sha256']:
                target.unlink()
        retained = [str(backup) for _, backup in backups if backup.exists()]
        raise Error(f'Relocation stopped; originals/recovery copies retained. {error}'
                    + (f' Recovery: {retained}' if retained else '')) from error
