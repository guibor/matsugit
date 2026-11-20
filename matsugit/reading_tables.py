"""Identify unadorned Markdown pipe tables without guessing from HTML widths."""
import re
from collections import Counter


def auto_tables(ast, text):
    if '|' not in text or 'tbl-colwidths' in text:
        return
    candidates = Counter()
    previous = ''
    fence = ''
    for line in text.splitlines():
        line = line.rstrip()
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            run = marker[1]
            if not fence:
                fence = run
            elif run.startswith(fence) and not line[marker.end():].strip():
                fence = ''
            previous = ''
            continue
        if fence:
            continue
        if previous.startswith('|') and previous.endswith('|'):
            cells = line.strip('|').split('|')
            if cells and all(re.fullmatch(r'\s*:?-{3}:?\s*', c) for c in cells):
                header = tuple(c.strip().strip('`') for c in previous[1:-1].split('|'))
                candidates[header] += 1
        previous = line
    if not candidates:
        return
    tables = []
    for i, block in enumerate(ast['blocks']):
        if block['t'] != 'Table':
            continue
        attrs, _, specs, head, _, _ = block['c']
        if len(head[1]) != 1:
            continue
        def label(cell):
            parts = cell[4]
            if len(parts) != 1 or parts[0]['t'] not in ('Plain', 'Para'):
                return None
            return ''.join(' ' if n['t'] == 'Space' else n['c'][-1] if n['t'] == 'Code'
                           else n['c'] if n['t'] == 'Str' else '\0' for n in parts[0]['c'])
        key = tuple(label(cell) for cell in head[1][0][1])
        tables.append((i, key, attrs, specs))
    counts = Counter(k for _, k, _, _ in tables)
    for i, key, attrs, specs in tables:
        if (candidates[key] == counts[key] == 1 and attrs == ['', [], []]
                and all(s[1] == specs[0][1] for s in specs)):
            ast['blocks'][i] = {'t': 'Div', 'c': [['', ['matsugit-auto-columns'], []], [ast['blocks'][i]]]}
