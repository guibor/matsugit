import {Annotation} from '@codemirror/state';
import {structure} from './structure.mjs';

export const layoutControl = Annotation.define();

// Protect the paired container, not its prose. Whole-container removal remains
// possible, while a selection ending halfway through a boundary cannot break it.
export function layoutEditAllowed(source, changes) {
  const parsed = structure(source);
  const touches = (change, from, to) => change.from === change.to
    ? change.from >= from && change.from <= to
    : change.from < to && change.to > from;
  for (const block of parsed.blocks.filter(b => b.endFrom !== undefined)) {
    const whole = changes.some(c => c.from <= block.from && c.to >= block.to);
    if (whole) continue;
    for (const change of changes) {
      if (touches(change, block.from, block.startEnd) || touches(change, block.endFrom, block.to)) return false;
      // Joining a boundary to its neighbour also destroys its block meaning.
      if (change.from < change.to && [block.from - 1, block.startEnd, block.endFrom - 1, block.to]
        .some(p => p >= change.from && p < change.to && source[p] === '\n')) return false;
    }
  }
  for (const heading of parsed.headings.filter(h => h.level === 4 && parsed.blocks.some(b => b.from < h.from && b.to > h.to))) {
    const prefix = /^####[ \t]+/.exec(source.slice(heading.from, heading.to));
    if (prefix && changes.some(c => touches(c, heading.from, heading.from + prefix[0].length - 1)
      && !parsed.blocks.some(b => b.from < heading.from && b.to > heading.to && c.from <= b.from && c.to >= b.to))) return false;
  }
  let next = source;
  const ordered = [...changes].sort((a,b) => a.from-b.from);
  for (const c of [...ordered].reverse()) next = next.slice(0,c.from) + c.insert + next.slice(c.to);
  const result = structure(next);
  const mapped = pos => pos + ordered.filter(c => c.to <= pos).reduce((delta,c) => delta+c.insert.length-(c.to-c.from),0);
  return result.unfinished.length <= parsed.unfinished.length && parsed.blocks.filter(b => b.endFrom !== undefined)
    .every(b => ordered.some(c => c.from <= b.from && c.to >= b.to)
      || result.blocks.some(n => n.role === b.role && n.from === mapped(b.from) && n.endFrom === mapped(b.endFrom)));
}

export function slideSpacing(source, position, compact) {
  const parsed = structure(source);
  const heading = parsed.headings.filter(h => h.level === 2 && h.topLevel && h.from <= position
    && !parsed.blocks.some(b => b.from < h.from && b.to > h.to)).at(-1);
  if (!heading) return null;
  const line = source.slice(heading.from, heading.to);
  if (!/^##\s/.test(line) || line.includes('\n')) return null;
  const attrs = /\s+\{([^{}]*)\}\s*$/.exec(line);
  const tokens = attrs ? attrs[1].match(/(?:[^\s"']|"[^"]*"|'[^']*')+/g) || [] : [];
  const active = tokens.includes('.tight');
  if (compact === undefined) return {active, from:heading.from};
  const rest = tokens.filter(t => t !== '.tight');
  if (compact) rest.push('.tight');
  const title = attrs ? line.slice(0,attrs.index) : line;
  return {from:heading.from, to:heading.to, insert:title + (rest.length ? ' {' + rest.join(' ') + '}' : '')};
}
