"""Portable CI entry point, copied with the renderer into the publishing repo."""
from pathlib import Path
import shutil
import tempfile
from core import config, render, read_json

site = Path(__SITE_DIR__).resolve()
manifests = {p.parent: p for p in site.glob('*/folioforge-manifest.json')}
manifests.update({p.parent: p for p in site.glob('*/matsugit-manifest.json')})
for manifest_file in sorted(manifests.values()):
    manifest = read_json(manifest_file)
    source_name = manifest.get('source_file', 'source.md')
    if source_name not in ('source.md', 'source.org'):
        raise ValueError('Unknown source format in ' + str(manifest_file))
    source = manifest_file.parent / source_name
    settings = config(source, {"theme": "theme", "themes_dir": str(source.parent)})
    settings['handout'] = bool(manifest.get('handout'))
    settings["source_root"] = source.parent
    with tempfile.TemporaryDirectory(prefix="matsugit-ci-") as temp:
        output = Path(temp) / "rendered"
        render(settings, output, edit_url=manifest.get("edit_url"))
        shutil.copytree(output, source.parent, dirs_exist_ok=True)
