"""Render an unsaved editor snapshot; never write the original or publish."""
import contextlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from folioforge.core import config, render


def main():
    request = json.load(sys.stdin)
    source = Path(request['path'])
    if source.suffix.lower() not in {'.md', '.markdown', '.qmd', '.org'}:
        raise ValueError('Unsupported document format')
    # A document's project settings may choose styling, never an executable.
    overrides = {'theme': request.get('theme'), 'quarto': os.environ.get('QUARTO', 'quarto')}
    settings = config(source, overrides)
    with contextlib.redirect_stdout(sys.stderr):
        render(settings, Path(request['output']), source_text=request['text'])
    print(json.dumps({'theme': settings['theme']}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
