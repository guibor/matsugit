import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mergePlan} from '../src/merge.mjs';
import {mergeResult} from '../src/merge-result.mjs';
import {MergeService} from '../src/merge-service.mjs';

test('merge combines separate edits and preserves Unicode, whitespace and final newline', () => {
  const base = '# Title\n\nOriginal one\n\nOriginal two\n';
  const local = base.replace('Original one', 'My שלום change');
  const incoming = base.replace('Original two', 'Agent change');
  const plan = mergePlan(base, local, incoming);
  assert.equal(plan.conflicts, 0);
  assert.equal(mergeResult(plan), local.replace('Original two', 'Agent change'));
  for (const value of ['', 'no newline', '\tCRLF\r\n', '\n\n']) {
    assert.equal(mergeResult(mergePlan(value, value, value)), value);
    assert.equal(mergeResult(mergePlan(value, value, value + 'new')), value + 'new');
  }
});

test('same edits do not duplicate and conflicting edits require explicit resolutions', () => {
  assert.equal(mergeResult(mergePlan('old\n', 'new\n', 'new\n')), 'new\n');
  const plan = mergePlan('old\n\nstable\n\nold2\n', 'mine\n\nstable\n\nmine2\n', 'agent\n\nstable\n\nagent2\n');
  assert.equal(plan.conflicts, 2);
  assert.throws(() => mergeResult(plan), /Resolve every/);
  assert.throws(() => mergeResult(plan, ['mine\n']), /Resolve every/);
  assert.equal(mergeResult(plan, ['mine\n', 'agent2\n']), 'mine\n\nstable\n\nagent2\n');
  assert.equal(plan.segments[0].base, 'old\n');
  assert.equal(plan.segments[0].line, 1);
});

test('delete versus edit and concurrent insertions are not guessed', () => {
  for (const [base, mine, incoming] of [['A\n', '', 'B\n'], ['', 'Mine', 'Agent'], ['a\nb\n', 'a\n', 'a\nB\n']]) {
    const plan = mergePlan(base, mine, incoming);
    assert.equal(plan.conflicts, 1);
    const conflicts = plan.segments.filter(s => !('text' in s));
    assert.equal(mergeResult(plan, conflicts.map(s => s.local)), mine);
    assert.equal(mergeResult(plan, conflicts.map(s => s.incoming)), incoming);
  }
});

test('merge worker is bounded, asynchronous and closes cleanly', async () => {
  const service = new MergeService();
  try {
    const base = Array.from({length:8000}, (_,i) => `line ${i}\n`).join('');
    const local = base.replace('line 5\n', 'local five\n'), incoming = base.replace('line 7000\n', 'agent seven thousand\n');
    const plan = await service.plan({base, local, incoming});
    assert.equal(plan.conflicts, 0);
    assert(mergeResult(plan).includes('agent seven thousand'));
    await assert.rejects(service.plan({base, local, incoming}, 1), /too long/);
    await assert.rejects(service.plan({base:'x'.repeat(2*1024*1024+1),local:'',incoming:''}), /2 MiB/);
    assert.equal(service.active.size, 0);
  } finally { service.close(); }
});
