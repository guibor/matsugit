"""Small authoring aliases; all outputs use the existing Pandoc block model."""
from copy import deepcopy
import re


def ratios(value):
    if not re.fullmatch(r'\d+(?:\.\d+)?(?::\d+(?:\.\d+)?){1,2}', value):
        raise ValueError('Columns need a ratio such as 1:1, 2:1 or 1:1:1')
    numbers = [float(item) for item in value.split(':')]
    if any(not 0 < number <= 1000 for number in numbers):
        raise ValueError('Column ratio values must be greater than zero and at most 1000')
    return numbers


def markdown(text):
    """Expand only standalone ratio openers, never examples or raw HTML.

    This is a lexical alias, not a Markdown parser. Pandoc still owns nesting,
    inline markup and all other syntax. Keep line count and line endings stable.
    """
    lines, result = text.splitlines(keepends=True), []
    code = None
    html_end = None
    frontmatter = bool(lines and lines[0].strip() == '---')
    review = []
    for number, line in enumerate(lines):
        stripped = line.strip()
        if frontmatter:
            result.append(line)
            if number and stripped in ('---', '...'):
                frontmatter = False
            continue
        if html_end:
            result.append(line)
            if html_end.search(line):
                html_end = None
            continue
        fence = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if code:
            result.append(line)
            if fence and fence[1][0] == code[0] and len(fence[1]) >= code[1] and not fence[2].strip():
                code = None
            continue
        if fence:
            code = (fence[1][0], len(fence[1]))
            result.append(line)
            continue
        html = re.match(r'^ {0,3}(<!--|<\?|<!\[CDATA\[|<([A-Za-z][\w:-]*)\b)', line)
        if html:
            end = {'<!--': r'-->', '<?': r'\?>', '<![CDATA[': r'\]\]>'}.get(html[1])
            if not end and html[2].lower() not in ('img', 'br', 'hr', 'input', 'meta', 'link'):
                end = r'</' + re.escape(html[2]) + r'\s*>'
                if html[2].lower() not in ('script', 'style', 'pre', 'textarea'):
                    end += r'|^\s*$'
            if end:
                pattern = re.compile(end, re.I)
                if not pattern.search(line):
                    html_end = pattern
            result.append(line)
            continue
        div = re.match(r'^ {0,3}(:{3,})[ \t]*(.*?)[ \t]*$', line.rstrip('\r\n'))
        if review or (div and re.search(r'\bagent-comment\b', div[2])):
            if div:
                if div[2]:
                    review.append(len(div[1]))
                elif review and len(div[1]) >= review[-1]:
                    review.pop()
            result.append(line)
            continue
        alias = re.fullmatch(r'( {0,3}:{3,})[ \t]+columns[ \t]+([^\s{}]+)[ \t]*(\r?\n)?', line)
        if alias:
            ratios(alias[2])
            line = f'{alias[1]} {{.columns ratio="{alias[2]}"}}' + (alias[3] or '')
        result.append(line)
    return ''.join(result)


def blocks(node):
    """Lower takeaway quotes and column ratios for Markdown, Org and CI alike."""
    if isinstance(node, list):
        return [blocks(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = deepcopy(node)
    if node.get('t') == 'Div' and 'agent-comment' in node['c'][0][1]:
        return node
    if node.get('t') == 'BlockQuote' and node['c']:
        first, *rest = node['c']
        if first['t'] in ('Para', 'Plain'):
            inline = first['c']
            if (inline and inline[0] == {'t': 'Str', 'c': '[!TAKEAWAY]'} and
                    (len(inline) == 1 or inline[1]['t'] in ('SoftBreak', 'LineBreak'))):
                body = ([dict(first, c=inline[2:])] if len(inline) > 2 else []) + rest
                if not body:
                    raise ValueError('A takeaway needs a conclusion after [!TAKEAWAY]')
                node = {'t': 'Div', 'c': [['', ['takeaway'], []], body]}
    if node.get('t') == 'Div' and 'columns' in node['c'][0][1]:
        attrs, children = node['c']
        options = dict(attrs[2])
        if 'ratio' in options:
            if __package__:
                from .layout import divisions
            else:
                from layout import divisions
            numbers = ratios(options['ratio'])
            parts = divisions(node, 'columns', 'column')
            if len(parts) != len(numbers):
                raise ValueError('Column ratio count must match the number of regions')
            if any('width' in dict(part['c'][0][2]) for part in parts):
                raise ValueError('Use a columns ratio or individual widths, not both')
            for part, weight in zip(parts, numbers):
                part['c'][0][2].append(['width', f'{100 * weight / sum(numbers):.6g}%'])
            attrs[2] = [pair for pair in attrs[2] if pair[0] != 'ratio']
            node['c'][1] = parts
    return {key: blocks(value) for key, value in node.items()}
