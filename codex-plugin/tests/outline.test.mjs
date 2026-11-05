import test from 'node:test';
import assert from 'node:assert/strict';
import {EditorState} from '@codemirror/state';
import {codeFolding, foldedRanges} from '@codemirror/language';
import {outlineRanges, setOutlineDepth, cycleSection, cycleOutline, moveHeading} from '../src/outline.mjs';

function viewFor(doc, anchor = 0) {
  return {state: EditorState.create({doc, selection: {anchor}, extensions: [codeFolding()]}),
    dispatch(spec) { this.state = this.state.update(spec).state; }};
}
function ranges(view) {
  const out = [];
  foldedRanges(view.state).between(0, view.state.doc.length, (from, to) => out.push({from, to}));
  return out;
}

const source = '# Section\nbody\n## Slide\nbody\n### Claim\nbody\n## Another\nbody\n';
test('intermediate depth folds bodies and deeper headings, not source', () => {
  const ranges = outlineRanges(source, 2);
  assert.equal(ranges.length, 3);
  assert.ok(ranges.some(r => source.slice(r.from, r.to).includes('### Claim')));
  assert.ok(!ranges.some(r => source.slice(r.from, r.to).includes('## Another')));
  assert.equal(outlineRanges(source, 3).length, 4);
  assert.deepEqual(outlineRanges(source, 0), []);
});

test('heading cycles folded, immediate children, fully expanded without edits', () => {
  const view = viewFor(source);
  assert.equal(cycleSection(view, false, true), true);
  assert.equal(ranges(view).length, 1);
  assert.equal(ranges(view)[0].to, source.length);
  cycleSection(view, false, true);
  assert.equal(ranges(view).length, 3);
  assert.ok(ranges(view).some(r => source.slice(r.from, r.to).includes('### Claim')));
  cycleSection(view, false, true);
  assert.deepEqual(ranges(view), []);
  assert.equal(view.state.doc.toString(), source);
});
test('body Tab is not consumed; explicit section cycling works from the body', () => {
  const view = viewFor(source, source.indexOf('body') + 2);
  assert.equal(cycleSection(view, false, true), false);
  assert.equal(cycleSection(view), true);
  assert.equal(view.state.selection.main.head, '# Section'.length);
  assert.equal(ranges(view).length, 1);
});
test('leaf cycle leaves siblings alone and global cycle uses actual first level', () => {
  const text = '## One\nbody\n### Child\nbody\n## Two\nbody';
  const view = viewFor(text, text.indexOf('###'));
  cycleSection(view);
  assert.equal(ranges(view)[0].to, text.indexOf('## Two') - 1);
  cycleSection(view);
  assert.deepEqual(ranges(view), []);
  cycleOutline(view);
  assert.equal(ranges(view).length, 2);
  cycleOutline(view);
  assert.equal(ranges(view).length, 3);
  cycleOutline(view);
  assert.equal(ranges(view).length, 0);
});
test('navigation respects folds, parent and Org and never edits source', () => {
  for (const [doc, org] of [[source, false], [source.replaceAll('#', '*'), true]]) {
    const view = viewFor(doc);
    setOutlineDepth(view, 2, org);
    moveHeading(view, 1, org);
    const first = view.state.selection.main.head;
    moveHeading(view, 1, org);
    assert.equal(view.state.selection.main.head, doc.indexOf(org ? '** Another' : '## Another'));
    moveHeading(view, -1, org);
    assert.equal(view.state.selection.main.head, first);
    moveHeading(view, -1, org, true);
    assert.equal(view.state.selection.main.head, 0);
    assert.equal(view.state.doc.toString(), doc);
  }
});
test('ignore code and frontmatter headings, support setext and Org', () => {
  const text = '---\ntitle: Test\n---\n\nTitle\n=====\n\n```md\n# not a heading\n```\n\n## Real\ntext';
  assert.equal(outlineRanges(text, 2).length, 2);
  assert.equal(outlineRanges('* One\ntext\n** Two\ntext\n*** Three\ntext', 2, true).length, 2);
});
test('fold and restore leave text unchanged and keep caret visible', () => {
  const view = {state: EditorState.create({doc: source, selection: {anchor: source.indexOf('###') + 3}, extensions: [codeFolding()]}),
    dispatch(spec) { this.state = this.state.update(spec).state; }};
  setOutlineDepth(view, 2);
  assert.equal(foldedRanges(view.state).size, 3);
  assert.equal(view.state.selection.main.head, source.indexOf('## Slide') + '## Slide'.length);
  assert.equal(view.state.doc.toString(), source);
  setOutlineDepth(view, 0);
  assert.equal(foldedRanges(view.state).size, 0);
  assert.equal(view.state.doc.toString(), source);
});
