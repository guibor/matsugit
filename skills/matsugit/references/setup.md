# First preview setup

Use this workflow when asked to set up matsugit, including from Cursor's
`/matsugit` skill. Installing this skill only installs instructions and assets;
it does not install the renderer, Python, Git or Quarto. No editor-specific
plugin or service is needed. Do not change publication settings during setup.

## Inspect before installing

1. Identify the OS and the actual shell/environment used by the agent. Check
   `matsugit --help`, `quarto --version`, `git --version`, and the available
   Python (`python3 --version`, or `py -3 --version` on Windows). Python 3.10+
   is required. Respect working wrappers and project settings rather than
   replacing them; never install over a private launcher of the same name.
2. Inspect an existing `matsugit.json` and any selected theme. If the command
   is missing, check whether an existing checkout's `bin/matsugit` works.
   Missing Git access is not permission to create credentials or change visibility.
3. Install missing tools only within the user's authorization. Use the existing
   package manager for Python/Git and the official Quarto installer at
   https://quarto.org/docs/get-started/. Do not bypass an externally managed
   Python with `--break-system-packages`, or use `sudo pip`.

## Isolate the renderer

With an existing `uv` installation, install the renderer as a user tool:

```sh
uv tool install 'git+https://github.com/guibor/matsugit.git'
matsugit --help
```

If `uv` is absent, use an existing `pipx`, an isolated virtual environment,
or an authorized checkout. For example, in a **new** POSIX project directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'git+https://github.com/guibor/matsugit.git'
.venv/bin/matsugit --help
```

On Windows use `py -3 -m venv .venv`, `.venv\Scripts\python.exe` and
`.venv\Scripts\matsugit.exe`. Use the explicit executable if Cursor's shell
has a different PATH. Reuse a working environment; don't erase an existing one.
A local checkout can be installed with `uv tool install .` or that
environment's `python -m pip install .`. The general repository is public;
no GitHub token is needed to read it. Private theme packs remain separate.

Do not install optional tooling without need. For charts, the explicit
`matsugit setup-charts` command provisions the isolated Altair/Vega-Lite
backend. Browser lint additionally needs Playwright and Chromium. These are
not prerequisites for a simple text/table preview.

## Verify with synthetic content

In a new working directory, with an unused source filename and output directory:

```sh
matsugit template section --output deck.md
matsugit lint deck.md --strict
matsugit render deck.md --theme default --output preview
```

Substitute the virtual environment's executable if necessary. Use the bundled
neutral `default` theme for this independent smoke test, not someone else's
private theme. Do not overwrite or publish an existing document. Inspect both
`preview/index.html` and `preview/slides.html`; relative assets must load.
Local HTML can be opened as files; no public server is needed. On a remote host,
use an already approved private preview mechanism and verify the URL.

Report separately: skill discovered, renderer runnable, Quarto available,
render succeeded, and visual inspection performed. Do not call setup complete
just because the skill installed. Keep generated previews and environments out
of version control. A refresh of the skill does not update the renderer; an
update of the renderer does not deploy CI or update personal themes.
