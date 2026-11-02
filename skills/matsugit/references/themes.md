# Create a theme without creating another slide language

## Start with the visual contract

Use the user's approved brand source or reference. Identify type hierarchy,
palette, spacing, logos, footers, table treatment, chart emphasis and light/dark
requirements. Studying consulting exhibits is not permission to redistribute
their templates, logos or fonts. The included starter is original and neutral.

Copy `assets/themes/starter/` from this skill to a new directory, for example
`~/.config/matsugit/themes/review/`. Do not overwrite a selected existing theme.
Keep organization assets and private configuration outside the matsugit package.

```json
{
  "document": "document.css",
  "slides": "slides.scss",
  "charts": "charts.json",
  "assets": []
}
```

Only manifest-listed files are copied. List local font, logo and imported CSS
files in `assets`. Keep all paths within the theme root. References in CSS are
relative to that CSS file after copying. Themes are trusted CSS/SCSS, not a
sandbox for arbitrary third-party files. Prefer licensed local fonts with a
system fallback rather than silently adding network font requests.

Select the pack explicitly:

```sh
matsugit render deck.md --theme review --output /tmp/review-preview
```

Use `--themes-dir /path/to/themes` for a different root. Per-project
`matsugit.json` can select `{"theme":"review"}`. Global configuration and
environment defaults must not override an explicit project or CLI choice.

## Styling contract

matsugit renders HTML/Reveal, not arbitrary positioned objects. Use Quarto
SCSS sections `/*-- scss:defaults --*/` and `/*-- scss:rules --*/`. The generic
slide canvas is 1280x720 or 1280x960 for 4:3. Style the canvas, not the browser's
viewport width; Reveal performs the scaling. A separately managed organization
renderer can use a different canvas and adapter, which must be tested separately.

| Semantic target | Generic output selector |
| --- | --- |
| Content slide / title | `.reveal .ff-content`, `.ff-content > h2` |
| Smaller claim / body / takeaway | `.ff-claim`, `.ff-body`, `.ff-takeaway` |
| Section | `.ff-section` |
| Region heading | `.ff-division-heading` |
| Rows | `.ff-rows > .ff-row` |
| Columns | `.columns > .column` (Quarto) |
| Components | `.ff-metrics`, `.ff-comparison`, `.ff-timeline`, `.ff-decision`, `.ff-region` |
| Media / chart | `.ff-media`, `.ff-image`, `.ff-diagram`, `.ff-chart` |
| Roles | `.cover`, `.statement`, `.image-slide`, `.dense` on the slide |
| Evidence / attribution | `.compact`, `.data-table`, `.quotation`, `.source` |
| Handout | `.ff-handout-slide`, `.ff-speaker-notes` |

Reading HTML does not always have slide wrappers: e.g. authored `rows`/`row`
classes remain in the reading document. Test both surfaces. Do not assume a
slide selector styles documents, or that a generic `h3` selector styles claims.
The runtime owns layout/media behavior; theme rules should not hide evidence,
change source order, add invented content, or redefine H1/H2/H3 semantics.

The runtime currently consumes `--personal-blue`, `--personal-claim`,
`--personal-ink`, `--personal-rule`. These historical names are compatibility
hooks, not a requirement for personal branding. The starter defines its own
`--ff-*` tokens and maps these hooks to them. A fully versioned public token
contract is still a gap; do not invent a supported `tokens.json` manifest field.
Some runtime rules load after theme CSS: use scoped selectors with appropriate
specificity and inspect computed styles, rather than adding global `!important`.

Charts use a separate optional `charts.json`:

```json
{
  "accent": "#1769AA", "ink": "#20262D", "muted": "#788696",
  "grid": "#DAE1E8", "background": "#FFFFFF",
  "series": ["#1769AA", "#16806A", "#A86816", "#74539A"]
}
```

Only six-digit hex colors are supported; `series` has 1-8 colors. Chart font
configuration, semantic positive/negative tokens and a universal theme schema
are not yet implemented. Chart text currently uses DejaVu Sans. Mermaid uses
Quarto's `--mermaid-*` CSS variables; inspect actual rendered diagrams as labels
are measured in the browser.

## Inheritance

`extends` resolves another local theme, then child manifest fields/files override
the parent. It does **not** automatically concatenate CSS. Example:

```json
{"extends":"base","slides":"review.scss","assets":["review-logo.svg"]}
```

If the parent's stylesheet is `base.scss`, the child may explicitly import
`base.scss` then add rules. Use distinct filenames; replacing `slides.scss` and
importing `slides.scss` creates a self-import, not inheritance. Inherited files
are flattened into the exported theme. Cycles/depth over eight fail. Test an
export without the original theme directories to verify portability.

## Acceptance

Render the unchanged `assets/slide-types.md` corpus with the new theme. Charts
require the optional backend. Inspect all twelve types plus long-title, Unicode,
multi-series, nested-layout, 4:3 and image fixtures as relevant to the theme.
The corpus is a starting contract, not an exhaustive visual proof.

Check large topic vs smaller/lighter claim, readable evidence, distinct list
levels, table/body separation, meaningful chart colors, intact diagrams, and
source/footer legibility. Keep sources visually subordinate but readable.
Use direct labels or shapes as well as color for meaningful distinctions.
Avoid multiple redundant rules between neighboring components.

Render and inspect the reading document at narrow widths, and the optional
handout with notes. Check fonts/assets offline and with CI's Quarto version.
Use `matsugit lint ... --rendered ...` when available and screenshots for
manual review. Do not report a theme as tested based only on valid JSON/SCSS.

Roll out by selecting the new theme on a preview first. Leave existing defaults
and renderer releases unchanged until approved. Publishing a theme or updating
a managed renderer is distinct from deploying a real document.

Takeaways must read as conclusions, not footnotes. The shared runtime supplies
a filled, high-contrast band, near-body-size type and stronger weight. Set
`--ff-takeaway-bg` and `--ff-takeaway-ink` for the theme (default white ink on
its accent), and verify at least 4.5:1 text contrast. Keep source notes quiet.
Do not add invented takeaway wording or shrink evidence to make room.
