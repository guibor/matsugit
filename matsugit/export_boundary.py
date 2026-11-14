"""Export projection only. Authored source and Git history remain untouched."""

from html.parser import HTMLParser

MARKER = '<!-- matsugit:export-end -->'


def boundary_index(ast):
    for index, block in enumerate(ast.get('blocks', [])):
        if (block.get('t') == 'RawBlock' and block.get('c', [None])[0] == 'html'
                and block['c'][1].strip() == MARKER):
            return index
    return None


def exported(ast):
    """Only a standalone top-level comment is a boundary, never a code example."""
    index = boundary_index(ast)
    return ast if index is None else dict(ast, blocks=ast['blocks'][:index])


def references(ast):
    """Asset/link inventory for CI: parsed nodes, never searches inside examples."""
    urls = set()

    class Resources(HTMLParser):
        def handle_starttag(self, tag, attrs):
            urls.update(value for key, value in attrs if key in ('src', 'href', 'poster') and value)
        handle_startendtag = handle_starttag

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            kind = node.get('t')
            if kind in ('Image', 'Link'):
                urls.add(node['c'][-1][0])
            elif kind in ('RawBlock', 'RawInline') and node['c'][0] == 'html':
                Resources().feed(node['c'][1])
            elif kind == 'Div' and 'canvas' in node['c'][0][1]:
                value = dict(node['c'][0][2]).get('src')
                if value:
                    urls.add(value)
            for value in node.values():
                visit(value)
    visit(ast)
    return urls
