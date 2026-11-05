import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mergePlan} from '../src/merge.mjs';
import {mergeResult} from '../src/merge-result.mjs';
import {selectedIncoming, changeGroups} from '../src/change-review.mjs';

test('external review includes clean edits, deletions, inserts and groups by real headings', () => {
  const base = '---\ntitle: Demo\n---\n# Section\n## One\nold\n\nstable\n\n## Two\ndelete\n\n```md\n## Fake\n```\n';
  const incoming = base.replace('old', 'new').replace('delete\n','').replace('stable','stable\ninsert');
  const plan = mergePlan(base, base, incoming);
  assert.equal(selectedIncoming(plan, [true,true,true]), incoming);
  assert.equal(selectedIncoming(plan, [false,false,false]), base);
  assert.equal(selectedIncoming(plan, [true,false,false]), base.replace('old','new'));
  assert.deepEqual(changeGroups(plan, base).map(g => g.title), ['One','Two']);
});

test('review respects Org literal blocks and Unicode / CRLF / trailing newline', () => {
  const base = '* Area\n** Slide\n#+begin_src text\n** Fake\n#+end_src\nold\n';
  assert.equal(changeGroups(mergePlan(base,base,base.replace('old','new')), base, true)[0].title, 'Slide');
  for (const [a,b] of [['','new'], ['abc',''], ['שלום\r\n','new\r\n'], ['x\n','x']]) {
    const plan = mergePlan(a,a,b);
    assert.equal(selectedIncoming(plan, plan.external.map(()=>true)), b);
    assert.equal(selectedIncoming(plan, []), a);
  }
});

test('rejecting an auto-merged change rebases over later independent typing', () => {
  const base = 'old\n\nstable\n\nlast\n';
  const incoming = base.replace('old','agent');
  const current = incoming.replace('last','my later edit');
  const result = mergeResult(mergePlan(incoming, current, base));
  assert.equal(result, base.replace('last','my later edit'));
});
