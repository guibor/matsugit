# Charts: prepare with Altair, compose with Markdown

matsugit does not implement a plotting engine. Altair prepares Vega-Lite and
`vl-convert-python` renders local SVGs before Quarto runs. No chart CDN, external
data fetch, or Python execution from documents is needed. Theme palettes apply
at preparation time, and the resulting `.vl.json` stays beside each SVG in
`assets/`. `source.md` retains the editable table/spec for the next build.

```sh
matsugit setup-charts
```

This explicitly installs optional dependencies in an isolated environment.
CI can install `matsugit[charts]` instead; `MATSUGIT_CHART_PYTHON` selects an
existing interpreter. New setup-ci bundles include the renderer and its setup
command. Existing organization CI must use its documented renderer update flow.

## Simple data: a Markdown table

```markdown
::: {.chart type="stacked100" unit="accounts" caption="Illustrative adoption mix"}
| Cohort | Active | Inactive |
| :--- | ---: | ---: |
| Before | 40 | 60 |
| After | 65 | 35 |
:::
```

Types: `bar`, `barh`, `line`, `scatter`, `stacked`, `stacked100`. Units are
required. Up to 30 categories and four series. Normalized stacks require
nonnegative data and positive totals; they show shares, not original counts.
Line categories are equally spaced. Use Vega-Lite temporal X for actual dates.
`highlight="After"` works on a single-series bar/barh. Source text is separate.

Altair is preferred. An old Matplotlib-only installation continues rendering the
original four types with an upgrade warning. `backend="matplotlib"` explicitly
preserves that choice; new types and native specs require Altair. Installation
does not run automatically during a normal render.

## Rich exhibits: native Vega-Lite

Use a standard `vega-lite` JSON fence, including inline data. For example:

````markdown
```vega-lite
{
  "description": "Illustrative quarterly cycle time, in days",
  "data": {"values": [
    {"quarter": "2026-01-01", "days": 12},
    {"quarter": "2026-04-01", "days": 8}
  ]},
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "quarter", "type": "temporal", "title": "Quarter"},
    "y": {"field": "days", "type": "quantitative", "title": "Days", "scale": {"zero": true}}
  }
}
```
````

Author complex charts in a **separate, reviewed preparation script** using
Altair; paste `chart.to_json()` here with inline data. Do not paste executable
Python into a deck and expect matsugit to run it. Standard layers, transforms,
temporal axes, rules, error bands, heatmaps and waterfall calculations are
delegated to Vega-Lite. Arithmetic, units and factual interpretation still need
author review. [Altair's waterfall example](https://altair-viz.github.io/gallery/waterfall_chart.html)
illustrates the library approach; no new matsugit waterfall grammar is needed.

This is a bounded static subset, not every Vega feature: at most 1 MB of JSON,
5000 items per array, 40 nested levels and a 60-second worker limit. URLs, image
marks, hyperlinks, expression-valued properties, interactive parameters and
facet/concat/repeat are refused. Use inline data, standard declarative transforms
and matsugit columns/rows for composition. Rejected input produces an error,
not a blank chart or network request. Altair validates against its local schema.

## Size for the slot

Full exhibits prepare at 960 logical pixels wide; two equal columns at 466.
Explicit column ratios and evidence regions affect the preparation width.
Label fonts keep the same logical size. matsugit sets chart width/height and
fit autosizing, overriding native spec dimensions to match the slot. It then
preserves aspect ratio in the slide/document/handout. Inspect long category
labels and dense charts; simplify or split instead of hiding evidence.

## Clear ownership

- Altair/Vega-Lite: data encodings, axes, chart geometry, statistical marks.
- Mermaid (already integrated): process and relationship diagrams.
- Graphviz/D2 or other established tools: prepare externally and include SVG;
  they are not silently installed or advertised as native integrations.
- matsugit: safe preparation, palettes, layout slots, captions, sources,
  takeaways and portable outputs. No hand-built chart or graph-layout engine.
