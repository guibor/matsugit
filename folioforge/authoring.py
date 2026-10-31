"""Small editable Markdown templates; no publication or source overwrites."""
from pathlib import Path

TEMPLATES = {
    'cover': '''## Working deck {.cover}
### The purpose and decision this deck supports

Prepared for the review meeting.
''',
    'statement': '''## One point to remember {.statement}

One sentence that advances the argument.
''',
    'summary': '''## The recommendation in brief
### State the answer before the supporting evidence

::: assertion
The bounded action recommended.
:::

- Evidence supporting the recommendation.
- The main uncertainty.
- The next decision gate.
''',
    'exhibit': '''## One exhibit carries the argument
### State what the comparison demonstrates

| Measure | Baseline | Pilot |
| :--- | ---: | ---: |
| Cycle time, days | 12 | 8 |
| Rework, percent | 18 | 18 |

::: source
Illustrative values. Replace with observed evidence and its period.
:::
''',
    'evidence': '''## Evidence and interpretation
### Explain the evidence beside it

::::: columns
:::: {.column width="65%"}
#### Evidence
| Measure | Baseline | Pilot |
| :--- | ---: | ---: |
| Cycle time, days | 12 | 8 |
::::
:::: {.column width="35%"}
#### Interpretation
What follows from the comparison, and what remains uncertain.
::::
:::::

::: source
Illustrative values. Replace with observed evidence.
:::
''',
    'table': '''## Evidence above, implication below
### Keep the table full width

::::: rows
:::: row
| Measure | Baseline | Pilot |
| :--- | ---: | ---: |
| Cycle time, days | 12 | 8 |
| Rework, percent | 18 | 18 |
::::
:::: row
#### Interpretation
Explain what the table supports, separately from the table itself.
::::
:::::

::: source
Illustrative values. Replace with observed evidence.
:::
''',
    'process': '''## How the mechanism works
### Name the critical gate or dependency

```mermaid
flowchart LR
  A[Evidence] --> B[Review] --> C[Decision]
```
''',
    'quotation': '''## The evidence in its own words
### Explain why this passage matters

> Replace this placeholder with an authorized quotation.

::: source
Author, document, date and page or link.
:::
''',
    'implication': '''## The mechanism connects the two sides
### State the relationship, not just a comparison

:::: {.implication relation="enables"}
#### Change
- One shared intake.
- Explicit ownership.

#### Result
Fewer handoffs and a measurable review gate.
::::
''',
    'mapping': '''## Each insight has a corresponding action

::: {.mapping relation="suggests"}
| Insight | Action |
| :--- | :--- |
| Ownership is unclear. | Name one decision owner. |
| Handoffs add waiting. | Test one shared intake. |
| Rework is not measured. | Add a quality gate. |
:::
''',
    'annotated': '''## Point to the evidence that changes the decision

::::: annotated
:::: evidence
| Measure | Baseline | Pilot |
| :--- | ---: | ---: |
| Cycle time | 12 days | [8 days]{#pilot-cycle} |
| Rework | 18% | [18%]{#pilot-rework} |
::::

::: {.callout target="pilot-cycle"}
Cycle time fell by one third.
:::

::: {.callout target="pilot-rework"}
Quality did not deteriorate.
:::
:::::

::: source
Illustrative values, not measured results.
:::
''',
    'metrics': '''## The key measures support the decision
### State the comparison period and scope

:::: metrics
#### Completion
**78%**

Baseline: 64%.

#### Cycle time
**8 days**

Baseline: 12 days.

#### Rework
**11%**

Baseline: 18%.
::::

::: source
Illustrative values. Replace with sourced evidence.
:::
''',
    'comparison': '''## Compare options against the same criteria

:::: comparison
#### Option A
- Strength.
- Constraint.

#### Option B
- Strength.
- Constraint.
::::
''',
    'timeline': '''## Sequence the work around explicit gates

:::: timeline
#### Weeks 1-2
Baseline. Owner: operations.

#### Weeks 3-6
Pilot. Owner: product.

#### Week 7
Decision gate. Owner: sponsor.
::::
''',
    'decision': '''## Approve a bounded next step

:::: decision
#### Recommendation
The action requested.

#### Reservations
The material uncertainty.

#### Proof gate
Evidence required before expansion.
::::

::: takeaway
State the decision, owner and deadline.
:::
''',
    'assertion': '''## The next question

::: assertion
One consequential sentence that changes the direction of the argument.
:::
''',
    'chart': '''## The comparison reveals the main change

:::: {.chart type="bar" unit="people" highlight="Pilot" caption="Illustrative cohort sizes"}
| Cohort | People |
| :--- | ---: |
| Baseline | 64 |
| Pilot | 78 |
::::

::: source
Illustrative values. Replace with sourced evidence.
:::
''',
    'section': '''# Decision context

## State the conclusion first
### Define the scope of this evidence cluster

- Supporting evidence.

## Explain the mechanism

- The reason the result changes the decision.

## Resolve the question

::: takeaway
The implication that follows from this cluster.
:::
''',
}


def template(name, output=None, fragment=False, fmt='markdown'):
    if name not in TEMPLATES:
        raise ValueError('Choose a template: ' + ', '.join(TEMPLATES))
    text = TEMPLATES[name]
    if not fragment:
        text = ('---\ntitle: Working deck\nslide-layout: structured\n'
                'slide-section-dividers: false\n---\n\n' + text)
    if fmt == 'org':
        from .source import convert
        from .converter import converter
        text = convert(text, 'markdown', 'org', converter())
    elif fmt != 'markdown':
        raise ValueError('Template format must be markdown or org')
    if output is None:
        return text
    with Path(output).open('x', encoding='utf-8') as file:
        file.write(text)
    return str(output)
