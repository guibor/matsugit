// Plain-language slide checks. Pure text in, findings out: no rendering, no
// file access, no model call. The renderer stays the authority; this explains
// the common mistakes early, names the slide and line, and offers a safe fix.
import {structure, frontmatterLength} from './structure.mjs';

// Part limits mirror matsugit/layout.py (columns, rows) and components.LIMITS.
const LIMITS = {columns: [2, 3], rows: [2, 3], metrics: [1, 4], comparison: [2, 3],
  timeline: [2, 6], decision: [2, 4], implication: [2, 2]};
const ITEM = {columns: 'column', rows: 'row', implication: 'column'};
const CHART_TYPES = ['bar', 'barh', 'line', 'scatter', 'stacked', 'stacked100'];
const KNOWN = ['takeaway', 'source', 'notes', 'columns', 'column', 'rows', 'row', 'metrics',
  'comparison', 'timeline', 'decision', 'assertion', 'claim', 'chart', 'implication', 'mapping',
  'annotated', 'evidence', 'callout', 'canvas', 'agent-comment', 'compact', 'data-table',
  'quotation', 'attribution'];
// Ordinary Quarto/Reveal classes are never "typos" of ours.
const FOREIGN = new Set(['incremental', 'nonincremental', 'fragment', 'aside', 'footer', 'center',
  'smaller', 'scrollable', 'absolute', 'panel-tabset', 'content-visible', 'content-hidden',
  'sources', 'comment', 'block', 'note', 'tip', 'warning', 'important', 'caution']);
const BOOLEANS = ['slide-section-dividers', 'slide-empty-slides', 'slide-title-page',
  'publish-sources', 'include-notes'];
const FENCE = /^ {0,3}(:{3,})[ \t]*(.*?)[ \t]*$/;
const title = role => role[0].toUpperCase() + role.slice(1).replaceAll('-', ' ');

function distance(a, b) {
  const row = Array.from({length: b.length + 1}, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let previous = row[0]; row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const current = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (a[i - 1] === b[j - 1] ? 0 : 1));
      previous = current;
    }
  }
  return row[b.length];
}

function orgCheck(source) {
  const parsed = structure(source, true), findings = [];
  const line = from => source.slice(0, from).split('\n').length;
  for (const block of parsed.unfinished.slice(0, 1)) findings.push({code: 'block-open', severity: 'problem',
    slide: null, title: '', from: block.from, line: line(block.from),
    message: `The ${title(block.role)} block that starts on line ${line(block.from)} is never closed.`,
    how: `Add a line with \`#+end_${block.role}\` where the block should end.`});
  return findings;
}

export function checkDeck(source, org = false) {
  if (org) return orgCheck(source);
  const parsed = structure(source, false);
  const lines = [];
  let offset = 0;
  for (const raw of source.split('\n')) {
    lines.push({from: offset, to: offset + raw.length, text: raw.replace(/\r$/, ''), index: lines.length});
    offset += raw.length + 1;
  }
  let pointer = 0;
  for (const line of lines) {
    while (pointer < parsed.literals.length && parsed.literals[pointer].to <= line.from) pointer++;
    const literal = parsed.literals[pointer];
    line.literal = !!literal && line.from >= literal.from && line.from < literal.to;
  }
  const blank = line => !line.text.trim();
  // A block opener or break needs to start its own block: Pandoc reads a line
  // directly under paragraph, list or quote text as more of that text.
  const glued = index => {
    const previous = lines[index - 1];
    return !!previous && !blank(previous) && !previous.literal && !FENCE.test(previous.text)
      && !/^ {0,3}#{1,6}(\s|$)/.test(previous.text) && !/^\s*\|/.test(previous.text)
      && !/^ {0,3}([-*_])( *\1){2,} *$/.test(previous.text);
  };

  // Fenced blocks, using Pandoc's rule: a bare colon line closes the innermost block.
  const blocks = [], stack = [], strays = [];
  for (const line of lines) {
    if (line.literal) continue;
    const fence = FENCE.exec(line.text);
    if (!fence) continue;
    const label = fence[2].replace(/[ \t]*:{3,}$/, '');
    if (label) {
      const role = /(?:^|[.{\s])([a-z][a-z-]*)\b/.exec(label)?.[1] || 'block';
      const attrs = Object.fromEntries([...label.matchAll(/([\w-]+)=(?:"([^"]*)"|'([^']*)'|(\S+?))(?=[\s}]|$)/g)]
        .map(match => [match[1], match[2] ?? match[3] ?? match[4]]));
      const block = {role, label, attrs, width: fence[1].length, from: line.from, open: line.index,
        close: null, to: source.length, parent: stack.at(-1) || null, glued: glued(line.index)};
      block.opaque = role === 'agent-comment' || !!block.parent?.opaque;
      blocks.push(block); stack.push(block);
    } else if (stack.length) {
      const block = stack.pop(); block.close = line.index; block.to = line.to;
    } else strays.push(line);
  }
  const enclosing = from => blocks.findLast(block => from > block.from && from < block.to) || null;

  const settings = {};
  const settingsEnd = frontmatterLength(source);
  for (const line of lines) {
    if (line.from >= settingsEnd) break;
    const match = /^([A-Za-z][\w-]*):[ \t]*(.*?)[ \t]*$/.exec(line.text);
    if (match) settings[match[1]] = {line, raw: match[2], value: match[2].replace(/\s+#.*$/, '').replace(/^(['"])(.*)\1$/, '$2')};
  }
  const layout = settings['slide-layout']?.value || '';
  const structured = layout === 'structured', arranged = structured || layout === 'title-claim';

  const tops = parsed.headings.filter(heading => heading.topLevel && heading.level <= 2 && !enclosing(heading.from)?.opaque);
  let number = 0;
  for (const heading of tops) if (heading.level === 2) heading.number = ++number;
  const where = from => {
    const heading = tops.findLast(item => item.from <= from);
    return heading?.level === 2 ? {slide: heading.number, title: heading.label}
      : {slide: null, title: heading ? heading.label : ''};
  };
  const findings = [];
  const add = (code, severity, from, message, how, fix) => findings.push({code, severity, ...where(from), from,
    line: source.slice(0, from).split('\n').length, message, how, ...(fix ? {fix} : {})});
  const lineOf = from => lines.findLast(line => line.from <= from);
  const fenceText = block => ':'.repeat(block.width);

  // --- Settings at the top -------------------------------------------------
  const first = lines.find(line => !blank(line));
  if (!settingsEnd && first && /^﻿?---[ \t]*$/.test(first.text) && /^[A-Za-z][\w-]*:/.test(lines[first.index + 1]?.text || ''))
    add('settings-open', 'problem', first.from, 'The settings block at the top starts with `---` but never ends, so the settings are read as slide text.',
      'Add a line with just `---` after the last setting.');
  for (const key of BOOLEANS) {
    const setting = settings[key];
    if (setting && /^['"]/.test(setting.raw)) add('setting-quoted', 'problem', setting.line.from,
      `The setting \`${key}\` must be true or false without quotation marks.`, `Write \`${key}: ${setting.value}\`.`,
      /^(true|false)$/.test(setting.value) ? {label: 'Remove quotes', changes: [{from: setting.line.from, to: setting.line.to, insert: `${key}: ${setting.value}`}]} : undefined);
  }
  if (settings['slide-layout'] && !['default', 'structured', 'title-claim'].includes(layout))
    add('setting-layout', 'problem', settings['slide-layout'].line.from, `\`slide-layout: ${layout}\` is not a layout matsugit knows.`,
      'Use `slide-layout: structured`.', {label: 'Use structured', changes: [{from: settings['slide-layout'].line.from, to: settings['slide-layout'].line.to, insert: 'slide-layout: structured'}]});
  if (settings['slide-aspect-ratio'] && !['16:9', '4:3'].includes(settings['slide-aspect-ratio'].value))
    add('setting-ratio', 'problem', settings['slide-aspect-ratio'].line.from, 'The slide shape must be "16:9" or "4:3".', 'Write `slide-aspect-ratio: "16:9"`.');

  // --- Blocks that do not open or close as intended ------------------------
  for (const line of strays) add('block-stray', 'problem', line.from,
    'This `' + line.text.trim() + '` line does not close anything, so the colons will show up as text.',
    'Remove the line, or add the opening line it belongs to.',
    {label: 'Remove line', changes: [{from: line.from, to: Math.min(source.length, line.to + 1), insert: ''}]});
  for (const block of blocks) {
    if (block.opaque) continue;
    if (block.glued) add('block-glued', 'problem', block.from,
      `\`${lines[block.open].text.trim()}\` needs an empty line above it. Right now it is read as ordinary text, so the colons show up on the slide.`,
      'Add an empty line before it.', {label: 'Add empty line', changes: [{from: block.from, to: block.from, insert: '\n'}]});
    if (!KNOWN.includes(block.role) && !FOREIGN.has(block.role) && !block.role.startsWith('callout-')) {
      const guess = KNOWN.map(name => [distance(block.role, name), name]).sort((a, b) => a[0] - b[0])[0];
      if (guess[0] <= (block.role.length <= 5 ? 1 : 2)) {
        const at = block.from + lines[block.open].text.indexOf(block.role);
        add('block-name', 'tip', block.from, `\`${block.role}\` is not a block matsugit knows. Did you mean \`${guess[1]}\`?`,
          `Change it to \`${guess[1]}\` if that is what you meant.`,
          {label: `Change to ${guess[1]}`, changes: [{from: at, to: at + block.role.length, insert: guess[1]}]});
      }
    }
  }
  const open = blocks.find(block => block.close === null && !block.glued && !block.opaque);
  if (open) {
    const next = tops.find(heading => heading.from > open.from);
    const at = next ? next.from : source.length;
    const swallowed = next?.level === 2 ? `, including slide ${next.number} ("${next.label}")` : '';
    add('block-open', 'problem', open.from,
      `The ${title(open.role)} block that starts on line ${open.open + 1} is never closed, so everything after it${swallowed} is treated as part of it.`,
      `Add a line with just \`${fenceText(open)}\` where the block should end.`,
      {label: 'Close the block', changes: [{from: at, to: at, insert: next ? fenceText(open) + '\n\n'
        : (source.endsWith('\n') || !source ? '' : '\n') + fenceText(open) + '\n'}]});
  }
  for (const line of lines) {
    if (line.literal || enclosing(line.from)?.opaque) continue;
    if (/^ {0,3}>[ \t]*\[!TAKEAWAY\]/.test(line.text) && glued(line.index) && !/^ {0,3}>/.test(lines[line.index - 1].text))
      add('block-glued', 'problem', line.from, 'This takeaway needs an empty line above it. Right now it is read as ordinary text.',
        'Add an empty line before it.', {label: 'Add empty line', changes: [{from: line.from, to: line.from, insert: '\n'}]});
    const heading = /^( {0,3}#{2,4})([^\s#].*)$/.exec(line.text);
    if (heading) add('heading-space', 'problem', line.from, `\`${heading[1].trim()}\` needs a space after it to become a heading.`,
      `Write \`${heading[1].trim()} ${heading[2].slice(0, 30)}\`.`,
      {label: 'Add space', changes: [{from: line.from + heading[1].length, to: line.from + heading[1].length, insert: ' '}]});
    const previous = lines[line.index - 1];
    if (/^ {0,3}-{3,}[ \t]*$/.test(line.text) && previous && !blank(previous) && !previous.literal
        && !/^ {0,3}(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||:{3,})/.test(previous.text))
      add('break-glued', 'problem', line.from, 'This `---` sits directly under a line of text, so that line becomes a heading instead of the slide continuing on a new page.',
        'Add an empty line before `---`.', {label: 'Add empty line', changes: [{from: line.from, to: line.from, insert: '\n'}]});
  }

  // --- Layout blocks: number of parts and their content --------------------
  const usable = block => block.close !== null && !block.glued && !block.opaque;
  let needsLayout = null;
  for (const block of blocks) {
    if (!usable(block) || !LIMITS[block.role]) continue;
    const items = [];
    for (let index = block.open + 1; index < block.close; index++) {
      const line = lines[index], inner = blocks.find(child => child.parent === block && child.open === index);
      if (inner) {
        items.push({kind: inner.role === ITEM[block.role] ? 'item' : 'other', from: line.from});
        index = inner.close ?? block.close;
      } else if (!blank(line)) items.push({kind: !line.literal && /^ {0,3}####(\s|$)/.test(line.text) ? 'h4' : 'other', from: line.from});
    }
    const explicit = items.length > 0 && items.every(item => item.kind === 'item');
    if ((block.role === 'rows' || block.role === 'columns' && !explicit) && !arranged) needsLayout ||= block;
    if (['columns', 'rows'].includes(block.role) && !arranged) continue;
    const name = title(block.role), [low, high] = LIMITS[block.role];
    const range = low === high ? `exactly ${low}` : high - low === 1 ? `${low} or ${high}` : `${low} to ${high}`;
    let parts;
    if (explicit) parts = items.length;
    else if (items.some(item => item.kind === 'item') && items.some(item => item.kind === 'h4')) {
      add('parts-mixed', 'problem', block.from, `This ${name} block mixes \`####\` headings with separate \`${ITEM[block.role]}\` blocks.`,
        `Use one style: either a \`####\` heading to start each part, or one \`${ITEM[block.role]}\` block per part.`);
      continue;
    } else if (items.length && items[0].kind !== 'h4') {
      add('parts-start', 'problem', items[0].from, `Each part of a ${name} block must start with a \`####\` heading. This content comes before the first one.`,
        'Add a line such as `#### First part` above it, or move the content into a part.',
        {label: 'Add heading', changes: [{from: items[0].from, to: items[0].from, insert: '#### Part title\n\n'}]});
      continue;
    } else {
      const heads = items.filter(item => item.kind === 'h4');
      parts = heads.length;
      for (const head of heads) {
        const following = items[items.indexOf(head) + 1];
        if (!following || following.kind === 'h4') add('parts-empty', 'problem', head.from,
          `This part of the ${name} block has a heading but no content.`, 'Write something under the heading, or remove the heading.');
      }
    }
    if (parts < low || parts > high) add('parts-count', 'problem', block.from,
      `This ${name} block has ${parts} ${parts === 1 ? 'part' : 'parts'}. ${name} works with ${range}.`,
      parts > high ? 'Merge parts, or move some to a second slide with a `---` line.'
        : `Add ${parts ? 'another' : 'a'} part: a \`####\` heading with content under it.`);
  }
  if (needsLayout) {
    const key = settings['slide-layout'];
    const settingsClose = lines.findLast(line => line.from < settingsEnd && /^(---|\.\.\.)[ \t]*$/.test(line.text));
    add('layout-off', 'problem', needsLayout.from,
      `This deck uses ${title(needsLayout.role)}, but the slide layout is not switched on, so the parts will not be arranged.`,
      'Add `slide-layout: structured` to the settings at the top of the file.',
      key ? undefined : {label: 'Switch on layout', changes: [settingsEnd
        ? {from: settingsClose.from, to: settingsClose.from, insert: 'slide-layout: structured\n'}
        : {from: 0, to: 0, insert: '---\nslide-layout: structured\n---\n\n'}]});
  }

  // --- Charts --------------------------------------------------------------
  for (const block of blocks) {
    if (!usable(block) || block.role !== 'chart') continue;
    const body = lines.slice(block.open + 1, block.close);
    if (!body.some(line => /^\s*\|/.test(line.text))) add('chart-table', 'problem', block.from,
      'This chart has no table inside it. A chart is drawn from one table.', 'Put a table with a header row between the opening and closing lines.');
    else if (!block.attrs.unit) add('chart-unit', 'problem', block.from, 'This chart does not say what its numbers measure.',
      'Add the unit to the first line, for example `unit="days"`.');
    if (block.attrs.type && !CHART_TYPES.includes(block.attrs.type)) add('chart-type', 'problem', block.from,
      `\`${block.attrs.type}\` is not a chart type. Choose one of: ${CHART_TYPES.join(', ')}.`, 'Change `type=` in the first line of the chart.');
  }

  // --- Titles, claims and takeaways ----------------------------------------
  const callouts = parsed.blocks.filter(block => block.syntax === 'callout');
  const breaks = parsed.breaks.filter(item => !enclosing(item.from));
  const scopes = tops.map((heading, index) => ({heading, from: heading.to, to: tops[index + 1]?.from ?? source.length}));
  for (const heading of parsed.headings) {
    const inside = enclosing(heading.from);
    if (!inside || inside.opaque || inside.close === null || heading.level > 3) continue;
    if (heading.level === 3 && structured) add('heading-inside', 'problem', heading.from,
      `Headings inside a ${title(inside.role)} block must use \`####\`.`, 'Change `###` to `####`.',
      {label: 'Make it ####', changes: [{from: heading.from, to: heading.from + 3, insert: '####'}]});
    else if (heading.level <= 2 && arranged) add('heading-inside', 'problem', heading.from,
      `This ${heading.level === 2 ? 'slide title' : 'section title'} sits inside the ${title(inside.role)} block that starts on line ${inside.open + 1}.`,
      `Move the closing \`${fenceText(inside)}\` line above this title.`);
  }
  for (const scope of scopes) {
    const bounds = [scope.from, ...breaks.filter(item => item.from > scope.from && item.from < scope.to).flatMap(item => [item.from, item.to]), scope.to];
    for (let part = 0; part < bounds.length; part += 2) {
      const from = bounds[part], to = bounds[part + 1];
      if (structured) {
        const claims = [...parsed.headings.filter(heading => heading.level === 3 && heading.from >= from && heading.from < to && !enclosing(heading.from)),
          ...blocks.filter(block => block.role === 'claim' && usable(block) && !block.parent && block.from >= from && block.from < to)]
          .sort((a, b) => a.from - b.from);
        claims.forEach((claim, index) => {
          const heading = 'level' in claim;
          if (scope.heading.level === 1) {
            if (heading) add('claim-untitled', 'problem', claim.from, 'This claim has no slide title above it.', 'Add a `## Slide title` line above the claim.');
            return;
          }
          // Heading offsets start at #, after any valid Markdown indentation.
          const claimLine = lineOf(claim.from).from;
          const content = lines.some(line => line.from >= from && line.from < claimLine && !blank(line)
            && !claims.some(other => line.from >= other.from && line.from < (other.to ?? other.from + 1))
            && !enclosing(line.from)?.opaque && !blocks.some(block => block.opaque && block.open === line.index)
            && !(line.literal && /^\s*<!--/.test(line.text)));
          if (!index && !content) return;
          add('claim-extra', 'problem', claim.from, index
            ? 'A slide has one claim, directly under its title. This is a second one.'
            : 'The claim must come directly under the slide title, before any other content.',
            heading ? 'Use `####` for a heading inside the slide, or start a new slide with `##`.' : 'Keep one claim for this slide.',
            heading ? {label: 'Make it ####', changes: [{from: claim.from, to: claim.from + 3, insert: '####'}]} : undefined);
        });
      }
      if (arranged) {
        const takeaways = [...blocks.filter(block => block.role === 'takeaway' && usable(block) && !block.parent),
          ...callouts.filter(block => !enclosing(block.from))].filter(block => block.from >= from && block.from < to)
          .sort((a, b) => a.from - b.from);
        for (const extra of takeaways.slice(1)) add('takeaway-extra', 'problem', extra.from,
          'A slide has one takeaway. This is a second one.', 'Keep one, or put a `---` line before this one to continue on another slide.');
      }
    }
  }

  // --- Tips: the deck works, these make it better --------------------------
  const hidden = line => { const block = enclosing(line.from); return !!block && (block.opaque || block.role === 'notes'); };
  const keepEmpty = settings['slide-empty-slides']?.value === 'true';
  for (const scope of scopes) {
    if (scope.heading.level !== 2) continue;
    const body = lines.filter(line => line.from >= scope.from && line.from < scope.to && !blank(line)
      && !enclosing(line.from)?.opaque && !blocks.some(block => block.opaque && (block.open === line.index || block.close === line.index)));
    if (arranged && !keepEmpty && !body.length) add('slide-empty', 'tip', scope.heading.from,
      'This slide has only a title, so it is left out of the slides for now.',
      'Add a claim or content. To keep title-only slides, add `slide-empty-slides: true` to the settings at the top.');
    if (scope.heading.label.length > 95) add('title-long', 'tip', scope.heading.from,
      `This title is ${scope.heading.label.length} characters long and may not fit.`, 'Shorten it and move the detail into the claim under it.');
    const words = body.filter(line => !line.literal && !FENCE.test(line.text) && !hidden(line) && !/^\s*\|[\s|:-]*$/.test(line.text))
      .flatMap(line => line.text.split(/\s+/)).filter(word => /[\p{L}\p{N}]/u.test(word)).length;
    if (words > 150) add('slide-dense', 'tip', scope.heading.from, `This slide has about ${words} words, which is a lot to read on one slide.`,
      'Split it with a `---` line, shorten the text, or move detail into presenter notes.');
    for (let index = 0; index < body.length; index++) {
      if (body[index].literal || !/^\s*\|/.test(body[index].text)) continue;
      let end = index;
      while (body[end + 1] && body[end + 1].index === body[end].index + 1 && /^\s*\|/.test(body[end + 1].text)) end++;
      const rows = end - index - 1, columns = body[index].text.trim().replace(/^\||\|$/g, '').split('|').length;
      if (rows > 10 || columns > 6) add('table-dense', 'tip', body[index].from,
        `This table has ${rows} rows and ${columns} columns, which may be hard to read on a slide.`, 'Show fewer rows or columns, or split the table over two slides.');
      index = end;
    }
  }
  return findings.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'problem' ? -1 : 1) || a.from - b.from);
}

// Apply one finding's fix to text; the editor applies the same changes itself.
export function applyFix(source, fix) {
  let result = source;
  for (const change of [...fix.changes].sort((a, b) => b.from - a.from))
    result = result.slice(0, change.from) + change.insert + result.slice(change.to);
  return result;
}

export function checkSummary(findings) {
  const problems = findings.filter(item => item.severity === 'problem').length, tips = findings.length - problems;
  return {problems, tips, label: problems ? `${problems} to fix` : tips ? `${tips} ${tips === 1 ? 'tip' : 'tips'}` : 'No problems'};
}

// The renderer speaks in Markdown terms. Say the common cases in slide words.
const RENDERER = [
  [/Use H4 for content divisions/, 'A heading inside a slide body or layout block must use `####`. This also happens when a block above is missing its closing `:::` line.'],
  [/Use two or three (columns|rows)/, 'A Columns or Rows block works with 2 or 3 parts.'],
  [/need H4 headings or explicit/, 'Each part of a Columns or Rows block must start with a `####` heading.'],
  [/Each (column|row) needs content/, 'One part of a Columns or Rows block has a heading but no content.'],
  [/Put one H3 subtitle directly after H2/, 'A slide has one claim (`###`) directly under its title. Use `####` for other headings.'],
  [/An H3 subtitle needs an H2/, 'A claim (`###`) needs a slide title (`##`) above it.'],
  [/Use one takeaway per slide/, 'A slide has one takeaway. Put a `---` line between two takeaways to continue on another slide.'],
  [/Use one claim per slide/, 'A slide has one claim.'],
  [/Give the chart an explicit unit/, 'A chart must say what its numbers measure, for example `unit="days"`.'],
  [/must be true or false/, 'A setting at the top must be true or false, without quotation marks.'],
  [/setup-charts/, 'Charts need a one-time setup on this computer: run `matsugit setup-charts`.'],
  [/setup-diagrams/, 'D2 diagrams need a one-time setup on this computer: run `matsugit setup-diagrams`.'],
];
export function rendererFinding(message) {
  const text = String(message || 'Preview failed.').trim();
  const known = RENDERER.find(([pattern]) => pattern.test(text));
  return {code: 'renderer', severity: 'problem', slide: null, title: '', from: null, line: null,
    message: known ? known[1] : text, how: known ? `Renderer message: ${text.slice(0, 300)}` : ''};
}
