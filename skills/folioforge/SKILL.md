---
name: folioforge
description: Author composable Markdown slide decks and reading documents with Folioforge, or create and validate Folioforge theme packs. Use for Folioforge syntax, evidence-led slide recipes, theme design, and local previews; not for arbitrary PowerPoint editing.
---

# Folioforge

Produce an editable argument, not a collection of hand-positioned slide objects.
Use Markdown for meaning, a small set of recipes for composition, and a theme
for presentation. Do not change the renderer or an existing theme just to fit
one slide.

## Choose the workflow

- **Write or revise a deck:** read [authoring.md](references/authoring.md) and
  [slide-types.md](references/slide-types.md). Start with the closest recipe in
  [slide-types.md](assets/slide-types.md), not a new layout language.
- **Create or adapt a theme:** read [themes.md](references/themes.md). Copy the
  [starter pack](assets/themes/starter/theme.json) into a new theme directory;
  validate it with the same twelve-slide corpus, without editing the corpus to
  conceal theme defects.
- **Evaluate a missing capability:** read [research-and-gaps.md](references/research-and-gaps.md).
  Distinguish native support, composition from existing blocks, external-image
  fallback, and proposed features. Never invent supported options.

## Establish the contract

Check `folioforge --help` and the project's `folioforge.json` before choosing
commands or changing defaults. Respect an explicitly selected theme, target
repository and legacy layout. Python 3.10+, Git and Quarto are prerequisites;
charts and browser lint have optional dependencies. These files also work when
the skill is installed separately from the Folioforge checkout.

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
folioforge lint deck.md --strict
folioforge render deck.md --output /tmp/deck-preview
```

Use a new or empty output directory for each iteration. Preview is local and
does not publish. Inspect the actual slides and reading document, including
long titles, tables, media, source notes and narrow viewports. Optional
`folioforge lint deck.md --rendered /tmp/deck-preview --strict` needs Playwright
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
