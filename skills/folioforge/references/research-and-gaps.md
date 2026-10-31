# Research and capability gaps

Reviewed 2026-10-31 against Folioforge 0.5.2. This is a capability audit and design
direction, not promised syntax or a delivery schedule. The public examples below
inform composition; no reference slides, logos or private source files are
bundled with this skill.

## Public reference sample

Page numbers below are one-based PDF pages, not printed slide numbers. These
are observations of selected pages, not an exhaustive study of every slide.

- [USPS, Envisioning America's Future Postal Service, McKinsey, 2010](https://about.usps.com/future-postal-service/mckinsey-march-2nd-presentation2.pdf):
  pages 5, 8, 13-15 pair an answer-bearing title with a bridge, a ranked exhibit,
  or an actual/forecast comparison; explanation and consequence sit next to the
  evidence. This suggests reusable exhibit-plus-interpretation composition and
  native bridges, not a bespoke USPS slide type. The web PDF reader was usable;
  a direct local download returned 404 during review.
- [UK Department of Energy and Climate Change, electricity-efficiency study, 2012](https://assets.publishing.service.gov.uk/media/5a78a166e5274a277e68e3be/7035-capturing-full-elec-eff-potential-edr.pdf):
  pages 6-7 show a cumulative decomposition and a methodology/exhibit split.
  The second retains intermediate totals, an emphasized scenario, a footnote and
  attribution. This exposes gaps in bridge semantics and analytical annotations,
  while columns already express the spatial layout. Those pages were also
  inspected as locally rendered images.
- [New Zealand Treasury, McKinsey Future of Work evidence base, 2019](https://www.treasury.govt.nz/sites/default/files/2019-04/fowtf-evidence-base-4080406.PDF):
  pages 4-10 use scenario comparisons, a geographic exhibit, aligned regional
  comparisons and composition by industry. Our inference is that shared scales,
  stacked series, maps and explicit scenario/period semantics matter more than
  a large template catalogue. The web PDF reader was usable; the local download
  was blocked, so local visual verification was not claimed.

[Slideworks' public deck index](https://slideworks.io/resources/47-real-mckinsey-presentations)
was used to discover publisher/client sources, not as proof of renderer behavior.
These historic documents are design references, not current business forecasts.
Reuse composition ideas; do not infer a right to redistribute third-party decks.

## What is already native, composable, or missing?

| Capability | Today | Honest fallback / next step |
| --- | --- | --- |
| Title, claim, exhibit, source, takeaway | Native | Choose a recipe, not another theme-specific parser |
| Full exhibit, 65/35 split, table above implication | Composable with columns/rows | No new primitive needed |
| Metrics, options, stages, decisions, quotation | Native | Author values and statements; renderer does not infer them |
| Bar/barh, categorical line, numeric scatter | Native bounded charts | 30 rows, 1-4 value series; explicit unit |
| Financial/operational bridge | Missing native waterfall | Use a reviewed local exhibit image; add totals/deltas/subtotals semantics first |
| Mix or contribution to a whole | Missing stacked/100%-stacked, area, Mekko | Plain table or external chart; never treat grouped bars as stacked |
| Scenario, forecast and uncertainty | Partial: multiple series | Missing date axis, forecast boundary, ranges/error bars and benchmark lines |
| Analytical annotations | Partial: one-category bar highlight | Missing data-anchored arrows, brackets, deltas and source-linked callouts |
| Small multiples | Spatial columns only | No shared axes/legend contract or automated scale-comparability check |
| 2x2 portfolio / heatmap | Table or Mermaid approximation | Missing native axes, weighted points and quantitative cells; do not fake numeric geometry |
| Geography | External image | No native choropleth, geographic joins or map projection |
| Process / logic tree | Mermaid | No dedicated editable value-driver model or dated-resource swimlane |
| Evidence/source management | Authored source text | No stable evidence IDs, automatic footnote registry or reconciliation across slides |
| Finite slide recipes | Documented and example-tested | No machine-validated recipe schema or complete theme conformance suite |
| Theme styling | Manifest, inheritance, CSS, chart colors | No versioned semantic token schema; chart fonts remain fixed |
| Output and QA | HTML document/slides, optional handout, lint | No integrated editable PPTX/PDF command, visual diff service or reference-fidelity score |

External SVG/PNG can cover a missing exhibit but is not native, data-editable
Markdown support. Ordinary Quarto capabilities are not automatically Folioforge
capabilities: the metadata allowlist deliberately rejects executable settings.

## Prioritize primitives, not templates

1. **Analytical chart grammar:** waterfall with explicit totals/subtotals,
   stacked/100% bars, numeric/date axes, benchmarks and forecast/range semantics.
   Validate arithmetic and units before drawing. Keep data in an ordinary table.
2. **Exhibit annotations:** attach labels/brackets/callouts to data or named
   regions, not browser coordinates. Give them source, reading and accessibility
   representations. This serves nearly every existing recipe.
3. **Matrix and small-multiple primitives:** clear axes, explicit cell/point
   semantics, shared scale/legend rules, then geographic exhibits if needed.
4. **Theme/evidence contracts:** generic versioned tokens, declared contrast and
   text budgets, source IDs, conformance fixtures and visual regression baselines.
   Add this incrementally without breaking old theme hooks or old documents.

Keep the twelve recipes in [slide-types.md](slide-types.md) bounded. A proposed
addition should enable multiple recipes, survive theme changes and produce a
useful reading document. Prefer separate opt-in attributes to heuristic rewriting.
Legacy documents and all installed themes remain a compatibility obligation.
