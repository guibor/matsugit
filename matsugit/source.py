"""Markdown and native Org inputs share the same inert Pandoc document model."""
from copy import deepcopy
import json
import re
import shlex
from uuid import uuid4

try:
    from .layout import metadata, plain
except ImportError:
    from layout import metadata, plain

DISPLAY = {'slide-layout', 'slide-section-dividers', 'slide-empty-slides',
           'slide-aspect-ratio', 'slide-title-page', 'publish-sources', 'include-notes'}
BOOLEAN = DISPLAY - {'slide-layout', 'slide-aspect-ratio'}
OPAQUE = {'src', 'example', 'export', 'comment', 'agent-comment'}


def pandoc(command, text, reader, writer, *flags):
    # Local import keeps this module usable in the copied CI package too.
    try:
        from .core import run
    except ImportError:
        from core import run
    return run([*command, '-f', reader, '-t', writer, *flags], text=text)


def check_org(text):
    """Reject reader data loss and file inclusions before invoking Pandoc."""
    stack, safe = [], []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        begin = re.match(r'^\s*#\+begin_(\S+)', line, re.I)
        end = re.match(r'^\s*#\+end_(\S+)\s*$', line, re.I)
        hidden = stack and stack[-1] == 'agent-comment'
        if not hidden and not (begin and begin[1].lower() == 'agent-comment' and
                               not (stack and stack[-1] in OPAQUE)):
            safe.append(line)
        if stack and stack[-1] in OPAQUE:
            if end and end[1].lower() == stack[-1]:
                stack.pop()
            continue
        if re.match(r'^\s*#\+(?:include|setupfile|bind|call):', line, re.I):
            raise ValueError(f'Org line {number}: includes and executable directives are not supported; use explicit local links')
        if begin:
            stack.append(begin[1].lower())
        elif end:
            if not stack or end[1].lower() != stack.pop():
                raise ValueError(f'Org line {number}: mismatched special block end')
        elif stack and re.match(r'^\*+\s', line):
            raise ValueError(f'Org line {number}: headlines inside blocks are lost by Pandoc; use #+begin_region :title "Heading" instead')
    if stack:
        raise ValueError(f'Org block is not closed: {stack[-1]}')
    return ''.join(safe)


def strip_agent_comments(node):
    """Remove collaboration-only blocks from every derived/published artifact."""
    if isinstance(node, list):
        return [strip_agent_comments(n) for n in node
                if not (isinstance(n, dict) and n.get('t') == 'Div'
                        and 'agent-comment' in n['c'][0][1])]
    if not isinstance(node, dict):
        return node
    return {key: strip_agent_comments(value) for key, value in node.items()}


def visible_sources(ast):
    """Sources are opt-in semantic Divs, not headings, links or code examples."""
    return visible_blocks(ast, 'source', 'publish-sources')


def visible_notes(ast):
    """Presenter notes are opt-in in reading documents, retained in slides."""
    return visible_blocks(ast, 'notes', 'include-notes')


def visible_blocks(ast, role, flag):
    if ast.get('meta', {}).get(flag, {}).get('c') is True:
        return ast
    def visit(node):
        if isinstance(node, list):
            return [visit(item) for item in node
                    if not (isinstance(item, dict) and item.get('t') == 'Div'
                            and role in item['c'][0][1])]
        if isinstance(node, dict):
            return {key: visit(value) for key, value in node.items()}
        return node
    return visit(ast)


def org_block_parameters(text):
    """Carry special-block arguments through older Pandoc Org readers.

    Pandoc 3.6 ignores BEGIN arguments but supports ATTR_HTML on special blocks.
    Opaque IDs avoid re-encoding quoted values into that reader's different syntax.
    """
    key = 'data-matsugit-' + uuid4().hex
    parameters, output, opaque = {}, [], None
    native = OPAQUE | {'quote', 'verse', 'center'}
    for line in text.splitlines(keepends=True):
        begin = re.match(r'^(\s*)#\+begin_([\w-]+)([^\r\n]*)(\r?\n)?$', line, re.I)
        end = re.match(r'^\s*#\+end_([\w-]+)\s*$', line, re.I)
        if opaque:
            if end and end[1].lower() == opaque: opaque = None
        elif begin:
            role = begin[2].lower()
            if role in OPAQUE:
                opaque = role
            elif role not in native and begin[3].strip():
                tokens = shlex.split(begin[3])
                if len(tokens) % 2 or any(not re.fullmatch(r':[\w-]+', token) for token in tokens[::2]):
                    raise ValueError('Org block parameters need :name "value" pairs')
                attrs = {tokens[i][1:]:tokens[i+1] for i in range(0,len(tokens),2)}
                identifier = str(len(parameters)); parameters[identifier] = attrs
                output.append(f'{begin[1]}#+attr_html: :{key} {identifier}\n')
                line = f'{begin[1]}#+begin_{begin[2]}{begin[4] or ""}'
        output.append(line)
    return ''.join(output), key, parameters


def restore_org_parameters(ast, key, parameters):
    remaining = set(parameters)
    def visit(node):
        if isinstance(node, list): return [visit(item) for item in node]
        if not isinstance(node, dict): return node
        if node.get('t') == 'Div':
            attrs = node['c'][0]
            values = dict(attrs[2]); identifier = values.pop(key, None)
            if identifier is not None:
                if identifier not in remaining: raise ValueError('Unexpected Org block parameter marker')
                remaining.remove(identifier); values.update(parameters[identifier])
                attrs[2] = list(map(list, values.items()))
        return {name:visit(value) for name,value in node.items()}
    ast = visit(ast)
    if remaining: raise ValueError('Pandoc did not preserve Org block parameters')
    return ast


def read(text, fmt, command):
    if __package__:
        from .sugar import markdown, blocks as authoring_blocks
    else:
        from sugar import markdown, blocks as authoring_blocks
    if fmt not in ('markdown', 'org'):
        raise ValueError('Source format must be markdown or org')
    if fmt == 'org':
        text = check_org(text)
        text, parameter_key, parameters = org_block_parameters(text)
    else:
        text = markdown(text)
    ast = strip_agent_comments(json.loads(pandoc(command, text, fmt, 'json')))
    if fmt == 'org':
        ast = restore_org_parameters(ast, parameter_key, parameters)
        seen = set()
        blocks = []
        for block in ast['blocks']:
            directive = (re.fullmatch(r'#\+([A-Za-z_-]+):\s*(.*)', block['c'][1], re.I)
                         if block['t'] == 'RawBlock' and block['c'][0] == 'org' else None)
            key = directive[1].lower().replace('_', '-') if directive else None
            if key in DISPLAY:
                if key in seen:
                    raise ValueError(f'Duplicate Org setting: {key}')
                seen.add(key)
                value = directive[2].strip()
                if key in BOOLEAN:
                    if value.lower() not in ('true', 'false'):
                        raise ValueError(f'{key} must be true or false')
                    ast['meta'][key] = {'t': 'MetaBool', 'c': value.lower() == 'true'}
                else:
                    ast['meta'][key] = {'t': 'MetaString', 'c': value}
            else:
                blocks.append(block)
        ast['blocks'] = org_blocks(blocks, command)
    ast = authoring_blocks(ast)
    ast['meta'] = metadata(ast.get('meta', {}))
    return ast


def org_blocks(blocks, command):
    result = []
    for block in blocks:
        block = deepcopy(block)
        kind = block.get('t')
        if kind == 'RawBlock' and block['c'][0] in ('markdown', 'md'):
            inner = read(block['c'][1], 'markdown', command)
            if inner['meta']:
                raise ValueError('Put document settings outside Org export blocks')
            result.extend(inner['blocks'])
            continue
        if kind == 'Div':
            attrs, children = block['c']
            values = dict(attrs[2])
            attrs[0] = values.pop('id', attrs[0])
            attrs[1] = list(dict.fromkeys([*attrs[1], *values.pop('class', '').split()]))
            children = org_blocks(children, command)
            if 'region' in attrs[1] or ({'column', 'row'} & set(attrs[1]) and 'title' in values):
                title = values.pop('title', '').strip()
                if not title:
                    raise ValueError('Org regions need :title "Heading"; use column/row without :title for untitled areas')
                heading = {'t': 'Header', 'c': [4, ['', [], []], [{'t': 'Str', 'c': title}]]}
                if 'region' in attrs[1]:
                    result.extend([heading, *children])
                    continue
                children.insert(0, heading)
            attrs[2] = list(map(list, values.items()))
            block['c'] = [attrs, children]
        elif kind == 'BlockQuote':
            block['c'] = org_blocks(block['c'], command)
        elif kind == 'BulletList':
            block['c'] = [org_blocks(item, command) for item in block['c']]
        elif kind == 'OrderedList':
            block['c'][1] = [org_blocks(item, command) for item in block['c'][1]]
        result.append(block)

    def attributes(node):
        if isinstance(node, list):
            return [attributes(n) for n in node]
        if not isinstance(node, dict):
            return node
        if node.get('t') in ('Image', 'Link', 'Span', 'CodeBlock', 'Table', 'Figure'):
            attrs = node['c'][0]
            values = dict(attrs[2])
            attrs[0] = values.pop('id', attrs[0])
            attrs[1] = list(dict.fromkeys([*attrs[1], *values.pop('class', '').split()]))
            attrs[2] = list(map(list, values.items()))
        if node.get('t') == 'Table':
            # A native target at the start of a cell names its evidence, not a
            # zero-width point whose annotation would collide with the value.
            _, _, _, head, bodies, foot = node['c']
            rows = head[1] + [r for body in bodies for r in body[2] + body[3]] + foot[1]
            for row in rows:
                for cell in row[1]:
                    for block in cell[4]:
                        if block['t'] not in ('Plain', 'Para') or len(block['c']) < 2:
                            continue
                        first, *rest = block['c']
                        if first['t'] == 'Span' and first['c'][0][0] and not first['c'][1]:
                            first['c'][1] = rest
                            block['c'] = [first]
        return {k: attributes(v) for k, v in node.items()}
    return attributes(result)


def write_org(ast, command):
    """Use Pandoc for inline syntax and tables, with lossless semantic wrappers."""
    ast = deepcopy(ast)
    settings = metadata(ast.get('meta', {}))
    directives = []
    for key in DISPLAY:
        if key in settings:
            value = settings.pop(key)
            text = str(value['c']).lower() if value['t'] == 'MetaBool' else plain(value)
            directives.append(f'#+{key.upper().replace("-", "_")}: {text}')
    ast['meta'] = settings

    def targets(node):
        if isinstance(node, list):
            return [targets(n) for n in node]
        if not isinstance(node, dict):
            return node
        if node.get('t') == 'Span' and node['c'][0][0]:
            identifier = node['c'][0][0]
            if re.search(r'[<>\r\n]', identifier):
                raise ValueError('Invalid Org evidence target')
            node['c'][0][0] = ''
            node['c'][1].insert(0, {'t': 'RawInline', 'c': ['org', f'<<{identifier}>>']})
        return {key: targets(value) for key, value in node.items()}
    def raw(text):
        return {'t': 'RawBlock', 'c': ['org', text]}

    def has_linebreak(node):
        if isinstance(node, list):
            return any(has_linebreak(n) for n in node)
        if isinstance(node, dict):
            return node.get('t') == 'LineBreak' or any(has_linebreak(v) for v in node.values())
        return False

    def blocks(items, nested=False):
        result = []
        index = 0
        while index < len(items):
            node = deepcopy(items[index])
            index += 1
            if node.get('t') == 'Div':
                attrs, children = node['c']
                identifier, names, values = attrs
                if not names:
                    names = ['div']
                options = dict(values)
                if identifier:
                    options['id'] = identifier
                if len(names) > 1:
                    options['class'] = ' '.join(names[1:])
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', names[0]):
                    raise ValueError('Invalid Org block name')
                if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', key) for key in options):
                    raise ValueError('Invalid Org block attribute')
                args = ''.join(f' :{k} {json.dumps(v, ensure_ascii=False)}' for k, v in options.items())
                result.extend([raw(f'#+begin_{names[0]}{args}'), *blocks(children, True), raw(f'#+end_{names[0]}')])
            elif node.get('t') == 'Header' and nested:
                if node['c'][0] != 4:
                    raise ValueError('Only H4 region headings are supported inside slide components')
                content = []
                while index < len(items) and items[index].get('t') != 'Header':
                    content.append(items[index])
                    index += 1
                title = json.dumps(plain(node['c'][2]), ensure_ascii=False)
                result.extend([raw(f'#+begin_region :title {title}'), *blocks(content, True), raw('#+end_region')])
            elif node.get('t') == 'Table':
                # Native Org cannot encode spans or rich multiline cells. Preserve
                # those as readable grid source, not flattened cells or HTML.
                _, _, _, head, bodies, foot = node['c']
                rows = head[1] + [r for body in bodies for r in body[2] + body[3]] + foot[1]
                cells = [c for r in rows for c in r[1]]
                rich = any(c[2:4] != [1, 1] or len(c[4]) > 1 or has_linebreak(c[4]) or
                           any(b['t'] not in ('Plain', 'Para') for b in c[4]) for c in cells)
                if rich:
                    grid = pandoc(command, json.dumps(dict(ast, meta={}, blocks=[node])), 'json',
                                  'markdown-pipe_tables-simple_tables-multiline_tables', '--wrap=auto')
                    result.append(raw('#+begin_export markdown\n' + grid.rstrip() + '\n#+end_export'))
                else:
                    native = pandoc(command, json.dumps(dict(ast, meta={}, blocks=[targets(node)])),
                                    'json', 'org', '--wrap=none')
                    alignment = {'AlignLeft': '<l>', 'AlignCenter': '<c>', 'AlignRight': '<r>',
                                 'AlignDefault': ''}
                    cookies = [alignment[col[0]['t']] for col in node['c'][2]]
                    if any(cookies):
                        row = '| ' + ' | '.join(cookies) + ' |\n'
                        native = re.sub(r'(?m)^(?=\|)', lambda _: row, native, count=1)
                    result.append(raw(native.rstrip()))
            elif node.get('t') == 'RawBlock' and node['c'][0] in ('markdown', 'md'):
                result.append(raw('#+begin_export markdown\n' + node['c'][1].rstrip() + '\n#+end_export'))
            else:
                result.append(node)
        return result

    ast['blocks'] = ([raw('\n'.join(sorted(directives)))] if directives else []) + blocks(ast['blocks'])
    return pandoc(command, json.dumps(targets(ast)), 'json', 'org', '--standalone', '--wrap=none')


def convert(text, reader, writer, command):
    ast = read(text, reader, command)
    if writer == 'org':
        return write_org(ast, command)
    if writer != 'markdown':
        raise ValueError('Output format must be markdown or org')
    return pandoc(command, json.dumps(ast), 'json', 'markdown', '--standalone', '--wrap=none')
