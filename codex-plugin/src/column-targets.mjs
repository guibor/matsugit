// Use the same authored divisions as the renderer, never a search for bullet text.
export function columnGroups(parsed) {
  const groups = [];
  for (const block of parsed.blocks) {
    if (!['columns','comparison'].includes(block.role)) continue;
    const inside = b => b.from > block.from && b.to <= block.endFrom;
    const children = parsed.blocks.filter(inside);
    if (children.some(b => ['columns','comparison'].includes(b.role))) continue;
    const headings = parsed.headings.filter(h => h.level === 4 && inside(h));
    const explicit = children.filter(b => b.role === 'column');
    const parts = explicit.length ? explicit.map(b => ({from:b.startEnd+1, end:b.endFrom,
      key:headings.find(h => h.from >= b.startEnd+1 && h.to <= b.endFrom)?.key || ''})) :
      headings.filter(h => !children.some(b => b.from < h.from && h.to <= b.to))
        .map((h,i,hs) => ({from:h.from, end:hs[i+1]?.from ?? block.endFrom, key:h.key}));
    if ([2,3].includes(parts.length)) groups.push({from:block.from, kind:block.role, parts});
  }
  return groups;
}

export function columnCaret(doc, parsed, request) {
  const headings = parsed.headings.filter(h => h.topLevel && h.level === 2);
  const slide = headings.filter(h => h.key === request.slide)[request.occurrence];
  if (!slide || !Array.isArray(request.keys) || !Number.isInteger(request.index)) return null;
  const end = headings.find(h => h.from > slide.from)?.from ?? doc.length;
  const matches = columnGroups(parsed).filter(g => g.from > slide.from && g.from < end &&
    g.kind === request.kind && g.parts.length === request.keys.length &&
    g.parts.every((p,i) => p.key === request.keys[i]));
  const part = matches.length === 1 && matches[0].parts[request.index];
  if (!part) return null;
  for (let n=doc.lineAt(part.end-1).number; n>=doc.lineAt(part.from).number; n--) {
    const line=doc.line(n);
    if (!line.text.trim()) continue;
    // Don't put typing inside a closing fence, table, heading attribute or code.
    if (/^\s*(?:[:#|`~]|<!--)/.test(line.text) ||
        parsed.literals.some(b => line.from >= b.from && line.from < b.to)) return null;
    return line.to;
  }
  return null;
}
