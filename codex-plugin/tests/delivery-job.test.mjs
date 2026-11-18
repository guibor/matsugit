import test from 'node:test';
import assert from 'node:assert/strict';
import {deliveryJob} from '../src/delivery-job.mjs';

const closed = Error('MCP error -32000: Transport closed');
for (const [label, replies, expected] of [
  ['lost start response', [closed], null],
  ['lost progress response', [{state:'running',job:'a'}, closed, {state:'ready'}], 'ready'],
  ['job disappeared after disconnect', [{state:'running',job:'a'}, closed, Error('Unknown job')], null],
  ['job reports failure', [{state:'running',job:'a'}, {state:'failed',error:'Rejected'}], 'failed']
]) test(label, async () => {
  const calls = [];
  const request = async (name, args) => {
    calls.push(name);
    if (name.endsWith('_status')) assert.deepEqual(args, {session:'s',job:'a'});
    const result = replies[calls.length - 1];
    if (result instanceof Error) throw result;
    return result;
  };
  const job = deliveryJob(request, {session:'s'}, 'publish', {}, {}, async () => {});
  if (expected) assert.equal((await job).state, expected);
  else await assert.rejects(job, e => e.unconfirmed && /latest commit/.test(e.message));
  assert.deepEqual(calls, ['matsugit_action', ...replies.slice(1).map(() => 'matsugit_action_status')]);
});
