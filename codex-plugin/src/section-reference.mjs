import {structure} from './structure.mjs';

// H2s are both document sections and slide destinations. Do not offer
// working material after export-end or headings inside a component.
export function destinations(source, parsed = structure(source)) {
  return parsed.headings.filter(h => h.level === 2 && h.topLevel &&
    /^ {0,3}##\s/.test(source.slice(h.from, h.to)) &&
    h.from < (parsed.exportEnd?.from ?? Infinity) &&
    ![...parsed.blocks,...parsed.unfinished].some(b => b.from < h.from && h.from < b.to));
}

export function sectionReference(source, at, headingFrom, label) {
  const parsed = structure(source), targets = destinations(source, parsed);
  const h = targets.find(h => h.from === headingFrom);
  if (!h) throw Error('Choose an exported section heading.');
  if (parsed.literals.some(r => r.from <= at && at < r.to) ||
      parsed.headings.some(r => r.from <= at && at <= r.to))
    throw Error('Place the cursor in body text for the reference.');
  const line = source.slice(h.from, h.to), attrs = /\s+\{([^{}]*)\}\s*$/.exec(line);
  const existing = /(?:^|\s)#([^\s}]+)/.exec(attrs?.[1] || '')?.[1];
  const end = h.to - (/\s+#+\s*$|\s+$/.exec(line)?.[0].length || 0);
  const base = 'detail-' + (h.key.replaceAll(' ', '-') || 'section');
  let id = existing || base;
  if (!existing) {
    const ids = new Set(Array.from(source.matchAll(/#([\p{L}\p{N}_.:-]+)/gu), m => m[1]));
    for (let n = 2; ids.has(id); n++) id = base + '-' + n;
  } else if (!/^[\p{L}\p{N}_:.\-]+$/u.test(id) ||
      targets.some(other => other !== h && source.slice(other.from, other.to).split(/[\s{}]+/).includes('#'+id))) {
    throw Error('Give the destination a unique, simple heading ID first.');
  }
  const refs = [...source.matchAll(/\[\\\[(\d+)\\\]\]\(#([^\s)]+)\)/g)]
    .filter(m => !parsed.literals.some(r => r.from <= m.index && m.index < r.to));
  const previous = refs.find(m => m[2] === id);
  const number = previous ? previous[1] : 1 + refs.reduce((max,m) => Math.max(max, Number(m[1])),0);
  if (label !== undefined && (!label || /[\n\[\]\\]/.test(label) || !source.startsWith(label,at)))
    throw Error('Select the link text again.');
  const mark = label === undefined ? `[\\[${number}\\]](#${id})` : `[${label}](#${id})`;
  const changes = [{from:at, to:at+(label?.length || 0), insert:mark}];
  if (!existing) changes.push(attrs ? {from:h.from + attrs.index + attrs[0].indexOf('{') + 1, insert:'#'+id+' '}
    : {from:end, insert:' {#'+id+'}'});
  return {changes:changes.sort((a,b)=>a.from-b.from), end:at + mark.length +
    changes.filter(c => c.from < at).reduce((n,c)=>n+c.insert.length,0)};
}
