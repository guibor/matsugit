---
name: matsugit
description: Set up matsugit, author composable Markdown or Org decks, address slide agent-comments, or validate theme packs. Use for matsugit syntax, layouts, charts, previews, the Codex workspace and Cursor setup; not arbitrary PowerPoint editing.
---

# matsugit

Previously named Folioforge. Use lowercase `matsugit` for new commands, skills,
plugin IDs and configuration. Preserve legacy settings and recovery data; for
an existing installation read [migration.md](references/migration.md) first.

Produce an editable argument, not a collection of hand-positioned slide objects.
Markdown and Org are equal authoring inputs. For native Org syntax read
[org.md](references/org.md); do not paste Markdown fences into an Org buffer.
Before revising a deck, inspect its local source for `agent-comment` blocks.
When present, follow [the review protocol](references/agent-comments.md): preserve
requests, respond in place, and leave acceptance/resolution to the user.
Use Markdown for meaning, a small set of recipes for composition, and a theme
for presentation. Do not change the renderer or an existing theme just to fit
one slide.

## Choose the workflow

- **Present, download or publish:** read [delivery.md](references/delivery.md).
  Present mode is local. Export is distinct from publication; a configured sync
  folder writes locally, without a cloud API. Always review/confirm a target before
  pushing. Editable PowerPoint is an adaptation, not exact CSS fidelity.

- **Edit/preview in the Codex workspace:** read [codex-workspace.md](references/codex-workspace.md).
  Prefer the available plugin tools when the user asks for an interactive split
  preview. Keep unsaved workspace edits separate from disk saves and publication.
- **First-time setup or missing commands:** read [setup.md](references/setup.md).
  Check the existing environment, install only approved missing prerequisites,
  then verify a local document and slide preview. In Cursor `matsugit setup-cursor`
  installs the shared MCP workspace and `/matsugit-slides` command. A skill-only
  `/matsugit` setup is also available, without an MCP server or always-on rule.
- **Write or revise a deck:** read [authoring.md](references/authoring.md) and
  [slide-types.md](references/slide-types.md). Start with the closest recipe in
  [slide-types.md](assets/slide-types.md), not a new layout language.
- **Create or adapt a theme:** read [themes.md](references/themes.md). Copy the
  [starter pack](assets/themes/starter/theme.json) into a new theme directory;
  validate it with the same twelve-slide corpus, without editing the corpus to
  conceal theme defects.
- **Relationships or saved pointers:** read [relationships.md](references/relationships.md).
  Distinguish whole-panel implication, paired rows and named evidence callouts.
  For chart data points use native Altair/Vega-Lite annotations, not DOM coordinates.
- **Expandable HTML evidence:** use an empty `canvas` block with local `src` and
  accessible `title`. Scripts require explicit `interactive="true"` for a trusted
  self-contained file. Never turn arbitrary raw HTML into executable content.
  See [canvas.md](references/canvas.md) for safety, Org syntax and export limits.
- **Evaluate a missing capability:** read [research-and-gaps.md](references/research-and-gaps.md).
  Distinguish native support, composition from existing blocks, external-image
  fallback, and proposed features. Never invent supported options.

## Content guidance is separate

This skill owns the source format and rendering contract, not a mandatory
storytelling style. Use the user's brief or, when available and relevant,
`bcg-slides` for consulting argument structure and `ackman-slides` for cumulative
evidence and narrative cadence. These optional skills must not redefine heading
semantics or invent renderer options. A theme named for a style does not select
that content method. All workflows remain usable without those skills.

## Establish the contract

Check `matsugit --help` and the project's `matsugit.json` before choosing
commands or changing defaults. Respect an explicitly selected theme, target
repository and legacy layout. Python 3.10+, Git and Quarto are prerequisites;
charts and browser lint have optional dependencies. These files also work when
the skill is installed separately from the matsugit checkout.

For new decks use `slide-layout: structured`: YAML title = deck; H1 = section;
H2 = slide title; the immediately following H3 = smaller claim; H4 = body region.
Do not reinterpret these levels per theme. A short topic plus an answer-bearing
claim is valid; do not force a long action title into the large heading.

Before drafting, identify the audience, decision, evidence, and authorized
visual source. When enough is supplied, proceed. Mark missing evidence rather
than inventing numbers, quotations, sources, owners or an organization's brand.
For reference reconstruction, preserve the authorized original wording and
exhibits. Keep reconstruction commentary outside the slides; do not invent
bottom takeaways that the reference never stated.

## Render and check

```sh
matsugit lint deck.md --strict
matsugit render deck.md --output /tmp/deck-preview
```

Use a new or empty output directory for each iteration. Preview is local and
does not publish. Inspect the actual slides and reading document, including
long titles, tables, media, source notes and narrow viewports. Optional
`matsugit lint deck.md --rendered /tmp/deck-preview --strict` needs Playwright
and Chromium. Lint is not proof of factual accuracy or perfect typography.

Fix crowded slides by splitting or simplifying with the author, not by silently
deleting content, shrinking everything, or hiding overflow. Media should retain
aspect ratio; never crop evidence to make it fit. Handouts include presenter
notes. Notes can also be present in slide HTML for presenter use: hidden is not
private. Remove secrets before distributing any artifact.

Return the source, preview, checks performed and remaining limitations. On a
remote host use its approved private preview mechanism; a server path is not a
browser link. Creating a deck or theme does not authorize publication, public
hosting, new credentials, or installation into unrelated repositories.
