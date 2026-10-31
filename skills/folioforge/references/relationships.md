# Relationships and saved evidence callouts

These opt-in blocks work across themes in Folioforge 0.7.0+. They are content
semantics, not a new theme. Ordinary columns, tables and old documents keep
their existing behavior. See the editable [four-slide example](../assets/relationships.md).

## One side leads to the other

```markdown
:::: {.implication relation="enables"}
#### Change
- One shared intake.
- Explicit ownership.

#### Result
Fewer handoffs and a measurable review gate.
::::
```

Two H4 regions form the sides; one large triangular connector relates the
**whole left panel** to the right. The number of bullets need not match.
Alternatively use exactly two `::: column` child blocks for untitled sides.
The optional `relation` label defaults to `leads to`. Write `supports`,
`suggests`, `enables`, or another short label that states the actual argument;
an arrow does not establish causality. Do not use this for a neutral comparison.

## Each point leads to its own counterpart

```markdown
::: {.mapping relation="suggests"}
| Insight | Action |
| :--- | :--- |
| Ownership is unclear. | Name a decision owner. |
| Handoffs add waiting. | Test one shared intake. |
:::
```

One ordinary two-column table, two headings and 1-6 complete data rows. Each
row receives its own connector and separator. Rich inline Markdown, links and
Unicode remain editable. No merged cells or table captions here; use an ordinary
table or columns when relationships are not one-to-one. A theme controls arrow
color, type and spacing. On narrow reading pages, each pair stacks in order
with its column labels repeated.

## Point to named evidence

```markdown
::::: annotated
:::: evidence
| Measure | Before | After |
| :--- | ---: | ---: |
| Cycle time | 12 days | [8 days]{#cycle} |
::::

::: {.callout target="cycle"}
Cycle time fell by one third.
:::
:::::
```

Name a Markdown span with `{#id}` or give a whole evidence div/table/code block
an ID. Wrap images in a named div instead of putting a target on the image
element. `target` must identify exactly one element **inside the same evidence
block**. IDs are unique across the document; each target gets one note. Use one
evidence block and 1-3 short callouts. Nested annotated groups, missing targets,
duplicate targets and empty notes fail with an actionable error.

Labels occupy a reserved side rail rather than covering the evidence. Numbers
and working links remain without JavaScript; wide views add connector arrows.
The browser recalculates pointers after resizing, slide navigation, image load
and font load. Narrow reading pages use numbered notes below the evidence.
Inspect arrows in the rendered output: target the relevant rightmost table cell
or an evidence region when a leader across a busy exhibit would obscure data.
There are no authored pixel coordinates, selectors, or cross-slide targets.

For a **specific chart data point**, prepare a native Altair/Vega-Lite text/rule
layer using data coordinates. The chart engine knows its axes; a DOM pointer
does not. A named chart block is a valid whole-exhibit target, not a back door
into individual bars inside its SVG. Charts still retain editable `.vl.json`.

## Insert and verify

```sh
folioforge template implication --output cause-and-effect.md
folioforge template mapping --fragment
folioforge template annotated --fragment
folioforge lint cause-and-effect.md --strict
folioforge render cause-and-effect.md --output /tmp/cause-and-effect-preview
```

Templates never overwrite an existing output file. Keep claims, takeaways and
sources outside these body blocks. Use synthetic values for experiments, then
replace them with supported evidence. Renderer updates are separate from
publication and must reach any vendored CI installation before using new syntax.
