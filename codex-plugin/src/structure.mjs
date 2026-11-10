import {parser} from '@lezer/markdown';

export function headingKey(label) {
  return label.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

// Length of the leading YAML settings block, or 0 when there is none.
export function frontmatterLength(source) {
  return /^\uFEFF?(?:[ \t]*\r?\n)*---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/.exec(source)?.[0].length || 0;
}

export function structure(source, org = false) {
  const headings = [], literals = [], markers = [], blocks = [], breaks = [];
  const counts = new Map();
  const add = (from, to, level, label, topLevel = true) => {
    const key = headingKey(label), identity = `${level}:${key}`;
    const occurrence = counts.get(identity) || 0;
    counts.set(identity, occurrence + 1);
    headings.push({from, to, level, label, key, occurrence, topLevel});
    markers.push({from, role: ['Section', 'Slide', 'Claim', 'Region'][level - 1] || 'Heading'});
  };
  if (org) {
    let offset = 0;
    const stack = [], opaqueNames = new Set(['src', 'example', 'export', 'comment', 'agent-comment']);
    for (const line of source.split('\n')) {
      const begin = /^\s*#\+begin_([\w-]+)\b/i.exec(line);
      const end = /^\s*#\+end_([\w-]+)\s*$/i.exec(line);
      const active = stack.at(-1);
      if (end && active?.role === end[1].toLowerCase()) {
        const block = stack.pop();
        blocks.push({...block, endFrom: offset, to: offset + line.length});
        if (block.opaque) literals.push({from: block.from, to: offset + line.length});
        markers.push({from: offset, role: block.role, closing: true});
      } else if (!active?.opaque && begin) {
        const role = begin[1].toLowerCase();
        stack.push({from: offset, startEnd: offset + line.length, role, opaque: opaqueNames.has(role)});
        markers.push({from: offset, role});
      } else if (!active?.opaque) {
        const match = /^(\*+)[ \t]+(.+?)\r?$/.exec(line);
        if (match) add(offset, offset + line.length, match[1].length,
          match[2].replace(/\[\[[^\]]+\]\[([^\]]+)\]\]/g, '$1'), !stack.length);
        if (!stack.length && /^\s*-{5,}\s*$/.test(line)) breaks.push({from: offset, to: offset + line.length});
      }
      offset += line.length + 1;
    }
    for (const block of stack) if (block.opaque) literals.push({from: block.from, to: source.length});
    return {headings, markers, blocks, breaks, unfinished: stack.map(b => ({...b, to:source.length})), literals: literals.sort((a,b)=>a.from-b.from)};
  }
  const frontmatter = frontmatterLength(source);
  if (frontmatter) literals.push({from: 0, to: frontmatter});
  const tree = parser.parse(source);
  tree.iterate({enter(node) {
    if (node.name !== 'Document' && node.from < frontmatter) return false;
    // Lezer distinguishes HTML comments from HTML blocks. Fence examples in a
    // comment must not open a semantic block extending through the whole deck.
    if (['FencedCode', 'CodeBlock', 'HTMLBlock', 'CommentBlock'].includes(node.name)) {
      literals.push({from: node.from, to: node.to}); return false;
    }
    if (node.name === 'HorizontalRule' && node.from >= frontmatter && node.node.parent?.name === 'Document')
      breaks.push({from: node.from, to: node.to});
    const match = /^(?:ATX|Setext)Heading([1-6])$/.exec(node.name);
    if (!match || node.from < frontmatter) return;
    const omit = [];
    node.node.toTree().iterate({enter(child) {
      if (['HeaderMark', 'EmphasisMark', 'LinkMark', 'URL', 'LinkTitle', 'CodeMark', 'HTMLTag'].includes(child.name)) {
        omit.push([node.from + child.from, node.from + child.to]); return false;
      }
    }});
    let label = '', cursor = node.from;
    for (const [from, to] of omit) { label += source.slice(cursor, from); cursor = to; }
    label += source.slice(cursor, node.to);
    label = label.replace(/\s+\{[^{}]*\}\s*$/, '').trim();
    if (typeof document !== 'undefined') {
      const decoder = document.createElement('textarea'); decoder.innerHTML = label; label = decoder.value;
    }
    add(node.from, node.to, Number(match[1]), label, node.node.parent?.name === 'Document');
    return false;
  }});
  let offset = 0, literal = 0;
  const stack = [];
  for (const line of source.split('\n')) {
    while (literal < literals.length && literals[literal].to < offset) literal++;
    const ignored = offset < frontmatter || (literals[literal] && offset >= literals[literal].from && offset < literals[literal].to);
    const fence = !ignored && /^ {0,3}(:{3,})\s*(.*?)\s*$/.exec(line);
    if (fence) {
      if (fence[2]) {
        const role = /(?:^|[.{\s])([a-z][a-z-]*)\b/.exec(fence[2])?.[1] || 'block';
        stack.push({from: offset, startEnd: offset + line.length, width: fence[1].length, role});
        markers.push({from: offset, role});
      } else if (stack.length && fence[1].length >= stack.at(-1).width) {
        const block = stack.pop();
        blocks.push({...block, endFrom: offset, to: offset + line.length});
        markers.push({from: offset, role: block.role, closing: true});
      }
    }
    offset += line.length + 1;
  }
  for (const match of source.matchAll(/^ {0,3}>[ \t]*\[!TAKEAWAY\][ \t]*\r?$/gm)) {
    if (literals.some(range => match.index >= range.from && match.index < range.to)) continue;
    let end = match.index + match[0].length;
    for (const line of source.slice(end + 1).split('\n')) {
      if (!/^ {0,3}>/.test(line)) break;
      end += line.length + 1;
    }
    blocks.push({from:match.index,startEnd:match.index+match[0].length,to:end,role:'takeaway',syntax:'callout'});
    markers.push({from:match.index,role:'takeaway'});
  }
  // Hidden review requests must not become preview navigation targets.
  const visible = headings.filter(h => !blocks.some(b => b.role === 'agent-comment' && h.from > b.from && h.from < b.to));
  counts.clear();
  for (const heading of visible) {
    const identity = `${heading.level}:${heading.key}`;
    heading.occurrence = counts.get(identity) || 0;
    counts.set(identity, heading.occurrence + 1);
  }
  return {headings: visible, markers: markers.sort((a, b) => a.from - b.from), blocks, breaks, literals,
    unfinished: stack.map(b => ({...b, to:source.length}))};
}

// These are source guides, not a prediction of renderer-generated overflow slides.
export function slideBoundaries(parsed) {
  return [...parsed.headings.filter(h => h.level === 2 && h.topLevel), ...parsed.breaks]
    .filter(item => !parsed.blocks.some(b => item.from > b.from && item.from < b.to))
    .sort((a, b) => a.from - b.from).map(item => item.from);
}

export function headingTargets(headings, position) {
  const trail = [];
  for (const heading of headings) {
    if (heading.from > position) break;
    while (trail.length && trail.at(-1).level >= heading.level) trail.pop();
    trail.push(heading);
  }
  const targets = trail.reverse();
  if (targets[0]?.level === 1) {
    const next = headings.find(h => h.from >= position && h.level === 2);
    if (next) targets.push(next);
  }
  return targets.map(({key, level, occurrence}) => ({key, level, occurrence}));
}
