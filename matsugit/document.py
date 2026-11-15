"""Reading projection of the authored AST; never rewrites the source document."""
from copy import deepcopy

if __package__:
    from .layout import plain, opening_heading, matches_title
    from .source import visible_notes
else:
    from layout import plain, opening_heading, matches_title
    from source import visible_notes


def document(ast):
    result = deepcopy(visible_notes(ast))
    blocks = result['blocks']
    # An authored title identical to the metadata title is not a second section.
    # Keep its anchor so existing links remain usable.
    opening = opening_heading(blocks)
    structured = plain(result.get('meta', {}).get('slide-layout')) == 'structured'
    out, in_slide, claim_position = [], False, False
    for index, block in enumerate(blocks):
        if block.get('t') == 'Header':
            level, attrs, content = block['c']
            if level <= 2:
                in_slide = level == 2
                claim_position = in_slide
            elif structured and level == 3 and claim_position:
                # Retain the exact inlines and heading anchor, but not a TOC entry.
                attrs[1].append('ff-document-claim')
                block = {'t': 'Div', 'c': [attrs, [{'t': 'Para', 'c': content}]]}
                claim_position = False
            if index == opening and matches_title(block, result.get('meta', {})):
                block = {'t': 'Div', 'c': [attrs, []]}
        elif structured and block.get('t') == 'HorizontalRule' and in_slide:
            # Manual slide breaks need no repeated heading in the reading view.
            claim_position = True
            continue
        else:
            claim_position = False
        out.append(block)
    result['blocks'] = out
    return result
