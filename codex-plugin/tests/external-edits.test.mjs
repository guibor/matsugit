import {test} from 'node:test';
import assert from 'node:assert/strict';
import {textChanges, distance, closestAncestor} from '../src/external-edits.mjs';

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

test('the version another writer started from is recognised, and ties prefer the latest', () => {
  const read = 'intro\n\nslide one\n\nslide two\n';              // what the agent read
  const typed = 'intro\n\nslide one\n\nmy new line\n\nslide two\n';  // autosaved since
  const latest = typed.replace('my new line', 'my new line, finished');
  const history = [latest, typed, read];
  // A whole-file rewrite from the old read: closest to that read.
  assert.equal(closestAncestor(history, read.replace('slide two', 'slide two, improved')), 2);
  // A targeted edit of the current file: closest to the latest.
  assert.equal(closestAncestor(history, latest.replace('intro', 'Intro')), 0);
  // Identical distances never pick an older version.
  assert.equal(closestAncestor([latest, latest], 'unrelated\n'), 0);
  assert.equal(distance(read, read), 0);
  assert.equal(distance(read, typed), 2);
});
