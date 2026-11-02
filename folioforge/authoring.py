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

# Small authoring elements share the renderer's existing syntax, not a new DSL.
ELEMENTS = {
    'slide': '## Slide title\n### Main claim\n\n- Supporting evidence.\n',
    'section': '# Section title\n',
    'claim': '### Main claim\n',
    'region': '#### Region title\n\n- Supporting point.\n',
    'takeaway': '> [!TAKEAWAY]\n> Key takeaway.\n',
    'takeaway-block': '::: takeaway\nKey takeaway.\n:::\n',
    'columns': ':::: columns\n#### First column\n\n- Supporting point.\n\n#### Second column\n\n- Supporting point.\n::::\n',
    'columns-3': ':::: columns\n#### First column\n\n- Supporting point.\n\n#### Second column\n\n- Supporting point.\n\n#### Third column\n\n- Supporting point.\n::::\n',
    'columns-evidence': ':::: columns 2:1\n#### Evidence\n\n- Supporting evidence.\n\n#### Implication\n\n- What the evidence means.\n::::\n',
    'chart-block': '::: {.chart type="barh" unit="minutes"}\n| Experience | Minutes |\n| :--- | ---: |\n| Baseline | 12 |\n| Pilot | 8 |\n:::\n',
    'rows': '::::: rows\n:::: row\nFirst block of evidence.\n::::\n\n:::: row\nSecond block of evidence.\n::::\n:::::\n',
    'notes': '::: notes\nPresenter notes.\n:::\n',
    'source': '::: source\nSource, date, page or link.\n:::\n',
    'break': '\n---\n\n',
    'table-block': '| Measure | Value |\n| :--- | ---: |\n| Example | 0 |\n',
    'agent-comment': ':::: {.agent-comment #review-INSERT_ID status="open"}\nRequest:\nDescribe the change or question for this slide.\n\nResponse:\nPending.\n::::\n',
}


def editor_templates():
    """Build the editor catalogue using the same Markdown/Org conversion as CLI."""
    from .source import convert
    from .converter import converter
    command = converter()
    entries = {}
    for kind, group in [('Slide', TEMPLATES), ('Element', ELEMENTS)]:
        for name, text in group.items():
            key = ({'section': 'section-deck', 'chart': 'chart-slide'}.get(name, name)
                   if kind == 'Slide' else name)
            # The shared converter intentionally removes hidden agent comments.
            org = ('#+begin_agent-comment :id "review-INSERT_ID" :status "open"\n'
                   'Request:\nDescribe the change or question for this slide.\n\n'
                   'Response:\nPending.\n#+end_agent-comment\n') if name == 'agent-comment' else convert(text, 'markdown', 'org', command)
            entries[key] = {'kind': kind, 'markdown': text, 'org': org}
    return entries


def template(name, output=None, fragment=False, fmt='markdown'):
    catalogue = {**ELEMENTS, **TEMPLATES}
    if name not in catalogue:
        raise ValueError('Choose a template: ' + ', '.join(catalogue))
    text = catalogue[name]
    if not fragment:
        text = ('---\ntitle: Working deck\nslide-layout: structured\n'
                'slide-section-dividers: false\n---\n\n' + text)
    if fmt == 'org':
        from .source import convert
        from .converter import converter
        if name == 'agent-comment':
            text = editor_templates()['agent-comment']['org']
        else:
            text = convert(text, 'markdown', 'org', converter())
    elif fmt != 'markdown':
        raise ValueError('Template format must be markdown or org')
    if output is None:
        return text
    with Path(output).open('x', encoding='utf-8') as file:
        file.write(text)
    return str(output)
