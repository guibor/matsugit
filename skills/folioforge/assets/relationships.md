---
title: From evidence to action
subtitle: Semantic relationships, not hand-positioned arrows
slide-layout: structured
slide-section-dividers: false
slide-title-page: false
---

## One change enables a different outcome
### A whole-panel relationship connects two arguments, not individual bullets

:::: {.implication relation="enables"}
#### A shared intake
- One entry point for requests.
- An owner for every handoff.
- A visible quality gate.

#### A more predictable service
Teams can measure waiting time and resolve missing ownership before expanding.
::::

::: takeaway
Make the mechanism explicit before claiming that the outcome will follow.
:::

## Each insight leads to a specific action
### Aligned rows make the reasoning easy to inspect

::: {.mapping relation="suggests"}
| Insight | Action |
| :--- | :--- |
| Ownership changes during handoff. | Name one accountable owner. |
| Requests arrive through several channels. | Test a shared intake. |
| Faster delivery can conceal rework. | Pair the speed target with a quality gate. |
:::

::: takeaway
Every action should answer an observed problem.
:::

## Two measurements determine the decision
### Callouts point to named evidence and follow it when the layout changes

::::: annotated
:::: evidence
| Measure | Baseline | Pilot |
| :--- | ---: | ---: |
| Cycle time | 12 days | [8 days]{#pilot-cycle} |
| Rework | 18% | [18%]{#pilot-rework} |
| Requests reviewed | 64 | 78 |
::::

::: {.callout target="pilot-cycle"}
Cycle time fell by one third.
:::

::: {.callout target="pilot-rework"}
The quality measure did not deteriorate.
:::
:::::

::: source
Illustrative values only, not measured results.
:::

::: takeaway
Read speed and quality together, not as separate claims of success.
:::

## The same syntax can annotate an exhibit
### A named chart is a whole-exhibit target; data-point labels belong in Vega-Lite

:::::: annotated
::::: evidence
:::: {#cohort-comparison .chart type="bar" unit="requests" caption="Illustrative cohort sizes"}
| Cohort | Requests |
| :--- | ---: |
| Baseline | 64 |
| Pilot | 78 |
::::
:::::

::: {.callout target="cohort-comparison"}
The cohorts differ in size. Compare rates rather than raw totals.
:::
::::::

::: source
Synthetic example. Altair/Vega-Lite prepares the chart.
:::

::: takeaway
Annotation explains the evidence; it does not substitute for analysis.
:::
