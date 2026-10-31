---
title: Evidence and conclusions
slide-layout: structured
slide-section-dividers: false
slide-title-page: false
---

# Chart preparation

## Reduce time without adding rework
### The illustrative pilot cuts cycle time by one third

::: {.chart type="bar" unit="days" highlight="Pilot" caption="Median cycle time; synthetic data"}
| Cohort | Days |
| :--- | ---: |
| Baseline | 12 |
| Pilot | 8 |
:::

::: source
Demonstration data only. Not an observed result.
:::

::: takeaway
Expand only if the time saving persists without higher rework.
:::

## Separate adoption from volume
### A higher share is not proof of a larger market

:::: columns
#### Adoption mix
::: {.chart type="stacked100" unit="accounts" caption="Share of each cohort"}
| Cohort | Active | Inactive |
| :--- | ---: | ---: |
| Before | 40 | 60 |
| After | 65 | 35 |
:::

#### Cohort size
::: {.chart type="barh" unit="accounts" caption="Absolute count"}
| Cohort | Accounts |
| :--- | ---: |
| Before | 100 |
| After | 100 |
:::
::::

::: source
Synthetic cohorts; same denominator. Prepared for each column, not shrunk from a full chart.
:::

::: takeaway
Adoption improved; total cohort size did not change.
:::

## Keep analytical geometry in Vega-Lite
### Temporal spacing and reference lines use the library, not custom drawing

```vega-lite
{
  "description": "Illustrative cycle time against an eight-day gate",
  "data": {"values": [
    {"date": "2026-01-01", "days": 12},
    {"date": "2026-02-01", "days": 11},
    {"date": "2026-04-01", "days": 8}
  ]},
  "layer": [
    {"mark": {"type": "line", "point": true}, "encoding": {
      "x": {"field": "date", "type": "temporal", "title": "Measurement date"},
      "y": {"field": "days", "type": "quantitative", "title": "Days", "scale": {"zero": true}}
    }},
    {"mark": {"type": "rule", "strokeDash": [5, 4], "color": "#986111"},
     "encoding": {"y": {"datum": 8}}}
  ]
}
```

::: source
Synthetic data. Dashed line: illustrative decision gate.
:::

::: takeaway
Reaching the gate once is not enough: confirm it in the next cohort.
:::

## Turn evidence into a decision
### Keep the conclusion separate from attribution and supporting detail

:::: rows
#### Evidence
| Dimension | Observation | Next check |
| :--- | :--- | :--- |
| Speed | 12 to 8 days | Repeat in a new cohort |
| Adoption | 40% to 65% | Check sustained use |
| Rework | Not yet measured | Measure before rollout |

#### Decision
Approve a bounded follow-up. Retain the current rollout gate.
::::

::: source
All values on this slide are synthetic examples.
:::

::: takeaway
Fund the next test, not a full rollout.
:::
