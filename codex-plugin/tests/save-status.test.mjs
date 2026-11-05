import {test} from 'node:test';
import assert from 'node:assert/strict';
import {saveStatus} from '../src/save-status.mjs';

test('file status distinguishes edits, save, conflict, failed save and local copies', () => {
  const file = {writable:true,etag:'version'};
  assert.equal(saveStatus(file,false).label,'Saved');
  assert.equal(saveStatus(file,true).label,'Unsaved');
  assert.equal(saveStatus({...file,saving:true},true).label,'Saving...');
  assert.equal(saveStatus({...file,conflict:true},false).label,'Review changes');
  assert.equal(saveStatus({...file,saveError:'No space'},true).detail,'No space');
  assert.equal(saveStatus({},false).label,'Local copy');
  assert.equal(saveStatus({},true).label,'Unsaved copy');
  assert.equal(saveStatus(file,false,true).label,'Table edits');
  assert.equal(saveStatus({...file,merging:true},true).label,'Merging...');
});

test('recovery status is never used as evidence that the source file was saved', () => {
  assert.equal(saveStatus({writable:true,etag:'old',recoveryStatus:'saved'},true).label,'Unsaved');
  assert.match(saveStatus({writable:true,etag:'new',lastSavedAt:Date.now()},false).detail,/Saved to the source file/);
});
