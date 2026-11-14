"""Portable CI entry point, copied with the renderer into the publishing repo."""
from pathlib import Path
import html
from core import config, render, read_json

site = Path(__SITE_DIR__).resolve()
# Publish only generated files, never the tracked originals or unused assets.
public = Path('.matsugit-ci/site').resolve()
if public.exists() and any(public.iterdir()):
    raise ValueError('CI output must be empty: ' + str(public))
public.mkdir(parents=True, exist_ok=True)
manifests = {p.parent: p for p in site.glob('*/folioforge-manifest.json')}
manifests.update({p.parent: p for p in site.glob('*/matsugit-manifest.json')})
manifests.update({p.parent: p for p in site.glob('*/matsugit-source.json')})
for manifest_file in sorted(manifests.values()):
    manifest = read_json(manifest_file)
    source_name = manifest.get('source_file', 'source.md')
    if source_name not in ('source.md', 'source.org'):
        raise ValueError('Unknown source format in ' + str(manifest_file))
    source = manifest_file.parent / source_name
    settings = config(source, {"theme": "theme", "themes_dir": str(source.parent)})
    settings['handout'] = bool(manifest.get('handout'))
    settings["source_root"] = source.parent
    render(settings, public / source.parent.name, edit_url=manifest.get("edit_url"))
links = ''.join(f'<li><a href="{p.parent.name}/index.html">{html.escape(p.parent.name)}</a></li>'
                for p in sorted(manifests.values()))
if links:
    (public / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Documents</title><h1>Documents</h1><ul>' + links + '</ul>', encoding='utf-8')
