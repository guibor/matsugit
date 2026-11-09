import test from 'node:test';
import assert from 'node:assert/strict';
import {hostResultData, sourceText} from '../src/host-results.mjs';

test('standard results, metadata and JSON text all retain document identity', () => {
  const summary = {session:'abc', name:'car.md', layout:'split', format:'slides'};
  assert.deepEqual(hostResultData({structuredContent:summary}), summary);
  assert.deepEqual(hostResultData({content:[{type:'text', text:JSON.stringify(summary)}]}), summary);
  assert.equal(sourceText(hostResultData({structuredContent:summary, _meta:{source:'draft'}})), 'draft');
  assert.equal(sourceText(hostResultData({structuredContent:{source:''}})), '');
});

test('missing source is an error, never a writable empty document', () => {
  for (const response of [{}, {text:null}, {source:12}, {source:[]}]) {
    assert.throws(() => sourceText(response), /did not return the document text/);
  }
  assert.deepEqual(hostResultData({content:[{type:'text', text:'Human-readable status'}]}), {});
  assert.deepEqual(hostResultData({content:[{type:'text', text:'["not an object"]'}]}), {});
  assert.throws(() => hostResultData({isError:true, content:[{type:'text', text:'Read failed'}]}), /Read failed/);
});
