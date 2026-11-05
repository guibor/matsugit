# Twelve recipes, one compositional language

This is a bounded authoring vocabulary, not twelve new parser keywords. A recipe
combines existing primitives. Choose the recipe that proves the claim, then fill
it with evidence. A theme changes appearance, not the recipe's meaning.

The [editable corpus](../assets/slide-types.md) contains one original, synthetic
example of each recipe. It is also the theme acceptance fixture. It is not a
McKinsey, BCG or Pershing Square deck and contains no copied reference exhibits.

| # | Recipe | Compose it from | Use when |
| --- | --- | --- | --- |
| 1 | Cover | YAML title + `.cover`, optional claim/image | Establish purpose and audience |
| 2 | Section or statement | H1 divider or `.statement` | Change the question or emphasize one point |
| 3 | Answer summary | `assertion` + short evidence list | State the recommendation before details |
| 4 | KPI scorecard | `metrics` + `source` | Compare a small set of measures |
| 5 | One decisive exhibit | `.chart`, image or table + `source` | One exhibit carries the argument |
| 6 | Evidence and interpretation | `columns`, usually 65/35 | Explain a chart or exhibit beside it |
| 7 | Table and implication | `rows` + table + commentary | Preserve full table width and separate its meaning |
| 8 | Options or before/after | `comparison` | Evaluate alternatives on the same basis |
| 9 | Mechanism or process | Mermaid + optional commentary | Explain causal/operational structure |
| 10 | Roadmap | `timeline` | Show stages and explicit gates |
| 11 | Documentary evidence | `quotation` or image + `source` | Preserve important authorized wording/evidence |
| 12 | Quote | `.quote` + blockquote + `attribution` | Center an authorized quote and its visible author |
| 12 | Decision request | `decision` + optional `takeaway` | Name the action, conditions and responsibility |

Within a recipe, choose one dominant exhibit. A full-width table plus a paragraph
belongs in rows; a chart and its explanation belong in columns. Two charts can
sit in columns, but synchronized axes and shared legends are not implemented:
check them yourself and do not imply comparability that the data lacks.

## Grammar, not a template explosion

```text
slide = title + optional claim + body + optional takeaway
body  = evidence | semantic group | rows(regions) | columns(regions)
region = heading? + evidence/content
evidence = text | table | chart | image | Mermaid | quotation
attribution = source + optional presenter notes
```

Keep region counts within the parser's limits. Prefer one outer spatial
composition and, only when useful, one nested grouping. This is an authoring
guideline, not a new hard parser restriction. A recipe name is not a CSS class.

The twelve recipes are a deliberate starting set, not a claim that all consulting
decks have exactly twelve types. An appendix normally reuses exhibit, table and
documentary recipes rather than adding a thirteenth layout. Market sizing, a
business case, a risk review and a board update are storylines that reuse these
recipes; they should not each need a new parser or a dedicated theme.

Example storylines, not required deck orders:

- **Investment argument:** answer summary -> business mechanism -> decisive
  exhibits -> valuation table -> risks/options -> decision. Statement and
  documentary-evidence slides can punctuate the argument when the source calls
  for them, as in an Ackman-style teaching or investment presentation.
- **Operational recommendation:** answer summary -> baseline scorecard ->
  diagnosis/process -> alternatives -> roadmap -> decision and proof gates.
- **Reference reconstruction:** follow the original order and map each slide to
  a recipe; do not impose either storyline on an existing authorized deck.

## Adding a capability

Before proposing a new primitive:

1. Show at least two different recipe/use cases that cannot be expressed well
   with current blocks. A different arrangement or color is not enough.
2. Define the content meaning and validation rules, not pixel coordinates.
3. Specify its reading-document behavior as well as slide behavior.
4. Keep data, sources and edits in Markdown or declared local assets.
5. Test default and representative external themes, 16:9 and 4:3, narrow reading
   views, missing data, and existing reference fixtures without changing them.

A waterfall is a useful new *chart primitive*: both a financial bridge and an
energy-demand decomposition need it. An `investment-slide-blue-three-boxes`
primitive would merely encode one styling decision and should not be added.

For an authorized reconstruction, inventory the original slides into these
recipes first. Record genuine exceptions and native gaps. Preserve meaning,
wording, slide order and values; do not turn reference commentary into a takeaway
or force every reference slide into the same title/claim structure.
