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

Private change history uses `history.py` (SQLite transactions, private files,
content-addressed source snapshots) and `git_history.py` (bounded, read-only
local Git commands). `checkpoints.mjs` calls it with the workspace's authorized
document identity. The history schema is versioned; a newer schema is refused
without rewriting it. A source save still uses its original etag check after
the pre-save checkpoint, so history I/O cannot authorize an intervening write.
Post-save checkpoint failure is reported as a history warning, never a false
claim that the file failed to save. The database has per-document and global
retention limits; quota failure rolls back pruning and keeps existing versions.

`history-panel.mjs` is the Changes entry point. `document-state.mjs` keeps local
draft, commit, recorded push and verified deployment observations independent.
`slide-diff.mjs` matches unique text/body/title evidence; duplicate titles are
not stable IDs. `history-restore.mjs` requires explicit slide destinations and
validates structural boundaries. Restore checks the draft generation and disk
etag after checkpointing, is one isolated Undo step and pauses autosave.
The existing save/reconcile engine stays in `app.js`; no broad refactor is
needed to introduce these contracts.

| Module | Role | Main functions |
| --- | --- | --- |
| `cli.py` | Command-line entry point | `main()` dispatches every subcommand |
| `core.py` | Configuration, themes, rendering | `config()` resolves settings (global, project, flags); `install_theme()` copies only manifest-listed theme files; `render()` builds both outputs |
| `source.py` | Markdown and Org input | `read()` parses to the Pandoc AST and strips agent comments; `convert()` converts between Markdown and Org without running code |
| `sugar.py` | Authoring short forms | `markdown()` expands `columns 2:1` lexically; `blocks()` lowers takeaway quotes and ratios in the AST |
| `claude_desktop.py` | `matsugit setup-claude-desktop` | `install()` adds one `matsugit` server to `claude_desktop_config.json` (per-platform `config_dir()`), keeping other servers and settings, backing up the file and refusing an entry it did not write |
| `browser.py` | `matsugit open`: the browser fallback | `open_in_browser()` validates the file, starts `bundle/browser.mjs` detached, reads its one-line `{url, path}` and opens the default browser; `run()` prints the address |
| `layout.py` | Slide structure | `slides()` groups sections and slides; `content()` enforces one claim and one takeaway per slide; `columns()` / `rows()` split regions; `metadata()` keeps only safe settings |
| `components.py` | Semantic blocks | `prepare()` validates metrics, comparison, timeline, decision (`LIMITS`) |
| `relationships.py` | Implication, mapping, annotated evidence | `implication()`, `mapping()`, `annotated()` |
| `charts.py`, `vega.py` | Table-backed and Vega-Lite charts | `dataset()` validates a chart block; `setup()` installs the optional backend |
| `diagrams.py` | D2 diagrams | `setup()`, render with a sanitised SVG result |
| `canvas.py` | Embedded local HTML | validation of `canvas` blocks |
| `check.py` | Plain-language check on the command line | `check()` runs the workspace's check through the bundled Node helper; `report()` |
| `doctor.py` | Read-only setup diagnostics shared by CLI and MCP | `diagnose()` reports required/optional tools; never installs or logs in |
| `lint.py` | CLI density checks | `inspect()` (long titles, dense slides, large tables); `rendered()` optional browser pass |
| `authoring.py` | The recipe catalogue | `TEMPLATES`, `ELEMENTS` (recipe text); `CATALOG` (plain name, when to use, group, sketch); `editor_templates()` feeds the workspace; `template()` feeds the CLI |
| `preview.py` | Fast preview patches | `render()` returns a full render or a small text patch |
| `exports.py` | HTML, ZIP, PDF, PowerPoint | `export_file()` |
| `publish.py`, `canonical.py`, `targets.py`, `repositories.py`, `publication.py` | Reviewed Git publication | `publish()`, `setup_ci()`, `plan()` |
| `git_sync.py`, `git_exchange.py`, `adopt.py` | Pull, reviewed push, moving a source into a checkout | `sync()`, `plan()`, `exchange()` |
| `cursor.py`, `skill_install.py` | Cursor setup | `install()` writes the MCP entry, links the skill, copies every file in `cursor-commands/` |
| `links.py` | Where a shared deck can be opened | `links()` builds slides, document, source and edit URLs from a push receipt; `build_step()` reads a build log; `describe()` records what links need |
| `share.py` | Local facts for the Share button | `status()`, `receipt_plan()`, `target_for()` |
| `updates.py` | Versioned renderer bundles for CI checkouts | `manage()` |
| `table_editor.py` | Standalone visual table editor | `serve()` |

## Workspace `codex-plugin/`

`build.mjs` bundles `src/` into `bundle/` (committed): the browser app (with the recipe catalogue from `authoring.editor_templates()`
baked in) inside the server's embedded runtime, read back by `app-html.mjs`,
`server.mjs` (the MCP server with the Python renderer embedded) and
`story-cli.mjs` (the Story engine for Emacs) and `browser.mjs` (the browser fallback). Rebuild after changing `src/` or
`matsugit/authoring.py`.
The generated server trims whitespace only: identifier renaming and syntax
minification are disabled. First-party source and license notices remain in the
package. This keeps the source-tree size limit without dropping capabilities.

### Server side (Node)

| File | Role |
| --- | --- |
| `src/server.mjs` | Registers MCP tools. Model-visible: `matsugit_open`, `matsugit_workspace` (scratch copy of the guided sample), `matsugit_tour` (writes `matsugit-tour.md` once and opens it; text from `matsugit/templates/tour.md`), `matsugit_check`. App-only: save, preview, recovery, merge, export/publish actions |
| `src/browser.mjs` | The browser fallback, used when no chat host shows the app. `startServer()` runs `server.mjs` over stdio as Cursor would; `serve()` opens the file (`matsugit_open`, or `matsugit_workspace` for the sample), then serves a host page and the app on 127.0.0.1 under a random token, refuses other `Host` headers and origins, relays only `tools/call` and `resources/read`, and stops five minutes after the last heartbeat; `hostPage()` answers the app's host messages (no chat, so Ask AI copies) |
| `src/browser-launch.mjs` | Sends the workspace to the browser when the chat cannot show it. `clientOf()` reads the client from the request envelope (2026 protocol) or the handshake; `wantsBrowser()` is true for a known text-only host (Claude Code) that does not announce `io.modelcontextprotocol/ui`, or with `MATSUGIT_BROWSER=1`; `openInBrowser()` starts or reuses `browser.mjs` for a file and opens the default browser; `browserResult()` is what the agent reads instead of a panel. Used by `matsugit_open`, `matsugit_tour`, `matsugit_workspace` and the model-visible `matsugit_browser` |
| `src/store.mjs` | `WorkspaceStore`: open sessions, version-checked `save()`, preview jobs; `checkedPath()` / `checkedText()` guard inputs; `expectRelocation()` / `followed()` let a session follow the one move a publication reviewed |
| `src/agent-edits.mjs` | Model-visible `matsugit_read_slide` / `matsugit_edit_slide`: bounded revision snapshots and exact replacements within one Story slide; reuse the parser and save path, reject stale or boundary-changing edits |
| `src/diagnostics.mjs` | Model/app-visible `matsugit_doctor`: one bounded Python diagnostic process shared by concurrent requests |
| `src/runtime.mjs` | `PluginRuntime`: unpacks the embedded renderer for this server version |
| `src/actions.mjs`, `actions.py`, `worker.py` | Export, publication and preview workers |
| `src/recovery.mjs`, `src/merge-service.mjs` | Private draft recovery; three-way merge |

### Browser side

`src/app.js` owns the editor (CodeMirror), state, rendering loop, saving and
view switching. On open (`load()`), it puts the cursor on the first sentence
under the first slide's title and claim, so the first screen shows formatted
text, not the settings block or heading marks; a block or list there keeps its
label, and the cursor stays at the end of the title instead. A scratch copy (no
file, not writable) says so and how to get a deck that is kept. A render that
fails because a tool is missing (`setupProblem()`) shows setup guidance, not a
problem in the deck. It wires together focused modules:

| File | Role | Main functions |
| --- | --- | --- |
| `structure.mjs` | Reads headings, blocks, breaks and literals from source text | `structure()`, `frontmatterLength()`, `headingTargets()` |
| `story-model.mjs` | Sections, slides, claims and takeaways as a tree | `storyModel()`, `moveStory()`, `insertStory()`, `titleRange()` |
| `story.mjs` | Story view (Overview, Walkthrough) | `storyView()` |
| `check.mjs` | **Plain-language slide check** | `checkDeck()` returns findings; `applyFix()`; `checkSummary()`; `rendererFinding()` restates renderer errors; `setupProblem()` recognises a missing tool and says what to install |
| `check-panel.mjs` | The Check chip and list | `checkPanel()` (Show, fix, Ask AI) |
| `setup-check.mjs` | More > Check setup, separate from deck findings | `setupCheck()` renders the shared diagnostic report without executing remedies |
| `slide-rail.mjs` | Slide strip under the workspace | `slideRail()`: current slide, jump, Check markers |
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
recovery view or the `More` menu. It defaults to false.

### Two writers, one file (`app.js`, `external-edits.mjs`)

The workspace polls the file every three seconds. `reload()` handles a changed
file in one of three ways. Untouched workspace: replace the text. Author has
typed in this session: reconcile. Table edit or Redo branch pending: mark
`Changed elsewhere` and wait.

`planExternalEdit()` checks the current base and retained pre-save versions.
File contents cannot prove the other writer's parent revision. Automatic
combining therefore requires every candidate to produce the same conflict-free
result. Disagreement, including a possible deliberate deletion, requires an
explicit review. A historical base is only a review proposal. Retaining a
saved title does not prove that the writer saw a saved number beside it;
short deleted lines need the same protection as long paragraphs. No matching
line is used to discard a possible parent revision. The three-way merge runs
in the existing server worker. Without ambiguity or conflicts,
`applyExternal()` re-reads the file to confirm its version, turns the result
into line hunks with `textChanges()` and dispatches them outside the undo
history, so selection and Undo survive; a result that differs from the file is
saved only when autosave is enabled. External updates do not clear saved
history. History is bounded to 20 versions and 8 MiB without a time expiry;
exceeding either bound requires full-version review on subsequent external
changes. Opening another document or explicitly accepting a reviewed version
starts a new history. This is session-local protection, not a revision protocol
for external editors. With conflicts, `state.ancestor` supplies a review base,
never an automatic write. An autosave refused by the version check calls
`reload()` rather than overwriting the file.

CodeMirror cannot preserve an external insertion inside the range of an earlier
whole-document replacement when that replacement is undone. `wholesaleHistory`
therefore rebases the author's contribution as one Undo step in this case,
with a recovery checkpoint of the pre-merge text. This protects the accepted
external edit, but does not preserve every earlier Undo step.

### When the file or the plugin goes away (`app.js`, `store.mjs`)

`call()` wraps every tool call. A `Workspace expired` error means the plugin
process restarted and its sessions are gone; `reconnect()` reopens the same
absolute path once (shared by concurrent callers), swaps in the new session,
restarts the draft backup and retries. Base text and version stay as they were,
so the usual version checks decide what happens next. `store.read()` raises
`MissingFile` with a plain message when the file is gone; the notice then offers
`matsugit_save` with `recreate: true`, which writes only if nothing exists at
the path. `store.save()` returns `read-only` instead of renaming over a file
without write permission, and `source()` reports `readOnly` so the workspace can
resume saving when it changes. A merge or resolved review becomes the undo
baseline in `applyMerged()`.

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

Site addresses are independent of deployment status. `links()` derives native
and legacy topics HTML paths immediately from the recorded target. `status()`
can fill older receipts from the matching local checkout without a fetch. Share
retains these links during checks, conflicts and failures; only the status may
claim the recorded revision is live. Configured HTTP Pages addresses are allowed
for navigation, never as provider API endpoints.

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

### Independent reading and slide projections

`document.py` projects the shared Pandoc AST into continuous reading content,
without changing the authored Markdown or inventing prose. Only structured
claims immediately after a slide heading/break become lead paragraphs. An
identical leading title is deduplicated with its anchor retained. Reading-only
CSS removes slide column constraints; Reveal CSS and authored boundaries stay
unchanged. `core.render(formats=...)` prepares only the selected projection;
`render --only document|slides` exposes that contract. Generated navigation
links only to built views. Portable CI includes the same projection module.

`runtime/fit.js` reads rendered geometry after fonts/media and checks overflow,
clipping and overlapping primary slide regions. It does not mutate layout or
source. The preview reports the current slide through the existing token-bound
bridge; Check retains only findings for the matching rendered source revision.
It does not imply that unvisited slides were measured. The optional full-deck
browser lint uses the identical measurement code. Fit findings are advisory,
not build or export failures (unless the author explicitly requests strict lint).

Preview titles with unchanged anchor/attributes can patch in place, including
the copied Reveal menu label. A changed anchor or heading structure forces a
full render; document headings still rebuild their TOC. Claims remain inert
text patches. Fonts, theme, slide geometry and source text are never rewritten
to make a patch succeed.

Presentation mode keeps its controls opaque, with a labeled `Exit presentation`
command and a return arrow distinct from fullscreen controls. Exiting restores
the previous view and follow setting and focuses Present. Escape remains an
alternative; finding the return action must not depend on knowing that key.

Incoming changes first populate `incomingReady`, not `conflict`. Acceptance
rechecks the observed etag, checkpoints the draft and applies minimal edits.
Only overlapping or ambiguous two-sided edits require the merge dialog.
Scoped agent writes record bounded, contiguous parent hashes in the server;
only an exact matching chain permits bypassing historical-parent ambiguity.
This never bypasses a real draft conflict or discards protection against a later
untracked writer. Pending updates pause autosave, and failed writes remain errors.

`slide-peek.mjs` owns a temporary sandboxed slide iframe, with a separate job,
token, cancellation and object-URL lifecycle. It renders the current draft and
does not mutate the main preview, layout or source selection.

`export_boundary.py` cuts the top-level Pandoc AST before asset processing for
delivery only. Workspace previews and source-to-CI preparation explicitly keep
the complete AST. Native CI writes a clean site outside the tracked source tree.
The small standalone boundary module is also vendored into legacy CI adapters.

Theme roots are ordered explicit/project, shared, then built-in; `resolve_theme`
is shared by discovery, installation and inheritance. Invalid shadowing themes
fail explicitly rather than silently falling through. Theme diagnostics include
the selected origin/path, and each preview request rereads file configuration.

- `python3 -m unittest discover -s tests`: renderer, layout, publication,
  catalogue, Cursor install (synthetic fixtures and local Git remotes only).
- `npm test --prefix codex-plugin`: pure modules and the built server over MCP.
- `codex-plugin/tests/*-browser.py`: the real built workspace in Chromium via
  the isolated host in `tests/browser-host.mjs` (needs Python Playwright).
  `check-browser.py` covers the check panel and the picker.

## Visual Layout Safety and Delivery (0.36.1)

Formatted editing protects paired container fences and region heading prefixes.
Whole-block removal remains possible; Raw Markdown is the structural escape hatch.
Raw/Formatted switches anchor to the visible caret or reading passage, not pixels.
Explicit image heights bypass flexible media allocation, including shallow panel
connectors. Compact spacing is an undoable slide attribute and preserves type size.
Setup reports UI, server, renderer and host separately. Unsupported host downloads
offer explicit server Downloads delivery, never an unverified sandbox anchor loop.

The 0.36.1 fitting design (implemented below) preserves authored geometry, fits media
proportionally, reduce spacing, then scale text within readable floors. Equal-role
regions should share a consistent type scale. No clipping or silent slide splitting.
Validate preview/export parity and long-content cases before enabling it by default.
Fit groups follow semantics: titles and claims stay at theme size; peer region
headings share a size; peer body text shares a bounded scale. Tables scale as
whole tables, not individual cells. Takeaways and sources keep their own roles.
Explicit image dimensions remain constraints. No independently tiny dense column.
Fit is local to a slide, never driven by the densest slide in the deck. Keep
already-fitting slides unchanged. Peer groups follow the layout's semantic roles,
not every text node: body, region heading, table, takeaway and source are separate.
Keep title and claim sizes fixed unless the author explicitly permits a change.
Choose one shared scale that fits every member of a peer group, within a
theme-defined readability floor; an unresolved member produces a fit finding,
not clipping, hidden overflow, a changed layout or an automatic split. Recompute
from the original theme metrics after fonts/media load so repeated renders do not
accumulate shrinkage. Preview, standalone HTML and PDF must use the same decision;
PowerPoint must be checked separately rather than assumed to inherit browser fit.

## Protected Agent Updates

`incoming-transition.mjs` is the pure incoming-update gate. Only exact server-
observed agent ancestry permits reconciliation, never direct replacement.
Autosave and draft dirtiness are not inputs to that permission. Existing review,
table, restore, delivery and Redo states pause automatic reconciliation.
`planExternalEdit` still decides whether edits conflict. The checkpoint and final
file/draft checks precede mutation; concurrent typing invalidates the attempt.
Automatic scoped updates are isolated CodeMirror undo events. Unknown filesystem
writes keep acceptance and the previous author-only undo behaviour. A combined
draft differing from disk stays unsaved until normal Save or opted-in autosave.
Provenance keys use the same canonical initial path as workspace sessions; this
does not loosen rejection of symlinks swapped beneath an open document.

## Bounded Automatic Fit

The shared fit runtime restores original inline styles before each pass, leaves
already-fitting slides untouched, reduces positive prose margins in 2% steps
only as needed, never below 90% of the original spacing, then
tries common prose scales in 2% steps down to 88%. Each table has a separate
group. Computed fonts are captured before mutation; only elements with direct
text are scaled so container inheritance cannot shrink fixed region headings.
Sources, titles, claims, media and code are excluded. Theme floors default to
20px, with hard bounds of 16px and 80% scale. `.no-fit` opts out per slide.
After text fitting, spacing is expanded again as far as the available room allows.
Unresolved geometry remains visible to the existing fit checker. Media is
reallocated at each candidate scale. Print and scroll views process all visible
slides; PDF explicitly fits before capture. This does not change PPTX layout.

## Export Runtime Recovery (2026-11-15)

`exports.setup` refreshes an existing export virtual environment with the
current Python before installing the hash-locked dependencies. OS Python
upgrades can leave an existing interpreter symlink pointing at a new version
while its packages remain under the old version's site-packages directory.
`exports.browser_artifacts` marks its one fallback subprocess with
`_MATSUGIT_EXPORT_REEXEC=1`. A fallback interpreter without Playwright raises
an actionable error instead of recursively launching itself. Tests in
`tests/test_export_runtime.py` cover bounded fallback, failed/missing runtimes,
and creation versus refresh of the isolated export environment.

# Single Opening Title

The authored source remains unchanged. Slide projection suppresses the generated
metadata cover when the first rendered heading matches the metadata title or is
marked `cover`, unless `slide-title-page` is explicit. The decision is included
in preview metadata so a cover-policy change requires a full render. Reading
projection replaces only a matching opening H1/H2 with its anchor, preserving
the claim and all body content. Later matching headings remain real sections.
The shared projection applies to preview, export and installed Pages CI.
