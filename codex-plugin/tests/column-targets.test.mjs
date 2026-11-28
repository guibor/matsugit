import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Text} from '@codemirror/state';
import {structure} from '../src/structure.mjs';
import {columnCaret} from '../src/column-targets.mjs';

const group='::::: columns\n:::: column\n#### Pickup\n- Same day.\n::::\n:::: column\n#### Delivery\n- Same day.\n::::\n:::::';
const go=(s, overrides={})=>columnCaret(Text.of(s.split('\n')),structure(s),{slide:'options',occurrence:0,
  kind:'columns',keys:['pickup','delivery'],index:1,...overrides});
test('explicit Markdown columns keep identical bullets separate',()=>{
  const source='## Options\n\n'+group;
  assert.equal(go(source),source.lastIndexOf('Same day.')+9);
  assert.equal(go(source,{index:0}),source.indexOf('Same day.')+9);
  assert.equal(go(source,{keys:['delivery','pickup']}),null);
  assert.equal(go(source,{index:3}),null);
});
test('ambiguous groups, unrecognised slides and literal tails are not edit targets',()=>{
  const source='## Options\n\n'+group;
  assert.equal(go(source+'\n\n'+group),null);
  assert.equal(go(source,{slide:'other'}),null);
  assert.equal(go(source.replace('Delivery\n- Same day.', 'Delivery\n\n```text\ncode\n```')),null);
});
