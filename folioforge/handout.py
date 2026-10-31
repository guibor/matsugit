"""Slide-ordered HTML handout, with presenter notes made explicit."""
from copy import deepcopy


def prepare(ast):
    result = deepcopy(ast)
    pages, current = [], []
    for block in result['blocks']:
        if block.get('t') == 'Header' and block['c'][0] == 2 and current:
            pages.append(current)
            current = []
        current.append(block)
    if current:
        pages.append(current)

    def notes(node):
        if isinstance(node, list):
            return [notes(n) for n in node]
        if not isinstance(node, dict):
            return node
        if node.get('t') == 'Div' and 'notes' in node['c'][0][1]:
            node['c'][0][1] = ['ff-speaker-notes']
            node['c'][1].insert(0, {'t':'Para', 'c':[{'t':'Strong','c':[{'t':'Str','c':'Presenter notes'}]}]})
        return {k: notes(v) for k, v in node.items()}
    result['blocks'] = [{'t':'Div', 'c':[['',['ff-handout-slide'],[]],notes(page)]} for page in pages]
    return result
