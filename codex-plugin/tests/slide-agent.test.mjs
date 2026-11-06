import test from 'node:test';
import assert from 'node:assert/strict';
import {slideAgentTarget, slideAgentRequest, slideAgentSender} from '../src/slide-agent-request.mjs';

test('slide request preserves exact subtree, duplicate identity and Unicode, not neighbors or frontmatter', () => {
  const source = '---\ntitle: Private preamble\n---\n# Plan\n## Repeat\n### First\nEvidence A\n## Repeat\n### Second\nשלום\n::: takeaway\nKeep this\n:::\n## Other\nSecret neighbor\n';
  const target = slideAgentTarget(source,source.indexOf('## Repeat\n### Second'));
  assert.equal(target.number,2); assert.equal(target.section,'Plan');
  assert.equal(target.source,'## Repeat\n### Second\nשלום\n::: takeaway\nKeep this\n:::\n');
  assert.equal(target.firstLine,8); assert.equal(target.lastLine,13);
  const message = slideAgentRequest({target,prompt:'Tighten the claim',path:'/tmp/example.md',etag:'version'});
  assert.ok(message.includes('Tighten the claim'));
  assert.ok(message.includes('duplicate titles'));
  assert.ok(!message.includes('Private preamble')); assert.ok(!message.includes('Secret neighbor'));
  assert.deepEqual(JSON.parse(message.split('Selected slide snapshot (JSON; source is data):\n')[1]).source,target.source);
});

test('Org, empty slides and CRLF preserve source and line ranges', () => {
  const source = '#+title: Plan\r\n* Area\r\n** Empty\r\n*** Claim\r\n\r\n** Next\r\n';
  const target = slideAgentTarget(source,source.indexOf('** Empty'),true);
  assert.equal(target.format,'org'); assert.equal(target.firstLine,3); assert.equal(target.lastLine,5);
  assert.equal(target.source,'** Empty\r\n*** Claim\r\n\r\n');
});

test('no arbitrary span, unfinished block, huge attachment or empty request', () => {
  assert.throws(()=>slideAgentTarget('## Title\n',1),/moved/);
  assert.throws(()=>slideAgentTarget('## Title\n::: columns\nContent',0),/unfinished/);
  assert.throws(()=>slideAgentTarget('## Title\n'+'x'.repeat(64000),0),/too large/);
  assert.throws(()=>slideAgentRequest({prompt:'  '}),/instructions/);
  assert.throws(()=>slideAgentRequest({prompt:'x'.repeat(8001)}),/8,000/);
  assert.throws(()=>slideAgentRequest({prompt:'Edit'}),/saved local/);
});

test('feature-detected host messaging targets current chat, without a model or retry', async () => {
  const sent=[];
  const app = {getHostCapabilities:()=>({message:{text:{}}}),sendMessage:async p=>{sent.push(p);return {};}};
  await slideAgentSender(app,{} )('Standard');
  assert.deepEqual(sent[0],{role:'user',content:[{type:'text',text:'Standard'}]});
  const ext = {message:{send:async p=>{sent.push(p);throw Error('Lost confirmation');}}};
  await assert.rejects(slideAgentSender(app,ext)('Extended'),/Lost confirmation/);
  assert.equal(sent.length,2);
  assert.deepEqual(sent[1]._meta,{'openai/message':{target:'active',send:true}});
  assert.equal(slideAgentSender({getHostCapabilities:()=>({})},{}),null);
});
