"""Local ownership receipts for replacing only unchanged generated exports."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .core import Error


def digest(path):
    if path.is_symlink():
        raise Error('Export destination is a symlink; choose a regular file')
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def receipt_path(output):
    root = Path(os.environ.get('MATSUGIT_EXPORT_STATE_DIR', str(Path.home() / '.local/share/matsugit/exports')))
    return root / (hashlib.sha256(str(output).encode()).hexdigest() + '.json')


def check(output, source, replace=False):
    current = digest(output)
    if current is not None and not replace:
        receipt = receipt_path(output)
        try:
            data = json.loads(receipt.read_text()) if not receipt.is_symlink() else {}
        except (OSError, ValueError):
            data = {}
        if data.get('sha256') != current or data.get('source') != str(source.resolve()):
            raise Error('Existing export is untracked or was edited outside matsugit. Nothing overwritten. '
                        'Review it first, then explicitly choose Replace existing file or --replace')
    return current


def record(output, source):
    path = receipt_path(output)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise Error('Export receipt is a symlink; refusing to replace it')
    fd, name = tempfile.mkstemp(prefix='.export-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'source':str(source.resolve()), 'output':str(output), 'sha256':digest(output)}, stream)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
