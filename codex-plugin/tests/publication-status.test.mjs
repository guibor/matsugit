import {test} from 'node:test';
import assert from 'node:assert/strict';
import {publicationLabel} from '../src/publication-status.mjs';

test('saved, pushed and deployed states cannot be confused with new draft edits', () => {
  assert.equal(publicationLabel(null,false,false),'Not pushed');
  assert.equal(publicationLabel({stage:'local'},false,false),'Not pushed');
  assert.equal(publicationLabel({stage:'pushed'},false,true),'Pushed');
  assert.equal(publicationLabel({stage:'published'},false,true),'Published');
  assert.equal(publicationLabel({stage:'published'},true,true),'Changes not pushed');
  assert.equal(publicationLabel({stage:'published'},false,false),'Changes not pushed');
  assert.equal(publicationLabel({stage:'failed'},false,true),'CI failed');
});
