import {test} from 'node:test';
import assert from 'node:assert/strict';
import {saveStatus, changeNotice} from '../src/save-status.mjs';

test('file status distinguishes edits, save, conflict, failed save and local copies', () => {
  const file = {writable:true,etag:'version'};
  assert.equal(saveStatus(file,false).label,'Saved to file');
  assert.equal(saveStatus(file,true).label,'Unsaved draft');
  assert.equal(saveStatus({...file,saving:true},true).label,'Saving...');
  assert.equal(saveStatus({...file,conflict:true},false).label,'Changed elsewhere');
  assert.equal(saveStatus({...file,saveError:'No space'},true).detail,'No space');
  assert.equal(saveStatus({},false).label,'Local copy');
  assert.equal(saveStatus({},true).label,'Unsaved copy');
  assert.equal(saveStatus(file,false,true).label,'Table edits');
  assert.equal(saveStatus({...file,merging:true},true).label,'Merging...');
  assert.equal(saveStatus({...file,fileMissing:true},false).label,'File missing');
  assert.equal(saveStatus({...file,fileMissing:true},true).label,'File missing');
});

test('recovery status is never used as evidence that the source file was saved', () => {
  assert.equal(saveStatus({writable:true,etag:'old',recoveryStatus:'saved'},true).label,'Unsaved draft');
  assert.match(saveStatus({writable:true,etag:'new',lastSavedAt:Date.now()},false).detail,/Saved to the source file/);
});

test('external-change receipts distinguish retained drafts, combined drafts and clean updates', () => {
  assert.equal(changeNotice({}, true), null);
  assert.match(changeNotice({conflict:true, fileReceipt:'merged'},true).detail, /No file has been overwritten/);
  assert.equal(changeNotice({fileReceipt:'merged'},true).title, 'Changes combined in your draft');
  assert.match(changeNotice({fileReceipt:'merged'},true).detail, /Not saved/);
  assert.match(changeNotice({fileReceipt:'reviewed'},true).detail, /unchanged until you save/);
  assert.match(changeNotice({fileReceipt:'updated'},false).detail, /no local edits/);
  assert.match(changeNotice({fileReceipt:'updated'},true).detail, /unsaved edits/);
});
