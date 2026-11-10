import {test} from 'node:test';
import assert from 'node:assert/strict';
import {textChanges, savedEditHistory, planExternalEdit} from '../src/external-edits.mjs';
import {mergePlan} from '../src/merge.mjs';

const apply = (text, changes) => [...changes].sort((a, b) => b.from - a.from)
  .reduce((value, change) => value.slice(0, change.from) + change.insert + value.slice(change.to), text);

test('a new text becomes small changes that leave untouched lines alone', () => {
  const before = 'title\n\none\ntwo\nthree\n\nend';
  for (const after of ['title\n\none\ntwo\nthree\n\nend', 'TITLE\n\none\ntwo\nthree\n\nend', 'title\n\none\nthree\n\nend\nmore\n',
    'new first\ntitle\n\none\nTWO\nthree\n\nend', '', 'title\r\n\r\none\r\n', 'title\n\none\ntwo\nthree\n\nend\n']) {
    const changes = textChanges(before, after);
    assert.equal(apply(before, changes), after, JSON.stringify(after));
  }
  // Two separate edits stay two hunks, so a cursor between them does not move.
  const changes = textChanges(before, 'TITLE\n\none\ntwo\nthree\n\nEND');
  assert.deepEqual(changes.map(change => [change.from, change.to, change.insert]), [[0, 6, 'TITLE\n'], [before.length - 3, before.length, 'END']]);
  assert.deepEqual(textChanges('', 'a\n'), [{from: 0, to: 0, insert: 'a\n'}]);
});

const decide = (base, local, incoming, history = savedEditHistory()) =>
  planExternalEdit({base, local, incoming, history, merge: async (...args) => mergePlan(...args)});

test('same-line edit after autosave requires review, including equal-distance versions', async () => {
  const history = savedEditHistory(); history.remember('Budget: 10\n');
  const result = await decide('Budget: 20\n', 'Budget: 20\n', 'Budget: 30\n', history);
  assert.equal(result.review, true);
  assert.equal(result.ambiguous, true);
  assert.equal(result.plan.conflicts, 1);
  assert.equal(result.plan.segments[0].local, 'Budget: 20\n');
});

test('disjoint edits combine only when all observed bases agree', async () => {
  const original = 'intro\n\none\n\ntwo\n';
  const current = original + '\nAuthor paragraph\n';
  const history = savedEditHistory(); history.remember(original);
  const incoming = current.replace('intro', 'Agent intro');
  const result = await decide(current, current, incoming, history);
  assert.equal(result.review, false);
  assert.equal(result.text, incoming);
  assert.deepEqual(history.versions, [original], 'accepting an external update must not discard saved history');
  history.rebase(result.versions);
  assert.deepEqual(history.versions, [original.replace('intro', 'Agent intro')]);
  const stale = original.replace('two', 'Agent second edit');
  const next = await decide(incoming, incoming, stale, history);
  assert.equal(next.review, true);
});

test('targeted edits stay independent while an author extends an already saved sentence', async () => {
  const original = 'intro\n\none\n\ntwo\n';
  const base = original + '\nAuthor paragraph';
  const local = base + ', still typing';
  const history = savedEditHistory(); history.remember(original);
  const incoming = base.replace('intro', 'Agent intro');
  const result = await decide(base, local, incoming, history);
  assert.equal(result.review, false);
  assert.equal(result.text, incoming + ', still typing');
  history.rebase(result.versions);
  const next = await decide(incoming, result.text, incoming.replace('Agent intro', 'Agent revised intro'), history);
  assert.equal(next.review, false);
  assert.equal(next.text, local.replace('intro', 'Agent revised intro'));
});

test('stale rewrite and intentional deletion are indistinguishable and both require review', async () => {
  const original = 'intro\n\none\n\ntwo\n';
  const current = original + '\nAuthor paragraph\n';
  const history = savedEditHistory(); history.remember(original);
  for (const incoming of [original, original.replace('intro', 'Agent intro')]) {
    const result = await decide(current, current, incoming, history);
    assert.equal(result.review, true);
    assert.equal(result.ambiguous, true);
    assert.equal(result.plan.conflicts, 0, 'a clean historical proposal still needs explicit acceptance');
  }
});

test('unsaved independent edits still combine without historical guesses', async () => {
  const base = 'one\n\ntwo\n\nthree\n';
  const result = await decide(base, base.replace('one', 'local'), base.replace('three', 'agent'));
  assert.equal(result.review, false);
  assert.equal(result.text, 'local\n\ntwo\n\nagent\n');
});

test('bounded history does not silently forget protection when capacity is exceeded', async () => {
  for (const options of [{limit: 2}, {maxBytes: 8}]) {
    const history = savedEditHistory(options);
    for (const text of ['old one\n', 'old two\n', 'old three\n']) history.remember(text);
    assert.equal(history.incomplete, true);
    const result = await decide('current\n', 'current\n', 'incoming\n', history);
    assert.equal(result.review, true);
    assert.equal(result.whole, true);
    assert.equal(result.plan.segments[0].local, 'current\n');
    history.clear();
    assert.equal(history.pending, false);
    assert.equal(history.incomplete, false);
  }
});

test('saved history deduplicates versions and does not expire with wall-clock time', () => {
  const history = savedEditHistory({limit: 1});
  history.remember('old\n'); history.remember('old\n');
  assert.deepEqual(history.versions, ['old\n']);
  assert.equal(history.incomplete, false);
});

test('very large replacement still produces exact text', () => {
  const before = 'before\n'.repeat(2100), after = 'after\n'.repeat(2100);
  assert.equal(apply(before, textChanges(before, after)), after);
});

test('an edit inside text the author saved earlier is accepted only with proof it saw that text', async () => {
  const {sawSavedEdits} = await import('../src/external-edits.mjs');
  const before = 'intro\n\n## Old slide\n\nfinal line\n';
  // The author wrote and saved a new slide; an agent then tightens one of its lines.
  const saved = before + '\n## New slide from the author\n\nFirst point the author wrote.\nSecond point the author wrote.\n';
  const targeted = saved.replace('Second point the author wrote.', 'Second point, tightened by the agent.');
  assert.equal(sawSavedEdits(before, saved, targeted), true);
  const history = savedEditHistory(); history.remember(before);
  const accepted = await decide(saved, saved, targeted, history);
  assert.equal(accepted.review, false);
  assert.equal(accepted.text, targeted);
  // The same holds when the author moved a block and the agent edits a line in it.
  const moved = '## B\n\nBlock B has a distinctive first line.\nBlock B has a second line.\n\n## A\n\nBlock A text.\n';
  const original = '## A\n\nBlock A text.\n\n## B\n\nBlock B has a distinctive first line.\nBlock B has a second line.\n';
  assert.equal(sawSavedEdits(original, moved, moved.replace('a second line', 'an edited second line')), true);
  // No proof: the whole saved edit is gone, replaced, or only trivial lines remain.
  assert.equal(sawSavedEdits(before, saved, before), false);
  assert.equal(sawSavedEdits(before, saved, before.replace('final line', 'final line, edited from the old version')), false);
  assert.equal(sawSavedEdits('Budget: 10\n', 'Budget: 20\n', 'Budget: 30\n'), false);
  assert.equal(sawSavedEdits('a\n\nz\n', 'a\n\n:::\nx\n:::\n\nz\n', 'a\n\n:::\ny\n:::\n\nz\n'), false);
  // The author deleted a paragraph; text re-inserted at that spot proves nothing.
  const deleted = 'keep\n\nend\n';
  assert.equal(sawSavedEdits('keep\n\nRemoved paragraph of the author.\n\nend\n', deleted, 'keep\n\nRemoved paragraph of the author.\n\nend\n'), false);
  assert.equal(sawSavedEdits('keep\n\nRemoved paragraph of the author.\n\nend\n', deleted, deleted.replace('end', 'end, edited elsewhere')), true);
  const stale = await decide(saved, saved, before.replace('final line', 'final line, edited from the old version'), history);
  assert.equal(stale.review, true);
});
