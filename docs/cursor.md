# matsugit in Cursor

**Use the same interactive source/document/slides workspace in Cursor.**

## Interactive workspace

With a current Cursor version supporting MCP Apps, Node 22+, Python 3.10+ and
Quarto, run from an authenticated matsugit checkout (or use its existing launcher):

```sh
matsugit setup-cursor --check
matsugit setup-cursor
```

For a pip installation, add `--checkout /absolute/path/to/matsugit`. This installs
the shared MCP workspace into `~/.cursor/mcp.json`, links the existing authoring
skill, and adds `/matsugit-open`, `/matsugit-slides`, `/matsugit-publish` commands.
`/matsugit-story` opens the same Overview/Walkthrough narrative editor as Codex.
From 0.26 three commands start from a goal instead of a tool:

| Command | Use it to |
| --- | --- |
| `/matsugit-new` | Turn notes into a deck: agree the story first, then open it |
| `/matsugit-check` | Hear what is wrong, slide by slide, and have it fixed on request |
| `/matsugit-help` | Learn what to ask for and what the workspace buttons do |

Rerun `matsugit setup-cursor` after updating to install them.

Other servers/settings are preserved; conflicting custom commands or skills are
refused, not replaced. Enable/reload the matsugit MCP server in Cursor and start
a new chat. Ask `/matsugit-slides Open /absolute/path/deck.md`. Present, split
editing, downloads and reviewed source-to-CI publication use the same runtime as
Codex. `/matsugit-publish` prepares a plan; it does not grant push approval.

Update the checkout and rerun `setup-cursor` to refresh its managed configuration.
The installed skill follows that checkout; do not maintain another editable copy
in `~/.cursor/skills/matsugit`. Setup recognizes identical copies, receipt-matching
older copies, and complete skill trees from the checkout's available Git history.
It keeps the original under `~/.cursor/matsugit-skill-backups/` before linking.
Finder metadata and Python caches do not count as instruction edits.

`matsugit setup-cursor --check` reports the installed and source paths without
changing anything. An unrecognized skill is retained with a list of differing
files. This is distinct from Git divergence: `git pull` updates the checkout,
not an independent copied skill or a running editor's cached connection.

Story editing, title/claim pairs, takeaways, section transitions, compact grid,
long-distance moves, visual Markdown/table editing, source/preview following,
Present, exports, explicit Save, external-change review, recovery and reviewed
Git sync all come from the **same bundle**; there is no older Cursor-only UI.
Save and Git conflict tests run against the standard MCP host path too.

Host capabilities are still distinct: active-chat messaging needs `ui/message`,
and host-controlled downloads need `ui/download-file`. If unavailable, the AI
action retains a copyable request and downloads offer the supported fallback;
neither silently reports success. Actual desktop support depends on the Cursor
version, so protocol tests alone do not establish every installed host's support.

### Add and Check

The workspace opens Markdown as formatted text. `Add` picks a slide or layout by
picture. The `Check` chip beside Document/Slides says `No problems`, `2 to fix`
or `1 tip`; its list names the slide and line in plain words, with Show, a
one-click fix and Ask AI. Agents read the same findings through the
`matsugit_check` tool, so `/matsugit-check` and the panel agree. See the
[workspace guide](codex.org) for what is and is not checked.

### Names and layout in 0.29

The view tabs are `Write`, `Preview` and `Side by side`; the editor modes are
`Formatted` and `Markdown`. A slide strip under the workspace shows where you
are and which slides `Check` flags; double-click a slide to edit that spot. The
workspace is opened by the agent on a file, inside the chat: its one-time hint
says so. `matsugit check FILE` gives the same findings in a terminal.

### Share

`Share` (0.27) is the one button for syncing and deploying: first share, later
changes, a colleague's changes and the site's state, each as one plain step.
It runs in Cursor through the standard MCP path, with no Cursor-specific
feature, and is covered by the same browser test in the inline Cursor host.
See the [workspace guide](codex.org) for its states and limits.

### Panel size and typing

Cursor 3.26.16 advertises only inline MCP App views, capped at 800 pixels tall;
it does not offer a full editor tab through this plugin protocol. From workspace
0.25.5, matsugit requests a 760-pixel panel within the host's limits instead of
inheriting a short chat-card height. The expand icon is shown only when the host
actually advertises another display mode. Present does not enlarge the host window.

That Cursor build also turns `ui/update-model-context` into a chat-composer update.
matsugit no longer sends passive updates while editing in Cursor, because they can
pull focus out of the editor. The explicit slide AI action still sends its selected
slide and prompt. This workaround does not change saves or source/preview sync.

The workspace footer shows the running engine version. Hover it for the host and
display mode; a newly downloaded ZIP does not update an already-open panel.
Reload the installed MCP connection and open a fresh workspace after an upgrade.
Do not keep both a manual and imported copy of the same MCP server enabled.

Do not install both this global MCP entry and a duplicate marketplace MCP server.
The `.cursor-plugin/` manifest also packages the shared skill, MCP and commands
for Cursor's plugin distribution mechanism. No marketplace submission or team
policy changes have been made. Actual availability depends on the Cursor host;
the protocol can be tested without claiming every desktop version is supported.

## Skill-only alternative

matsugit also uses Cursor's native Agent Skills support. You do not need a VS Code
extension, an MCP server, a custom model, or a second copy of its instructions.
The same skill teaches authoring, theme creation and local previews.

## 1. Install the skill

With Node.js/npm and Git available, run this in Cursor's terminal:

```sh
npx skills add guibor/matsugit --skill matsugit --agent cursor --global
```

Review the installer prompt. This installs the skill for your local user, not
the matsugit renderer or Quarto. The repository is public; no GitHub token is
needed. A local checkout also works: replace `guibor/matsugit` with its path.

Open a new Agent chat and type `/matsugit`, selecting the skill. For a first
run, use this prompt:

> /matsugit Set up a local preview in a new folder. Check what is installed,
> tell me about any missing dependencies, then make a small synthetic deck with
> a title, smaller claim, table and takeaway. Show both the document and slides.
> Use the bundled default theme. Do not publish anything.

The skill includes a [setup workflow](../skills/matsugit/references/setup.md)
for Python, Quarto and an isolated renderer installation. It does not require
Emacs, MD Skills, or any personal configuration. Existing installations are reused.

## 2. Work in ordinary Markdown

Examples to use after setup:

> /matsugit Turn @brief.md into a six-slide decision deck. Preserve the
> evidence and citations. Use our configured theme; preview both versions.

> /matsugit Give the evidence and interpretation separate columns, keep the
> longer claim below the title, and add only the takeaway I supplied.

> /matsugit Create a new theme from this approved design reference. Validate
> it with the bundled twelve-slide specimen without changing the specimen.

Cursor may select the skill automatically for relevant requests. Explicit
`/matsugit` is useful when you want to be certain. The skill owns Markdown
syntax, semantic layouts, themes and rendering. Optional BCG/Ackman content
skills can guide the story, but are not dependencies and are not installed by
this command. A BCG-style theme alone does not choose the narrative.

## 3. Share with a project or team

For a repository-local copy, run from that repository and omit `--global`:

```sh
npx skills add guibor/matsugit --skill matsugit --agent cursor --copy
```

Review the generated skill directory and lock file before committing them.
A project copy can travel with the project to a remote worker. Include the full
skill tree (references, starter themes and examples), not only `SKILL.md`.
Do not assume a local global install exists on Cursor Cloud or another machine;
provision Python, Quarto and the renderer in that environment separately.

Cursor also supports syncing personal skills from `~/.cursor/skills/` and team
marketplace plugins, subject to account/admin policy. Those are optional
distribution choices, not required setup. matsugit has not been submitted to
a marketplace; the repository remains the source of truth. Do not change your
team settings or publish a plugin just to preview a deck.

## Update and troubleshoot

- **Refresh instructions:** for the interactive setup, update the checkout and
  rerun `matsugit setup-cursor`. For a skill-only installation, rerun the same
  `npx skills add` command, reviewing local skill edits before replacement.
  Source documents and output files are unaffected.
- **Refresh renderer:** for a `uv` tool installation, use
  `uv tool upgrade matsugit`. Do not replace a working custom launcher.
- **No `/matsugit`:** restart/reload Cursor, then start a new Agent chat. Check
  Skills in Cursor's customization settings and
  `npx skills list --agent cursor --global`. A project install needs the project
  open. A skill on another machine is not automatically installed here.
- **Missing `matsugit` or `quarto`:** follow the setup workflow, checking PATH
  in the same terminal that Agent uses. Installing instructions is not enough.
- **Missing personal theme:** use `default`, or explicitly supply your trusted
  theme directory. Private fonts and corporate assets are not bundled.
- **Deck rendered, no live website:** expected. `render` never publishes.
  Hosting, credentials, repository visibility and CI deployment are separate
  choices, never implied by setup. A private repo does not imply private Pages.

See [Cursor's skill documentation](https://cursor.com/docs/skills) and the
[Skills CLI](https://github.com/vercel-labs/skills) for native discovery and
installation options; [Cursor plugins](https://cursor.com/docs/plugins) cover
optional marketplace distribution. This integration uses the native skill
format. The interactive option uses standard MCP Apps, not a separate renderer;
see [Cursor's MCP documentation](https://cursor.com/docs/mcp).
