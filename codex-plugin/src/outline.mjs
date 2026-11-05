import {foldEffect, unfoldEffect, foldedRanges} from '@codemirror/language';
import {EditorView, keymap} from '@codemirror/view';
import {Prec} from '@codemirror/state';
import {completionStatus, hasNextSnippetField, hasPrevSnippetField} from '@codemirror/autocomplete';
import {structure} from './structure.mjs';

const outlines = new WeakMap();
function headings(state, org) {
  let cached = outlines.get(state.doc);
  if (!cached || cached.org !== org) {
    cached = {org, headings: structure(state.doc.toString(), org).headings};
    outlines.set(state.doc, cached);
  }
  return cached.headings;
}
function folds(state) {
  const ranges = [];
  foldedRanges(state).between(0, state.doc.length, (from, to) => ranges.push({from, to}));
  return ranges;
}
function sectionRange(items, index, length) {
  const heading = items[index];
  const next = items.slice(index + 1).find(h => h.level <= heading.level);
  return {from: heading.to, to: next ? Math.max(heading.to, next.from - 1) : length};
}

export function outlineRanges(source, depth, org = false) {
  if (!Number.isInteger(depth) || depth < 0 || depth > 9) throw Error('Invalid outline depth');
  if (!depth) return [];
  const headings = structure(source, org).headings.filter(h => h.level <= depth);
  return headings.map((heading, i) => ({from: heading.to,
    to: i + 1 < headings.length ? Math.max(heading.to, headings[i + 1].from - 1) : source.length}))
    .filter(range => range.to > range.from);
}

export function setOutlineDepth(view, depth, org = false) {
  const effects = [];
  foldedRanges(view.state).between(0, view.state.doc.length,
    (from, to) => effects.push(unfoldEffect.of({from, to})));
  const ranges = outlineRanges(view.state.doc.toString(), depth, org);
  effects.push(...ranges.map(range => foldEffect.of(range)));
  const head = view.state.selection.main.head;
  const containing = ranges.find(range => head > range.from && head <= range.to);
  // Keep the caret on a visible heading rather than editing hidden prose.
  view.dispatch({effects, ...(containing ? {selection: {anchor: containing.from}} : {})});
}

export function cycleSection(view, org = false, headingOnly = false) {
  const selection = view.state.selection.main;
  if (!selection.empty || view.state.selection.ranges.length !== 1) return false;
  const items = headings(view.state, org);
  const index = items.findLastIndex(h => h.from <= selection.head);
  if (index < 0) return false;
  const heading = items[index];
  if (headingOnly && selection.head > heading.to) return false;
  const range = sectionRange(items, index, view.state.doc.length);
  if (range.to <= range.from) return false;
  const existing = folds(view.state).filter(r => r.from >= range.from && r.to <= range.to);
  const closed = existing.some(r => r.from === range.from && r.to === range.to);
  const effects = existing.map(r => unfoldEffect.of(r));
  if (closed) {
    // Reveal immediate children, leaving their bodies and descendants folded.
    let i = index + 1;
    const children = [];
    while (i < items.length && items[i].from < range.to) {
      const child = sectionRange(items, i, view.state.doc.length);
      children.push(child);
      do { i++; } while (i < items.length && items[i].from < child.to);
    }
    if (children.length) {
      const body = {from: heading.to, to: items[index + 1].from - 1};
      effects.push(...[body, ...children].filter(r => r.to > r.from).map(r => foldEffect.of(r)));
    }
  } else if (!existing.length) effects.push(foldEffect.of(range));
  view.dispatch({effects, selection: {anchor: Math.min(selection.head, heading.to)}, scrollIntoView: true});
  return true;
}

export function cycleOutline(view, org = false) {
  const source = view.state.doc.toString(), items = headings(view.state, org);
  if (!items.length) return false;
  const current = folds(view.state);
  const same = ranges => ranges.length === current.length && ranges.every((r, i) => r.from === current[i].from && r.to === current[i].to);
  const top = Math.min(...items.map(h => h.level)), deepest = Math.max(...items.map(h => h.level));
  const depth = same(outlineRanges(source, deepest, org)) ? 0
    : same(outlineRanges(source, top, org)) ? deepest : top;
  setOutlineDepth(view, depth, org);
  return true;
}

export function moveHeading(view, direction, org = false, parent = false) {
  const items = headings(view.state, org), position = view.state.selection.main.head;
  const hidden = folds(view.state);
  const visible = items.filter(h => !hidden.some(r => h.from > r.from && h.from <= r.to));
  const current = items.findLast(h => h.from <= position);
  const target = parent ? visible.findLast(h => h.from < (current?.from ?? 0) && h.level < current.level)
    : direction > 0 ? visible.find(h => h.from > position) : visible.findLast(h => h.from < position);
  if (target) view.dispatch({selection: {anchor: target.from}, effects: EditorView.scrollIntoView(target.from, {y: 'nearest'})});
  return !!items.length;
}

export function outlineKeys(isOrg) {
  const freeTab = state => !completionStatus(state) && !hasNextSnippetField(state) && !hasPrevSnippetField(state);
  return Prec.high(keymap.of([
    {key: 'Tab', run: view => freeTab(view.state) && cycleSection(view, isOrg(), true)},
    // Outside headings Shift-Tab keeps list/table indentation and snippet behavior.
    {key: 'Shift-Tab', run: view => freeTab(view.state) && view.state.selection.main.empty
      && headings(view.state, isOrg()).some(h => view.state.selection.main.head >= h.from && view.state.selection.main.head <= h.to)
      && cycleOutline(view, isOrg())},
    {key: 'Mod-Enter', run: view => cycleSection(view, isOrg())},
    {key: 'Alt-j', run: view => moveHeading(view, 1, isOrg())},
    {key: 'Alt-k', run: view => moveHeading(view, -1, isOrg())},
    {key: 'Alt-h', run: view => moveHeading(view, -1, isOrg(), true)},
  ]));
}
