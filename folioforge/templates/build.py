"""Portable CI entry point, copied with the renderer into the publishing repo."""
from pathlib import Path
import shutil
import tempfile
from core import config, render, read_json

site = Path(__SITE_DIR__).resolve()
for source in sorted(site.glob("*/source.md")):
    manifest = read_json(source.parent / "folioforge-manifest.json")
    settings = config(source, {"theme": "theme", "themes_dir": str(source.parent)})
    settings["source_root"] = source.parent
    with tempfile.TemporaryDirectory(prefix="folioforge-ci-") as temp:
        output = Path(temp) / "rendered"
        render(settings, output, edit_url=manifest.get("edit_url"))
        shutil.copytree(output, source.parent, dirs_exist_ok=True)
