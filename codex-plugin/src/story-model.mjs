import {structure} from './structure.mjs';

// Positions, not heading text, identify nodes. Duplicate titles are ordinary.
export function storyModel(source, org = false) {
  const parsed = structure(source, org);
  const blocks = [...parsed.blocks, ...parsed.unfinished];
  const outside = item => !blocks.some(b => item.from > b.from && item.from < b.to);
  const headings = parsed.headings.filter(h => h.topLevel && h.level <= 3 && outside(h));
  const nodes = [], roots = [], stack = [];
  for (const heading of headings) {
    while (stack.length && stack.at(-1).level >= heading.level) stack.pop().end = heading.from;
    const parent = stack.at(-1) || null;
    const node = {...heading, end:source.length, parent, children:[],
      kind:['section', 'slide', 'claim'][heading.level - 1]};
    (parent ? parent.children : roots).push(node);
    nodes.push(node); stack.push(node);
  }
  let slide = 0;
  for (const node of nodes) {
    if (node.kind === 'slide') node.number = ++slide;
    node.continuations = parsed.breaks.filter(b => b.from > node.from && b.from < node.end && outside(b)).length;
    const claims = parsed.blocks.filter(b => b.role === 'claim' && b.from > node.from && b.to <= node.end
      && !blocks.some(outer => outer !== b && b.from > outer.from && b.to <= outer.to));
    node.hasBlockClaim = claims.length > 0;
    if (node.kind === 'slide') {
      node.claims = [...node.children.filter(c => c.kind === 'claim'), ...claims.map(b => ({
        ...b, kind:'claim', block:true, parent:node, end:b.to, children:[],
        label:source.slice(b.startEnd, b.endFrom).trim(),
      }))].sort((a,b) => a.from-b.from);
      let body = source.slice(node.to, node.end);
      for (const claim of [...node.claims].reverse())
        body = body.slice(0,claim.from-node.to) + body.slice(claim.to-node.to);
      node.empty = !body.trim();
    }
  }
  return {nodes, roots, sections:nodes.filter(n => n.kind === 'section'),
    slides:nodes.filter(n => n.kind === 'slide'), unfinished:parsed.unfinished};
}

export function titleRange(source, node, org = false) {
  if (node.block) {
    const raw = source.slice(node.startEnd,node.endFrom), value = raw.trim();
    if (!value || /[\r\n]/.test(value)) throw Error('Edit this multiline claim block in source view.');
    const from = node.startEnd + raw.indexOf(value);
    return {from,to:from+value.length,text:value};
  }
  const raw = source.slice(node.from, node.to);
  const prefix = (org ? /^(\*+[ \t]+)(?:(?:TODO|DONE|NEXT|WAITING|CANCELLED)[ \t]+)?(?:\[#[A-Z0-9]\][ \t]+)?/
    : /^ {0,3}#{1,6}[ \t]+/).exec(raw)?.[0] || '';
  let body = raw.slice(prefix.length), suffix = '';
  if (!org && !prefix) {
    const setext = /\r?\n[ \t]*[=-]+[ \t]*\r?$/.exec(body);
    if (!setext) throw Error('This heading must be edited in source view.');
    suffix = setext[0]; body = body.slice(0, -suffix.length);
  } else {
    const tail = (org ? /(?:[ \t]+:[\w@#%:]+:)?[ \t]*\r?$/
      : /(?:[ \t]+#+)?[ \t]*\r?$/).exec(body)?.[0] || '';
    suffix = tail; body = body.slice(0, body.length - tail.length);
  }
  if (!org) {
    const attrs = /[ \t]+\{[^{}\r\n]*\}[ \t]*$/.exec(body)?.[0] || '';
    suffix = attrs + suffix; body = body.slice(0, body.length - attrs.length);
  }
  if (/[\r\n]/.test(body)) throw Error('This multiline heading must be edited in source view.');
  return {from:node.from + prefix.length, to:node.to - suffix.length, text:body};
}

function join(left, right, eol) {
  if (!left || !right) return left + right;
  const trailing = left.match(/(?:\r?\n)*$/)[0];
  const count = (trailing.match(/\n/g) || []).length;
  return left + eol.repeat(Math.max(0, 2 - count)) + right;
}

// Return one bounded editor change; the caller uses the existing undo/save path.
export function moveStory(source, from, target, placement = 'before', org = false) {
  const model = storyModel(source, org), node = model.nodes.find(n => n.from === from);
  const other = model.nodes.find(n => n.from === target);
  if (!node || !other || node.kind === 'claim') throw Error('Select a section or slide to move.');
  if (!['before', 'after', 'inside'].includes(placement)) throw Error('Unknown move position.');
  if (placement === 'inside' ? node.kind !== 'slide' || other.kind !== 'section' : node.kind !== other.kind)
    throw Error('Move sections beside sections, or slides beside slides / into sections.');
  const destination = placement === 'before' ? other.from : other.end;
  if (destination >= node.from && destination <= node.end) return null;
  // An unclosed block could swallow a new sibling. Refuse structural moves only.
  if (model.unfinished.length) throw Error('Close the unfinished Markdown/Org block before moving slides.');
  const eol = source.includes('\r\n') ? '\r\n' : '\n';
  const chunk = source.slice(node.from, node.end);
  let start, end, insert, anchor;
  if (destination < node.from) {
    start = destination; end = node.end;
    insert = join(chunk, source.slice(destination, node.from), eol);
    anchor = start;
  } else {
    start = node.from; end = destination;
    const between = source.slice(node.end, destination);
    insert = join(between, chunk, eol);
    anchor = start + insert.length - chunk.length;
  }
  if (end < source.length) insert = join(insert, source.slice(end), eol).slice(0, -source.slice(end).length);
  const result = source.slice(0,start) + insert + source.slice(end);
  const identities = m => m.nodes.map(n => `${n.level}:${n.label}`).sort();
  if (JSON.stringify(identities(model)) !== JSON.stringify(identities(storyModel(result,org))))
    throw Error('This move changes how Markdown/Org blocks are parsed. Close any unfinished block and retry in source view.');
  return {changes:{from:start, to:end, insert}, anchor};
}

export function adjacentMove(source, from, direction, org = false) {
  const model = storyModel(source, org), node = model.nodes.find(n => n.from === from);
  if (!node) return null;
  const siblings = (node.parent?.children || model.roots).filter(n => n.kind === node.kind);
  const next = siblings[siblings.indexOf(node) + direction];
  return next ? moveStory(source, from, next.from, direction < 0 ? 'before' : 'after', org) : null;
}

export function insertStory(source, position, kind, org = false, fields = {}) {
  if (!['section','slide'].includes(kind)) throw Error('Unknown story item.');
  const model = storyModel(source,org);
  if (model.unfinished.length) throw Error('Close the unfinished block before inserting a story item.');
  let node = model.nodes.findLast(n => n.from <= position);
  while (node && node.level > (kind === 'section' ? 1 : 2)) node = node.parent;
  const at = node?.end ?? source.length, eol = source.includes('\r\n') ? '\r\n' : '\n';
  const heading = (org ? '*' : '#').repeat(kind === 'section' ? 1 : 2);
  const title = fields.title ?? (kind === 'section' ? 'New section' : 'New slide');
  const claim = fields.claim ?? '';
  if (!title.trim() || /[\r\n\u0000]/.test(title+claim)) throw Error('Use a nonempty title and single-line title / claim.');
  const content = heading + ' ' + title.trim() + eol + eol
    + (kind === 'slide' && claim.trim() ? (org ? '*** ' : '### ') + claim.trim() + eol + eol : '');
  const prefix = join(source.slice(0,at),content,eol).slice(at);
  return {changes:{from:at,insert:prefix},anchor:at+prefix.length-content.length};
}

export function insertClaim(source, node, org = false) {
  const eol = source.includes('\r\n') ? '\r\n' : '\n';
  const lineEnd = source.indexOf('\n', node.to);
  let at = lineEnd < 0 ? source.length : lineEnd + 1;
  if (org) {
    // Org planning / property lines belong to the slide, not the new subtitle.
    const metadata = /^(?:(?:SCHEDULED|DEADLINE|CLOSED):[^\n]*\n)*(?:[ \t]*:PROPERTIES:[ \t]*\r?\n[\s\S]*?\r?\n[ \t]*:END:[ \t]*(?:\r?\n|$))?/i.exec(source.slice(at))?.[0] || '';
    at += metadata.length;
  }
  const prefix = (at === source.length && !source.endsWith('\n') ? eol : '') + eol;
  return {changes:{from:at,insert:prefix + (org ? '*** ' : '### ') + 'Main claim' + eol + eol},anchor:at+prefix.length};
}
