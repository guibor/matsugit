# One language, any style

Every component is interpreted by the renderer, independently of the theme.
Themes change presentation, never capability or the source structure.

See [the syntax cookbook](syntax.md) for complete copyable examples, including
headings, columns, rows, evidence components, charts, media and explicit breaks.

For faithful reference reconstruction, preserve the original words and exhibits.
Do not invent takeaways or turn the original claims into commentary about a source.
Keep reconstruction notes separate from the slides.

Optional YAML `slide-aspect-ratio: "4:3"` uses the older presentation proportion;
the default remains `"16:9"`. `slide-title-page: false` omits the generated cover,
without removing the title from the reading document. Author one explicitly with
`## Title {.cover}`. Use `## The whole statement {.statement}` for a statement-only
slide, together with `slide-empty-slides: true`. `## {.image-slide}` creates a
titleless image slide. `.data-table` provides deliberate dense financial-table
spacing; `.quotation` preserves longer quotations without silently summarising.
These roles work in every style. They are explicit choices, not inferred rewrites.

Start with `matsugit template section --output deck.md`. Templates are ordinary
editable Markdown; the command refuses to overwrite an existing file.

```markdown
---
title: Decision brief
slide-layout: structured
slide-section-dividers: false
---

# Recommendation
## Test the process before scaling
### A small pilot can resolve the main uncertainty

:::: decision
#### Recommendation
Approve one bounded pilot.

#### Reservations
The benefit is not measured yet.

#### Proof gate
Require better speed without worse quality.
::::

::: takeaway
Buy evidence before buying scale.
:::

::: notes
Presenter guidance appears in the optional handout.
:::
```

Other starters: `metrics` (1-4 regions), `comparison` (2-3), `timeline` (2-6),
`decision` (2-4), `assertion`, `chart` and `section`. Regions start at H4.
Use existing `rows` / `columns` for explicit spatial composition, with or without
region titles. This syntax works in every theme, including the generic default.
Wrap a dense data table in `::: compact` when a deliberately tighter row spacing
is appropriate. This changes padding, not the data; it is available in every style.

## Table-backed charts

Run `matsugit setup-charts` once, or install `matsugit[charts]` in your own
environment. The preferred backend uses Altair/Vega-Lite; it does not execute document
code. It produces local SVG and retains the original editable table in source.md.

```markdown
:::: {.chart type="bar" unit="days" highlight="Pilot" caption="Illustrative values"}
| Cohort | Median duration |
| :--- | ---: |
| Baseline | 12 |
| Pilot | 8 |
::::

::: source
Synthetic example, not an observed treatment effect.
:::
```

Supported types: `bar`, `barh`, `line`, `scatter`. One category column plus 1-4
numeric series, up to 30 data rows. Units are required. Use numeric cells without
unit suffixes; missing values are rejected, never replaced by zeros. Scatter's
first column must be numeric; line charts treat categories as equally spaced.
`stacked` and `stacked100` also use tables; native `vega-lite` JSON fences cover
temporal axes, layers and richer marks. See [chart preparation](charts.md).
Do not use an equally spaced line chart to imply a continuous series across
missing years. Source and date belong in a `source` block.

Optional theme manifest `charts` points to JSON colour tokens. Optional `extends`
inherits another local theme; copied exports flatten dependencies for portable CI.
Child assets can override parent files; paths must stay within their theme root.

## Lint and handouts

`matsugit lint deck.md --strict` exits 2 for structural/density warnings.
`--json` produces machine-readable diagnostics. Without strict mode warnings do
not prevent editing. No automatic shrinking, clipping or content deletion occurs.

`matsugit render deck.md --handout --output preview` creates document, slides,
editable source and handout.html, in that order. Handouts include speaker notes,
so check for private information before sharing. Ordinary exports do not acquire
a handout unless explicitly requested or configured.

For optional browser checks, install `matsugit[lint]`, run
`playwright install chromium`, then `matsugit lint deck.md --rendered preview`.
`MATSUGIT_CHROMIUM` can point to an existing Chromium binary. Network requests
are blocked during checks; remote media therefore needs local verification.
Checks cover overflow, top-level overlap and broken images, not every possible
typographic or factual problem. Inspect the actual deck on the intended screen.

CI runners that rebuild native charts need Altair and vl-convert-python in their
Python environment; legacy Matplotlib remains available. See [charts.md](charts.md).
No new dependency is required for documents without chart blocks. Installing or
updating matsugit never enables hosting or changes a repository's visibility.

See `examples/decision-demo.md` for a complete original consulting-style story
using the components together. Its data and commercial assumptions are synthetic.
