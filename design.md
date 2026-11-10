# matsugit design

How the code is organised and where the main functions live. For behaviour and
limits, read `README.org` and `docs/`; for requirements, `prd.org`.

## The shape of the system

One source file (Markdown, Quarto Markdown or Org) goes through one renderer and
comes out as slides and a reading document. Everything else is a way to edit,
check, preview or deliver that same file.

```
source.md / source.org
   |  matsugit/source.py     read into Pandoc's document model (never executed)
   |  matsugit/sugar.py      expand short forms (columns 2:1, [!TAKEAWAY])
   |  matsugit/components.py validate semantic blocks (metrics, comparison, ...)
   |  matsugit/layout.py     turn H1/H2/H3/H4 + blocks into slide structure
   v  matsugit/core.py       copy the theme, call Quarto -> index.html, slides.html
```

Three surfaces sit on top:

- **CLI** (`matsugit/cli.py`): render, lint, template, export, publish, setup.
- **Workspace** (`codex-plugin/`): an MCP server plus one browser bundle used by
  Codex and Cursor. It edits the draft, previews through the same Python
  renderer, and never publishes without an explicit reviewed action.
- **Agent skill** (`skills/matsugit/`) and **Cursor commands**
  (`cursor-commands/`): instructions, not code.

`folioforge/` is the legacy import name and only re-exports `matsugit`.

## Python package `matsugit/`

| Module | Role | Main functions |
| --- | --- | --- |
| `cli.py` | Command-line entry point | `main()` dispatches every subcommand |
| `core.py` | Configuration, themes, rendering | `config()` resolves settings (global, project, flags); `install_theme()` copies only manifest-listed theme files; `render()` builds both outputs |
| `source.py` | Markdown and Org input | `read()` parses to the Pandoc AST and strips agent comments; `convert()` converts between Markdown and Org without running code |
| `sugar.py` | Authoring short forms | `markdown()` expands `columns 2:1` lexically; `blocks()` lowers takeaway quotes and ratios in the AST |
| `layout.py` | Slide structure | `slides()` groups sections and slides; `content()` enforces one claim and one takeaway per slide; `columns()` / `rows()` split regions; `metadata()` keeps only safe settings |
| `components.py` | Semantic blocks | `prepare()` validates metrics, comparison, timeline, decision (`LIMITS`) |
| `relationships.py` | Implication, mapping, annotated evidence | `implication()`, `mapping()`, `annotated()` |
| `charts.py`, `vega.py` | Table-backed and Vega-Lite charts | `dataset()` validates a chart block; `setup()` installs the optional backend |
| `diagrams.py` | D2 diagrams | `setup()`, render with a sanitised SVG result |
| `canvas.py` | Embedded local HTML | validation of `canvas` blocks |
| `lint.py` | CLI density checks | `inspect()` (long titles, dense slides, large tables); `rendered()` optional browser pass |
| `authoring.py` | The recipe catalogue | `TEMPLATES`, `ELEMENTS` (recipe text); `CATALOG` (plain name, when to use, group, sketch); `editor_templates()` feeds the workspace; `template()` feeds the CLI |
| `preview.py` | Fast preview patches | `render()` returns a full render or a small text patch |
| `exports.py` | HTML, ZIP, PDF, PowerPoint | `export_file()` |
| `publish.py`, `canonical.py`, `targets.py`, `repositories.py`, `publication.py` | Reviewed Git publication | `publish()`, `setup_ci()`, `plan()` |
| `git_sync.py`, `git_exchange.py`, `adopt.py` | Pull, reviewed push, moving a source into a checkout | `sync()`, `plan()`, `exchange()` |
| `cursor.py`, `skill_install.py` | Cursor setup | `install()` writes the MCP entry, links the skill, copies every file in `cursor-commands/` |
| `share.py` | Local facts for the Share button | `status()`, `receipt_plan()`, `target_for()` |
| `updates.py` | Versioned renderer bundles for CI checkouts | `manage()` |
| `table_editor.py` | Standalone visual table editor | `serve()` |

## Workspace `codex-plugin/`

`build.mjs` bundles `src/` into `bundle/` (committed): `app.html` (the browser
app with the recipe catalogue from `authoring.editor_templates()` baked in),
`server.mjs` (the MCP server with the Python renderer embedded) and
`story-cli.mjs` (the Story engine for Emacs). Rebuild after changing `src/` or
`matsugit/authoring.py`.

### Server side (Node)

| File | Role |
| --- | --- |
| `src/server.mjs` | Registers MCP tools. Model-visible: `matsugit_open`, `matsugit_workspace`, `matsugit_check`. App-only: save, preview, recovery, merge, export/publish actions |
| `src/store.mjs` | `WorkspaceStore`: open sessions, version-checked `save()`, preview jobs; `checkedPath()` / `checkedText()` guard inputs; `expectRelocation()` / `followed()` let a session follow the one move a publication reviewed |
| `src/runtime.mjs` | `PluginRuntime`: unpacks the embedded renderer for this server version |
| `src/actions.mjs`, `actions.py`, `worker.py` | Export, publication and preview workers |
| `src/recovery.mjs`, `src/merge-service.mjs` | Private draft recovery; three-way merge |

### Browser side

`src/app.js` owns the editor (CodeMirror), state, rendering loop, saving and
view switching. It wires together focused modules:

| File | Role | Main functions |
| --- | --- | --- |
| `structure.mjs` | Reads headings, blocks, breaks and literals from source text | `structure()`, `frontmatterLength()`, `headingTargets()` |
| `story-model.mjs` | Sections, slides, claims and takeaways as a tree | `storyModel()`, `moveStory()`, `insertStory()`, `titleRange()` |
| `story.mjs` | Story view (Overview, Walkthrough) | `storyView()` |
| `check.mjs` | **Plain-language slide check** | `checkDeck()` returns findings; `applyFix()`; `checkSummary()`; `rendererFinding()` restates renderer errors |
| `check-panel.mjs` | The Check chip and list | `checkPanel()` (Show, fix, Ask AI) |
| `gallery.mjs` | **Layout picker** behind `Add` | `gallery()` draws thumbnails and inserts the chosen recipe |
| `insertions.mjs` | Pure source edits | `placeInsertion()` decides where a recipe goes; `wrapElement()` wraps a selection; `snippetTemplate()` marks placeholders |
| `authoring.mjs` | Gutter roles, block labels, `/` completion | `authoringExtensions()` |
| `visual.mjs`, `table-dialog.js`, `tables.mjs` | Visual mode and table editing | `visualExtensions()`, `tableDialog()` |
| `outline.mjs` | Folding by heading depth | `setOutlineDepth()`, `outlineKeys()` |
| `preview.js` | Preview iframe, position sync, in-place patches | `previewHtml()`, `patchedHtml()` |
| `slide-agent.mjs`, `slide-agent-request.mjs` | "Edit slide with AI" request to the current chat | `slideAgent()`, `slideAgentRequest()` |
| `share.mjs` | **One Share button**: first share, later changes, colleagues' changes, site state | `share()`; `plainBlocked()` restates Git refusals |
| `delivery.js`, `download.mjs`, `git-exchange.js`, `publication-status.mjs` | Export and the detailed publish, Git sync and status dialogs; `delivery()` returns the job runner Share reuses | |
| `merge-dialog.mjs`, `change-review.mjs`, `save-status.mjs` | External-change review and save state | |
| `host-view.mjs`, `host-results.mjs` | Differences between Codex and Cursor hosts | |

### How the check works (`check.mjs`)

`checkDeck(source, org)` is a pure function over text. It never renders, reads
files or calls a model, so it can run on every pause in typing and inside the
MCP server.

1. `structure()` supplies headings, slide breaks and literal ranges (settings
   block, code, HTML). Literal lines and anything inside an agent comment are
   never judged.
2. Its own scan pairs block fences by Pandoc's actual rule (any bare colon line
   closes the innermost block; an opener glued to paragraph text is not a
   block). That yields open blocks, stray closers and nesting.
3. Checks run in groups: settings, blocks that do not open or close, part
   counts (limits mirror `layout.py` and `components.LIMITS`), charts, claims
   and takeaways per slide segment, then tips.
4. Each finding carries `code`, `severity` (`problem` or `tip`), the slide
   number and title, the line, a plain `message`, a `how`, and optionally a
   `fix` (`{label, changes}`) that is safe to apply mechanically.

`tests/check.test.mjs` runs every problem case through the real Python renderer
too: it must fail or misrender where the check says so, and every fixed text
must render. That keeps the two from drifting. The renderer stays the
authority: when a render fails and the check has nothing to say,
`rendererFinding()` shows the renderer's own message.

In the app, `checkPanel()` recomputes 300 ms after edits, paints the chip, and
applies a fix as one editor transaction (one Undo step, no save). A failed
render sets `state.renderError`; the notice then offers `Show problems` and
`#preview-stale` marks the old preview.

### How adding works (`gallery.mjs`, `insertions.mjs`)

Recipe text lives once, in `matsugit/authoring.py`. `CATALOG` adds the plain
name, the "use it when" line, the group (`slide` or `part`) and a sketch id.
`placeInsertion()` chooses the position from `storyModel()`: a slide goes after
the slide holding the cursor; a part goes at a free line, else after the
current paragraph or block; foot-of-slide parts go to the end of the slide; an
existing claim or takeaway is selected instead of duplicated; nothing is added
while a block is unclosed. The `/` completion in `authoring.mjs` uses the same
catalogue for keyboard users.

### Autosave (`app.js`)

`scheduleAutosave()` runs after each document change and calls the ordinary
`save({review: false})` 1.5 s after typing stops. It does nothing for files
without a writable, versioned connection, backs off while a table edit, merge,
review or share holds the document, and stops at a conflict so the existing
review takes over. `state.autosave` comes from the `autosave` open option, the
recovery view or the `More` menu.

### Two writers, one file (`app.js`, `external-edits.mjs`)

The workspace polls the file every three seconds. `reload()` handles a changed
file in one of three ways. Untouched workspace: replace the text. Author has
typed in this session: reconcile. Table edit or Redo branch pending: mark
`Changed elsewhere` and wait.

Reconciling picks the merge base with `closestAncestor()` from the current file
version plus `savedVersions` (what this workspace wrote in the last ten
minutes). An incoming file made from an older read is closest to that read, so
merging from it restores what was typed since instead of deleting it. The
three-way merge runs in the existing server worker. Without conflicts,
`applyExternal()` re-reads the file to confirm its version, turns the result
into line hunks with `textChanges()` and dispatches them outside the undo
history, so selection and Undo survive; a result that differs from the file is
then saved by autosave. With conflicts, `state.ancestor` keeps the chosen base
for the review dialogs and nothing is written. An autosave refused by the
version check calls `reload()` rather than stopping.

### How Share works (`share.mjs`, `matsugit/share.py`)

Share adds no new Git operation; it sequences the reviewed ones. `share-status`
(`share.status()`, local only) says whether the open file is tracked in a
checkout with an upstream. If not (`mode: new`), Share runs the existing
publish `plan` and `publish` with move-and-link into a chosen CI target, and the
store follows the move. If so (`mode: sync`), it runs `exchange-plan`, merges
base, local and incoming text with the existing three-way merge, and then either
pulls (`sync`), opens the existing conflict dialog, or sends with `exchange`.
`receipt_plan()` attaches the project and provider to that push so
`publication.status(check=True)` can report the site build afterwards. Share
saves before taking the delivery lock, because Save is disabled while locked.
`outcome()` paints the result from the stored receipt and `monitor()` polls the
provider independently of the dialog, so the header button and a notice report
the site build even when Share is closed.

## Agent surface

- `skills/matsugit/SKILL.md` routes to `references/` (syntax, recipes, themes,
  delivery, workspace) and includes guidance for authors who do not read
  Markdown: slide words, layout names as in the picker, run `matsugit_check`
  after edits.
- `cursor-commands/*.md` are slash commands installed by `matsugit setup-cursor`:
  `matsugit-open`, `-slides`, `-story`, `-publish` (tool-shaped) and
  `matsugit-new`, `-check`, `-help` (goal-shaped).
- Plugin manifests: `plugin.json`, `.codex-plugin/plugin.json`,
  `.cursor-plugin/plugin.json`; versions must match `codex-plugin/package.json`.

## Tests

- `python3 -m unittest discover -s tests`: renderer, layout, publication,
  catalogue, Cursor install (synthetic fixtures and local Git remotes only).
- `npm test --prefix codex-plugin`: pure modules and the built server over MCP.
- `codex-plugin/tests/*-browser.py`: the real built workspace in Chromium via
  the isolated host in `tests/browser-host.mjs` (needs Python Playwright).
  `check-browser.py` covers the check panel and the picker.
