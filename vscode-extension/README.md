# matsugit for VS Code (Preview)

Open a Markdown or Org file, then run **matsugit: Open Document** in the Command
Palette, or use **Reopen Editor With > matsugit**. The workspace is a full editor
tab with formatted Markdown, Story, slides, reading view, Present, exports and
reviewed Git sharing. It does not replace the default Markdown editor.

From a current Git checkout run `python3 vscode-extension/package_vscode.py --install`
(Windows: `py -3 vscode-extension/package_vscode.py --install`). No npm build is
needed. Reload VS Code, then use the command above. Running it again installs
the checkout's version. The CLI must be on PATH; `--code /path/to/code` selects
an approved installation explicitly. This does not install prerequisites.

Alternatively install the generated `dist/matsugit.vsix` with **Extensions: Install from VSIX**.
Do not import the Codex/Cursor
plugin ZIP into VS Code. This extension does not install duplicate MCP servers.

## Requirements

Use a trusted local checkout and approved Node.js 22+, Python 3.10+, Quarto and
Pandoc >=3.7.0.2. Configure `matsugit.nodePath` or `matsugit.pythonPath` when GUI
PATH discovery differs from your terminal. No prerequisite downloads run on
activation. Optional diagram/chart/PDF tools are the same as other matsugit hosts.

VS Code owns the document buffer, native save prompts and hot-exit recovery.
Edits in matsugit update that buffer without publishing or saving automatically.
Other buffer writers wait for Accept/review; reading their change never permits
the next keystroke to overwrite it. Conflicts retain both drafts until resolved.
VS Code's own Auto Save setting still applies. External disk changes follow VS
Code's conflict handling; do not overwrite its warning without reviewing it.
Unapplied edits in a table dialog must be applied to become part of the document.

Rendering is local and uses no AI subscription. The slide AI action offers a
copyable request; this release does not automatically route it to Copilot,
Codex or Claude. Paste it into your chosen agent explicitly.

## Themes and work profiles

The public package contains the public default theme. To use an existing work
installation, set `matsugit.configPath` to its configuration file, for example
`~/.config/matsugit-work/config.json`. That profile must refer to an installed
theme directory. Corporate themes are not bundled in this public extension.

## Limits

Local desktop files only in this release; browser-only vscode.dev and remote
workspace URIs are not supported yet. Native Windows/Mac acceptance must be
verified separately from Linux tests. Keep your documents outside extension
installation directories. Share never creates public hosting implicitly.

The native Linux smoke test covers opening, actual slide/document previews,
Story, formatted/raw editing, dirty state, keyboard Undo, native Save and
concurrent buffer edits. A real GitHub/GitLab deployment, the native export
Save dialog and hot-exit restoration need separate acceptance testing.

## Build

From the repository:

```sh
npm ci --prefix codex-plugin
npm run build --prefix codex-plugin
node vscode-extension/build.mjs
cd vscode-extension
python3 package_vscode.py
```

On Windows, the build also needs a `python3` command or `MATSUGIT_PYTHON` set
to the Python executable. The prebuilt VSIX does not need npm or a build.

This is a maintainer packaging step, not a dependency download at plugin launch.
Commit `dist/extension.cjs` after building; this is the reviewed native adapter.
The runtime and dependency notices are bundled; users need no npm build.

MIT licensed, copyright MDF (guibor). Third-party notices are in `runtime/`.
