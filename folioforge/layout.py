"""Theme-independent slide structure, using the established Pandoc AST convention."""
from copy import deepcopy


def classes(block):
    return block['c'][0][1] if block.get('t') == 'Div' else []


def div(names, blocks):
    return {'t': 'Div', 'c': [['', names, []], blocks]}


def metadata(meta):
    """Keep display/layout metadata, never executable Quarto configuration."""
    result = {key: deepcopy(meta[key]) for key in ('title', 'subtitle') if key in meta}
    for key in ('slide-layout', 'slide-section-dividers', 'slide-empty-slides'):
        if key not in meta:
            continue
        value = meta[key]
        if key == 'slide-layout':
            text = plain(value)
            if text not in ('default', 'structured', 'title-claim'):
                raise ValueError('slide-layout must be default, structured or title-claim')
        elif value.get('t') != 'MetaBool' or not isinstance(value.get('c'), bool):
            raise ValueError(f'{key} must be true or false, not a quoted string')
        result[key] = deepcopy(value)
    return result


def plain(node):
    if isinstance(node, list):
        return ''.join(plain(n) for n in node)
    if not isinstance(node, dict):
        return ''
    kind, value = node.get('t'), node.get('c')
    if kind in ('Str', 'MetaString'):
        return value
    if kind in ('Space', 'SoftBreak', 'LineBreak'):
        return ' '
    if kind in ('Code', 'Math', 'RawInline'):
        return value[1]
    return plain(value)


def has_content(blocks):
    # Comments and empty headings are scaffolding; images/code/tables are content.
    for block in blocks:
        kind = block.get('t')
        if kind in ('Header', 'HorizontalRule', 'Null'):
            continue
        if kind == 'RawBlock':
            text = block['c'][1].strip()
            if not text or (text.startswith('<!--') and text.endswith('-->')):
                continue
        if kind == 'Div':
            if has_content(block['c'][1]):
                return True
        else:
            return True
    return False


def body_headings(node, minimum=4):
    """Avoid nested Reveal sections while retaining accessible body headings."""
    if isinstance(node, list):
        return [body_headings(n, minimum) for n in node]
    if not isinstance(node, dict):
        return node
    if node.get('t') == 'Header':
        level, attrs, content = node['c']
        if level < minimum:
            raise ValueError('Use H4 for content divisions inside a slide or column')
        return {'t': 'Div', 'c': [[attrs[0], attrs[1] + ['ff-division-heading'],
                                  attrs[2] + [['role', 'heading'], ['aria-level', str(level)]]],
                                 [{'t': 'Plain', 'c': content}]]}
    return {key: body_headings(value, minimum) for key, value in node.items()}


def divisions(block, group, item):
    """Split explicit regions or H4-delimited regions without guessing content."""
    children = block['c'][1]
    if children and all(item in classes(b) for b in children):
        parts = children
    else:
        parts = []
        for child in children:
            if child.get('t') == 'Header' and child['c'][0] == 4:
                parts.append(div([item], []))
            if not parts or item in classes(child):
                raise ValueError(f'{group.title()} need H4 headings or explicit {item} blocks; do not mix them')
            parts[-1]['c'][1].append(child)
    if len(parts) not in (2, 3):
        raise ValueError(f'Use two or three {group}')
    for part in parts:
        if not has_content(part['c'][1]):
            raise ValueError(f'Each {item} needs content')
    return parts


def columns(block):
    """Support explicit columns and H4-delimited columns inserted by Emacs."""
    parts = divisions(block, 'columns', 'column')
    for part in parts:
        part['c'][1] = body_headings(prepare_divisions(part['c'][1]))
        if 'width' not in dict(part['c'][0][2]):
            part['c'][0][2].append(['width', f'{100 / len(parts):g}%'])
    block['c'][1] = parts
    return block


def rows(block):
    """Stack authored sections; use names that cannot collide with Bootstrap."""
    parts = divisions(block, 'rows', 'row')
    block['c'][0][1] = ['ff-rows' if c == 'rows' else c for c in classes(block)]
    for part in parts:
        part['c'][0][1] = ['ff-row' if c == 'row' else c for c in classes(part)]
        part['c'][1] = body_headings(prepare_divisions(part['c'][1]))
    block['c'][1] = parts
    return block


def prepare_divisions(node):
    if isinstance(node, list):
        return [prepare_divisions(n) for n in node]
    if not isinstance(node, dict):
        return node
    if 'columns' in classes(node):
        return columns(node)
    if 'rows' in classes(node):
        return rows(node)
    return {key: prepare_divisions(value) for key, value in node.items()}


def groups(blocks, layout):
    """Group the fixed H1/H2 structure, or legacy parent-title/child-claim layout."""
    levels = sorted({b['c'][0] for b in blocks if b.get('t') == 'Header'})
    top, second = (1, 2) if layout == 'structured' else (levels[0] if levels else 1,
                         levels[1] if len(levels) > 1 else 2)
    sections, current, parent = [], None, None
    for block in blocks:
        level = block['c'][0] if block.get('t') == 'Header' else None
        if level in (top, second):
            current = {'heading': deepcopy(block), 'blocks': [], 'parent':parent if level == second else None,
                       'section':level == top}
            if level == top:
                parent = current
            sections.append(current)
        else:
            if current is None:
                if not has_content([block]):
                    continue
                current = {'heading': {'t':'Header', 'c':[2, ['overview', [], []], [{'t':'Str','c':'Overview'}]]},
                           'blocks':[], 'parent':None, 'section':False}
                sections.append(current)
            current['blocks'].append(block)
    return sections


def content(section, layout, include_empty):
    segments = [[]]
    for block in section['blocks']:
        if block.get('t') == 'HorizontalRule':
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(deepcopy(block))
    out, inherited_claim = [], None
    for index, segment in enumerate(segments):
        if index and not segment:
            continue
        claim, takeaway, body = None, None, []
        for block in segment:
            if block.get('t') == 'Header' and block['c'][0] == 3 and layout == 'structured':
                if section['section']:
                    raise ValueError('An H3 subtitle needs an H2 slide title first')
                if claim or has_content(body):
                    raise ValueError('Put one H3 subtitle directly after H2 or a slide break; use H4 for body headings')
                claim = div(['claim', 'ff-claim'], [{'t':'Para','c':block['c'][2]}])
            elif 'claim' in classes(block):
                if claim:
                    raise ValueError('Use one claim per slide')
                claim = block
                claim['c'][0][1].append('ff-claim')
            elif 'takeaway' in classes(block):
                if takeaway:
                    raise ValueError('Use one takeaway per slide; separate slides with ---')
                takeaway = block
                takeaway['c'][0][1].append('ff-takeaway')
            else:
                body.append(prepare_divisions(block))
        if not has_content(body) and not claim and not takeaway and not include_empty:
            continue
        heading = deepcopy(section['heading'])
        if layout == 'title-claim' and section['parent']:
            claim = claim or div(['claim', 'ff-claim'], [{'t':'Para', 'c':deepcopy(heading['c'][2])}])
            heading['c'][2] = deepcopy(section['parent']['heading']['c'][2])
        claim = claim or inherited_claim
        if claim:
            inherited_claim = deepcopy(claim)
        heading['c'][0] = 2
        heading['c'][1][1].append('ff-content')
        if index:
            heading['c'][1][0] += f'-continuation-{index + 1}'
        out.append(heading)
        if claim:
            out.append(claim)
        if body:
            out.append(div(['ff-body'], body_headings(body, 4 if layout == 'structured' else 3)))
        if takeaway:
            out.append(takeaway)
    return out


def slides(ast):
    result = deepcopy(ast)
    meta = result['meta']
    layout = plain(meta.get('slide-layout')) or 'default'
    if layout == 'default' and not any(key in meta for key in ('slide-section-dividers', 'slide-empty-slides')):
        return result
    section_dividers = meta.get('slide-section-dividers', {'c':True})['c']
    include_empty = meta.get('slide-empty-slides', {'c':False})['c']
    sections = groups(result['blocks'], layout)
    prepared = [(section, content(section, layout, include_empty)) for section in sections]
    out = []
    for section, blocks in prepared:
        if not section['section']:
            out.extend(blocks)
            continue
        has_children = any(child['parent'] is section and child_blocks for child, child_blocks in prepared)
        if section_dividers and (blocks or has_children or include_empty):
            heading = deepcopy(section['heading'])
            heading['c'][0] = 2
            heading['c'][1][1].append('ff-section')
            out.append(heading)
        # Section introductions remain visible even with divider slides disabled.
        if has_content(section['blocks']):
            if section_dividers and blocks:
                blocks[0]['c'][1][0] += '-introduction'
            out.extend(blocks)
    result['blocks'] = out
    return result
