"""Explicit relationships and named evidence annotations, independent of themes."""
from collections import Counter
import re

if __package__:
    from .layout import body_headings, classes, div, divisions, has_content, plain
else:
    from layout import body_headings, classes, div, divisions, has_content, plain

KINDS = {'implication', 'mapping', 'annotated'}


def attrs(node):
    kind = node.get('t')
    if kind == 'Header':
        return node['c'][1]
    if kind in ('Div', 'Span', 'CodeBlock', 'Table', 'Figure', 'Image', 'Link', 'Code'):
        return node['c'][0]
    return None


def nodes(node):
    if isinstance(node, list):
        for child in node:
            yield from nodes(child)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            yield from nodes(value)


def validate_targets(node):
    """Do not emit an ambiguous anchor, including duplicates outside its group."""
    targets = [dict(n['c'][0][2]).get('target', '').removeprefix('#')
               for n in nodes(node) if 'callout' in classes(n)]
    if not targets:
        return
    counts = Counter(a[0] for n in nodes(node) if (a := attrs(n)) and a[0])
    for target in targets:
        if counts[target] != 1:
            raise ValueError(f'Callout target {target!r} must name exactly one evidence element')
        if counts['ff-note-' + target]:
            raise ValueError(f'Reserved callout ID already exists: ff-note-{target}')


def options(block, allowed):
    pairs = block['c'][0][2]
    values = dict(pairs)
    if len(values) != len(pairs) or set(values) - set(allowed):
        raise ValueError(f'{classes(block)[0]}: use only these options: {", ".join(allowed)}')
    return values


def relation(block):
    value = options(block, ('relation',)).get('relation', 'leads to').strip()
    if not value or len(value) > 60 or any(ord(c) < 32 for c in value):
        raise ValueError('relation must be a short, nonempty label (at most 60 characters)')
    return value


def arrow(label):
    return div(['ff-relation'], [{'t': 'Plain', 'c': [
        {'t': 'Span', 'c': [['', ['ff-relation-label'], []], [{'t': 'Str', 'c': label}]]}]}])


def implication(block, prepare):
    label = relation(block)
    parts = divisions(block, 'implication', 'column')
    if len(parts) != 2:
        raise ValueError('An implication needs exactly two H4 regions or column blocks')
    for part in parts:
        part['c'][0][1] = ['ff-premise' if c == 'column' else c for c in classes(part)]
        part['c'][1] = body_headings(prepare(part['c'][1]))
    parts[1]['c'][0][1] = ['ff-consequence' if c == 'ff-premise' else c for c in classes(parts[1])]
    block['c'][0][1].append('ff-implication')
    block['c'][0][2] = []
    block['c'][1] = [parts[0], arrow(label), parts[1]]
    return block


def mapping(block, prepare):
    label = relation(block)
    children = block['c'][1]
    if len(children) != 1 or children[0].get('t') != 'Table':
        raise ValueError('A mapping needs one ordinary two-column Markdown table')
    _, caption, specs, head, bodies, foot = children[0]['c']
    rows = [r for body in bodies for r in body[2] + body[3]]
    if caption[1] or foot[1] or len(specs) != 2 or len(head[1]) != 1 or not 1 <= len(rows) <= 6:
        raise ValueError('A mapping needs two columns, one header, 1-6 rows and no caption/footer')
    if any(len(row[1]) != 2 or any(cell[2:4] != [1, 1] for cell in row[1])
           for row in head[1] + rows):
        raise ValueError('Mapping tables cannot contain merged cells')
    labels = [plain(cell[4]).strip() for cell in head[1][0][1]]
    if not all(labels):
        raise ValueError('Both mapping columns need a heading')
    output = []
    for index, row in enumerate(head[1] + rows):
        cells = []
        for col, cell in enumerate(row[1]):
            if not has_content(cell[4]) or not plain(cell[4]).strip():
                raise ValueError('Every mapping cell needs content')
            content = div(['ff-mapping-cell'], body_headings(prepare(cell[4])))
            content['c'][0][2] = [['role', 'columnheader' if index == 0 else 'cell'],
                                 ['data-column', labels[col]]]
            cells.append(content)
        middle = arrow(label)
        middle['c'][0][2].append(['role', 'cell' if index else 'columnheader'])
        if not index:
            middle['c'][0][2].append(['aria-label', 'Relationship'])
        result = div(['ff-mapping-head' if index == 0 else 'ff-mapping-row'],
                     [cells[0], middle, cells[1]])
        result['c'][0][2].append(['role', 'row'])
        output.append(result)
    block['c'][0][1].append('ff-mapping')
    block['c'][0][2] = [['role', 'table'], ['aria-label', f'{labels[0]} {label} {labels[1]}']]
    block['c'][1] = output
    return block


def annotated(block, prepare):
    options(block, ())
    children = block['c'][1]
    if not 2 <= len(children) <= 4 or 'evidence' not in classes(children[0]) or any(
            'callout' not in classes(n) for n in children[1:]):
        raise ValueError('An annotated block needs one evidence block followed by 1-3 callouts')
    if any('annotated' in classes(n) for n in nodes(children)):
        raise ValueError('Annotated evidence groups cannot be nested')
    evidence = prepare(children[0])
    if not has_content(evidence['c'][1]):
        raise ValueError('Annotated evidence cannot be empty')
    evidence['c'][0][1].append('ff-evidence')
    notes, seen = [], set()
    for number, note in enumerate(children[1:], 1):
        target = options(note, ('target',)).get('target', '').removeprefix('#')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,79}', target):
            raise ValueError('A callout needs target="name", matching an evidence ID')
        matches = [n for n in nodes(evidence) if (a := attrs(n)) and a[0] == target]
        if len(matches) != 1 or target in seen:
            raise ValueError(f'Callout target {target!r} must occur once inside its evidence; combine repeated notes')
        element = matches[0]
        if element['t'] not in ('Span', 'Div', 'Header', 'Table', 'CodeBlock', 'Figure'):
            raise ValueError('Name a text span or evidence block, not a link or an image itself')
        if not has_content(note['c'][1]):
            raise ValueError('A callout needs explanatory text')
        seen.add(target)
        a = attrs(element)
        a[1].append('ff-annotation-target')
        a[2].extend([['data-ff-number', str(number)], ['aria-describedby', 'ff-note-' + target]])
        note['c'][0] = ['ff-note-' + target, ['ff-callout'], [['data-target', target]]]
        link = {'t': 'Link', 'c': [['', ['ff-callout-number'], [['aria-label', f'Go to evidence {number}']]],
                                  [{'t': 'Str', 'c': str(number)}], ['#' + target, '']]}
        note['c'][1] = [{'t': 'Plain', 'c': [link]}] + body_headings(prepare(note['c'][1]))
        notes.append(note)
    block['c'][0][1].append('ff-annotated')
    block['c'][1] = [evidence, div(['ff-callouts'], notes)]
    return block
