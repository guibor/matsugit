"""Opt-in evidence components shared by document and slide rendering."""
from copy import deepcopy

if __package__:
    from .layout import classes, div, body_headings, has_content
else:
    from layout import classes, div, body_headings, has_content

LIMITS = {'metrics': (1, 4), 'comparison': (2, 3), 'timeline': (2, 6),
          'decision': (2, 4)}


def prepare(node):
    """Group H4 regions explicitly; never infer a layout from prose."""
    if isinstance(node, list):
        return [prepare(n) for n in node]
    if not isinstance(node, dict):
        return node
    node = deepcopy(node)
    names = set(classes(node))
    found = names.intersection(LIMITS)
    if len(found) > 1:
        raise ValueError('Use one evidence layout per block')
    if found:
        kind = found.pop()
        parts = []
        for block in node['c'][1]:
            if block.get('t') == 'Header' and block['c'][0] == 4:
                parts.append([])
            if not parts:
                raise ValueError(f'{kind}: start each region with an H4 heading')
            parts[-1].append(block)
        low, high = LIMITS[kind]
        if not low <= len(parts) <= high:
            raise ValueError(f'{kind}: use {low} to {high} H4 regions')
        if any(not has_content(part) for part in parts):
            raise ValueError(f'{kind}: each region needs content')
        node['c'][0][1].append('ff-' + kind)
        node['c'][0][2].append(['data-regions', str(len(parts))])
        node['c'][1] = [div(['ff-region'], body_headings(prepare(part))) for part in parts]
        return node
    if 'assertion' in names:
        node['c'][0][1].append('ff-assertion')
    return {key: prepare(value) for key, value in node.items()}
