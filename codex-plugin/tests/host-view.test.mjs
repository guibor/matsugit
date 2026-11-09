import test from 'node:test';
import assert from 'node:assert/strict';
import {cursorHost, inlineEditorHeight} from '../src/host-view.mjs';

test('Cursor context policy follows the negotiated host, not the document or machine', () => {
  assert.equal(cursorHost({userAgent:'cursor'}, {}), true);
  assert.equal(cursorHost({}, {name:'Cursor',version:'3.26.16'}), true);
  assert.equal(cursorHost({}, {name:'Codex'}), false);
  assert.equal(cursorHost(undefined, undefined), false);
});

test('inline editor requests useful space without ignoring host constraints', () => {
  assert.equal(inlineEditorHeight({displayMode:'inline'}), 760);
  assert.equal(inlineEditorHeight({displayMode:'inline',containerDimensions:{maxHeight:800}}), 760);
  assert.equal(inlineEditorHeight({displayMode:'inline',containerDimensions:{maxHeight:500}}), 500);
  assert.equal(inlineEditorHeight({displayMode:'inline',containerDimensions:{height:450,maxHeight:600}}), 450);
  assert.equal(inlineEditorHeight({displayMode:'inline',containerDimensions:{height:-2,maxHeight:NaN}}), 760);
  assert.equal(inlineEditorHeight({displayMode:'fullscreen'}), null);
  assert.equal(inlineEditorHeight({}), null);
});
