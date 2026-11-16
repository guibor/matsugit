import {test} from 'node:test';
import assert from 'node:assert/strict';
import {browserBlocker} from '../src/browser-button.mjs';

test('browser handoff waits for pending edits and requires a local file', () => {
  const ready = {path:'/tmp/deck.md', etag:'revision'};
  assert.equal(browserBlocker(ready), '');
  assert.equal(browserBlocker({...ready, dirty:true}), ''); // The UI asks to save.
  assert.match(browserBlocker({etag:'revision'}), /local/);
  for (const key of ['pendingTable', 'incomingReady', 'externalPending', 'conflict',
    'loading', 'saving', 'merging', 'delivering'])
    assert.ok(browserBlocker({...ready, [key]:true}), key);
});
