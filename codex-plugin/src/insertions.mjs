// Pure source transformations shared by completion, menus and focused tests.
import {structure} from './structure.mjs';
import {storyModel, titleRange, insertClaim} from './story-model.mjs';
export const chartTypes = ['barh', 'bar', 'line', 'stacked', 'stacked100'];

export function wrapElement(name, selected, org = false) {
  if (name === 'takeaway' || name === 'takeaway-callout') {
    const body = selected || 'Key takeaway.';
    return org ? `#+begin_takeaway\n${body}\n#+end_takeaway\n`
      : '> [!TAKEAWAY]\n' + body.split('\n').map(line => '> ' + line).join('\n') + '\n';
  }
  if (name.startsWith('chart-') && chartTypes.includes(name.slice(6))) {
    const body = selected.trim() || (org
      ? '| Experience | Value |\n|------------+-------|\n| Baseline | 12 |\n| Pilot | 8 |'
      : '| Experience | Value |\n| :--- | ---: |\n| Baseline | 12 |\n| Pilot | 8 |');
    if (!body.split('\n').every(line => /^\s*\|.*\|\s*$/.test(line))) {
      throw Error('Select one pipe table to make a chart. Other content was not changed.');
    }
    const type = name.slice(6);
    return org ? `#+begin_chart :type "${type}" :unit "units"\n${body}\n#+end_chart\n`
      : `::: {.chart type="${type}" unit="units"}\n${body}\n:::\n`;
  }
  return null;
}

export function snippetTemplate(value, placeholders = true) {
  const escaped = value.replace(/[{}]/g, '\\$&');
  if (!placeholders) return escaped;
  let index = 0;
  return escaped.replace(/Slide title|Main claim|Section title|(?:First|Second|Third) column|Supporting (?:point|evidence)\.|What the evidence means\.|Key takeaway\.|Presenter notes\.|\bunits\b/g,
    label => '${' + (++index) + ':' + label + '}') + (index ? '${0}' : '');
}

export function ratioLine(line, ratio, org = false) {
  if (!['1:1', '2:1', '1:2', '1:1:1'].includes(ratio)) throw Error('Unsupported ratio');
  if (org) return line.replace(/\s+:ratio\s+(?:"[^"]*"|\S+)/, '') + ` :ratio "${ratio}"`;
  if (/\{/.test(line)) {
    const clean = line.replace(/\s+ratio=(?:"[^"]*"|\S+)/, '');
    return clean.replace(/\}\s*$/, ` ratio="${ratio}"}`);
  }
  return line.replace(/(columns)(?:\s+[\d.:]+)?\s*$/, `$1 ${ratio}`);
}

// Elements that belong at the foot of a slide wherever the cursor is.
const BOTTOM = new Set(['takeaway', 'takeaway-block', 'notes', 'source', 'agent-comment']);

// Decide where a picked recipe goes, so adding never depends on where the
// cursor happens to be: a slide follows the current slide, a part goes into it.
// Returns one change ({from,to,insert}) and/or a range to select; never saves.
export function placeInsertion(source, position, name, recipe, org = false) {
  const model = storyModel(source, org);
  if (model.unfinished.length) throw Error('A block above is not closed yet. Open Check to close it, then add this.');
  const value = recipe[org ? 'org' : 'markdown'];
  const pad = (from, to = from) => {
    const head = source.slice(0, from), tail = source.slice(to);
    const body = value.replace(/^\n+|\n+$/g, '') + '\n';
    const prefix = !head || head.endsWith('\n\n') ? '' : head.endsWith('\n') ? '\n' : '\n\n';
    const suffix = !tail || tail.startsWith('\n') ? '' : '\n';
    return {from, to, insert: prefix + body + suffix};
  };
  const tops = model.nodes.filter(node => node.kind !== 'claim');
  const current = tops.findLast(node => node.from <= position);
  if (recipe.group === 'slide') {
    return pad(!current ? source.length : current.kind === 'slide' ? current.end
      : current.children.find(node => node.kind === 'slide')?.from ?? current.end);
  }
  const slide = current?.kind === 'slide' ? current
    : model.slides.find(item => item.from >= position) || model.slides.at(-1);
  if (!slide) return pad(source.length);
  const existing = (node, what) => {
    let range;
    try { range = titleRange(source, node, org); } catch { range = {from: node.from, to: node.to}; }
    return {select: {from: range.from, to: range.to}, message: `This slide already has a ${what}. It is selected so you can edit it.`};
  };
  if (name === 'claim') {
    if (slide.claims.length) return existing(slide.claims[0], 'claim');
    // Markdown keeps the claim on the line under its title; Org planning and
    // property lines need the Story helper that steps over them.
    const {changes, anchor} = org ? insertClaim(source, slide, org)
      : {changes: {from: slide.to, insert: '\n### Main claim'}, anchor: slide.to + 1};
    return {from: changes.from, to: changes.from, insert: changes.insert, placeholders: false,
      select: {from: anchor + 4, to: anchor + 4 + 'Main claim'.length}};
  }
  if (name.startsWith('takeaway') && slide.takeaways.length) return existing(slide.takeaways[0], 'takeaway');
  const foot = () => {
    const end = slide.from + source.slice(slide.from, slide.end).replace(/\s+$/, '').length;
    return pad(end, slide.end < source.length ? source.lastIndexOf('\n', slide.end - 1) : slide.end);
  };
  if (BOTTOM.has(name) || current !== slide) return foot();
  const parsed = structure(source, org);
  const container = [...parsed.blocks, ...parsed.literals].filter(item => item.from <= position && position <= item.to)
    .sort((a, b) => a.from - b.from)[0];
  const lineStart = source.lastIndexOf('\n', position - 1) + 1;
  let lineEnd = source.indexOf('\n', position); if (lineEnd < 0) lineEnd = source.length;
  if (container) { const end = source.indexOf('\n', container.to); return pad(end < 0 ? source.length : end + 1); }
  if (!source.slice(lineStart, lineEnd).trim()) return pad(lineStart, lineEnd);
  // Otherwise finish the paragraph (or title and claim) the cursor is in.
  let end = lineEnd;
  while (end < slide.end) {
    const next = source.indexOf('\n', end + 1), stop = next < 0 ? source.length : next;
    if (!source.slice(end + 1, stop).trim()) break;
    end = stop;
  }
  return pad(Math.min(source.length, end + 1));
}
