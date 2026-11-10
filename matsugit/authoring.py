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
    'd2': '''## How the mechanism works
### Name the critical gate or dependency

```d2
direction: right
evidence: Evidence
review: Review
decision: Decision
evidence -> review: informs
review -> decision: enables
```
''',
    'process': '''## How the mechanism works
### Name the critical gate or dependency

```mermaid
flowchart LR
  A[Evidence] --> B[Review] --> C[Decision]
```
''',
    'quotation': '''## The evidence in its own words {.quote .hide-title .hide-claim}
### Why this passage matters

> Replace this placeholder with an authorized quotation.

::: attribution
-- Author, role or publication
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

TEMPLATES['quote'] = TEMPLATES['quotation']

# Small authoring elements share the renderer's existing syntax, not a new DSL.
ELEMENTS = {
    'canvas': '::: {.canvas src="visual.html" title="Interactive evidence"}\n:::\n',
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


# Plain-language names for the layout picker and help. Keys are editor names
# (see editor_templates). `group` says whether the recipe starts a new slide or
# goes inside the current one; `sketch` selects the picker's thumbnail.
CATALOG = {
    'slide': ('slide', 'Blank slide', 'A title, a claim and room for your points.', 'slide'),
    'cover': ('slide', 'Cover', 'Open the deck with its title and purpose.', 'cover'),
    'section': ('slide', 'Section heading', 'Start a new chapter of the deck.', 'section'),
    'statement': ('slide', 'Big statement', 'One sentence that deserves a whole slide.', 'statement'),
    'summary': ('slide', 'Answer first', 'The recommendation, then the reasons behind it.', 'summary'),
    'evidence': ('slide', 'Evidence beside its meaning', 'A table on the left, what it means on the right.', 'wide'),
    'table': ('slide', 'Table and what it means', 'A full-width table above, the implication below.', 'stack'),
    'exhibit': ('slide', 'One table', 'Let a single table carry the point.', 'table'),
    'chart-slide': ('slide', 'Chart', 'A bar chart drawn from a small table.', 'chart'),
    'metrics': ('slide', 'Key numbers', 'Up to four headline figures, each with a line of context.', 'metrics'),
    'comparison': ('slide', 'Compare options', 'Two or three alternatives, side by side.', 'columns'),
    'timeline': ('slide', 'Timeline', 'Stages in order, with dates or owners.', 'timeline'),
    'decision': ('slide', 'Decision request', 'What you ask for, the reservations and the proof needed.', 'columns3'),
    'process': ('slide', 'Flow diagram', 'Boxes and arrows drawn from a few lines of text.', 'flow'),
    'quotation': ('slide', 'Quote', 'A quotation with its author.', 'quote'),
    'implication': ('slide', 'Cause and effect', 'A change on the left leads to a result on the right.', 'arrow'),
    'mapping': ('slide', 'Insight to action', 'Pair each finding with what to do about it.', 'mapping'),
    'annotated': ('slide', 'Pointed-out evidence', 'Notes that point at the numbers that matter.', 'annotated'),
    'assertion': ('slide', 'Turning point', 'One bold sentence that changes direction.', 'statement'),
    'd2': ('slide', 'Relationship diagram', 'A richer diagram (D2). Needs the one-time diagram setup.', 'flow'),
    'section-deck': ('slide', 'Three-slide starter', 'A short section: conclusion, mechanism, takeaway.', 'section'),
    'claim': ('part', 'Claim under the title', 'The one-sentence point of this slide.', 'claim'),
    'takeaway': ('part', 'Takeaway', 'The conclusion band at the bottom of the slide.', 'takeaway'),
    'columns': ('part', 'Two columns', 'Two blocks side by side.', 'columns'),
    'columns-3': ('part', 'Three columns', 'Three blocks side by side.', 'columns3'),
    'columns-evidence': ('part', 'Wide and narrow columns', 'Evidence wide on the left, its meaning on the right.', 'wide'),
    'rows': ('part', 'Stacked rows', 'Two blocks, one above the other.', 'stack'),
    'table-block': ('part', 'Table', 'A small table to fill in.', 'table'),
    'chart-block': ('part', 'Chart from a table', 'Select a table first to turn it into a chart.', 'chart'),
    'region': ('part', 'Sub-heading', 'A small heading with points under it.', 'region'),
    'source': ('part', 'Source line', 'Where the evidence comes from.', 'source'),
    'notes': ('part', 'Presenter notes', 'Only you see these while presenting.', 'notes'),
    'break': ('part', 'Continue on a new page', 'Same title and claim, next page.', 'break'),
    'agent-comment': ('part', 'Note for the AI', 'A review request that never appears on slides.', 'comment'),
    'canvas': ('part', 'Interactive HTML', 'Embed a trusted local HTML file. Advanced.', 'canvas'),
}
# Aliases and duplicates stay available by typing "/", but not in the picker.
HIDDEN = {'quote', 'takeaway-block'}


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
            if key in CATALOG:
                group, title, when, sketch = CATALOG[key]
                entries[key].update(group=group, title=title, when=when, sketch=sketch,
                                    rank=list(CATALOG).index(key))
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
