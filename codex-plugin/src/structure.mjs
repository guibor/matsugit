import {parser} from '@lezer/markdown';

export function headingKey(label) {
  return label.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

export function structure(source, org = false) {
  const headings = [], literals = [], markers = [], blocks = [];
  const counts = new Map();
  const add = (from, to, level, label) => {
    const key = headingKey(label), identity = `${level}:${key}`;
    const occurrence = counts.get(identity) || 0;
    counts.set(identity, occurrence + 1);
    headings.push({from, to, level, label, key, occurrence});
    markers.push({from, role: ['Section', 'Slide', 'Claim', 'Region'][level - 1] || 'Heading'});
  };
  if (org) {
    let offset = 0, opaque;
    for (const line of source.split('\n')) {
      if (/^\s*#\+end_/i.test(line)) opaque = false;
      else if (/^\s*#\+begin_(src|example|export|comment|agent-comment)\b/i.test(line)) opaque = true;
      else if (!opaque) {
        const match = /^(\*+)\s+(.+)$/.exec(line);
        if (match) add(offset, offset + line.length, match[1].length,
          match[2].replace(/\[\[[^\]]+\]\[([^\]]+)\]\]/g, '$1'));
      }
      offset += line.length + 1;
    }
    return {headings, markers, blocks, literals};
  }
  const frontmatter = /^---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/.exec(source)?.[0].length || 0;
  if (frontmatter) literals.push({from: 0, to: frontmatter});
  const tree = parser.parse(source);
  tree.iterate({enter(node) {
    if (['FencedCode', 'CodeBlock', 'HTMLBlock'].includes(node.name)) {
      literals.push({from: node.from, to: node.to}); return false;
    }
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
    add(node.from, node.to, Number(match[1]), label);
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
        blocks.push({...block, to: offset + line.length});
        markers.push({from: offset, role: block.role, closing: true});
      }
    }
    offset += line.length + 1;
  }
  // Hidden review requests must not become preview navigation targets.
  const visible = headings.filter(h => !blocks.some(b => b.role === 'agent-comment' && h.from > b.from && h.from < b.to));
  counts.clear();
  for (const heading of visible) {
    const identity = `${heading.level}:${heading.key}`;
    heading.occurrence = counts.get(identity) || 0;
    counts.set(identity, heading.occurrence + 1);
  }
  return {headings: visible, markers: markers.sort((a, b) => a.from - b.from), blocks, literals};
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
