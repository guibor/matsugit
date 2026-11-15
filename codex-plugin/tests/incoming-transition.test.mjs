import {test} from 'node:test';
import assert from 'node:assert/strict';
import {incomingTransition} from '../src/incoming-transition.mjs';

test('only an exact observed agent lineage permits reconciliation, never replacement', () => {
  const incoming = {currentEtag:'base', incomingEtag:'next', agentBases:['base']};
  assert.equal(incomingTransition(incoming), 'reconcile-agent');
  assert.equal(incomingTransition({...incoming, blocked:true}), 'review');
  assert.equal(incomingTransition({...incoming, agentBases:['older']}), 'review');
  assert.equal(incomingTransition({...incoming, agentBases:undefined}), 'review');
  assert.equal(incomingTransition({...incoming, agentBases:'base'}), 'review');
  assert.equal(incomingTransition({...incoming, incomingEtag:'base'}), 'unchanged');
  assert.equal(incomingTransition({...incoming, currentEtag:null}), 'review');
  assert.equal(incomingTransition({...incoming, incomingEtag:null}), 'review');
});

test('autosave and dirty draft flags cannot grant permission to replace text', () => {
  for (const autosave of [true,false]) for (const dirty of [true,false]) {
    const incoming = {currentEtag:'base',incomingEtag:'next',autosave,dirty};
    assert.equal(incomingTransition(incoming), 'review');
    assert.equal(incomingTransition({...incoming,agentBases:['base']}), 'reconcile-agent');
  }
});
