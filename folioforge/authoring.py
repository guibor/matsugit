"""Small editable Markdown templates; no publication or source overwrites."""
from pathlib import Path

TEMPLATES = {
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


def template(name, output=None, fragment=False):
    if name not in TEMPLATES:
        raise ValueError('Choose a template: ' + ', '.join(TEMPLATES))
    text = TEMPLATES[name]
    if not fragment:
        text = ('---\ntitle: Working deck\nslide-layout: structured\n'
                'slide-section-dividers: false\n---\n\n' + text)
    if output is None:
        return text
    with Path(output).open('x', encoding='utf-8') as file:
        file.write(text)
    return str(output)
