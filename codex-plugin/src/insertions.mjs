// Pure source transformations shared by completion, menus and focused tests.
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
