import test from 'node:test';
import assert from 'node:assert/strict';
import {documentState} from '../src/document-state.mjs';

test('incoming edits stay pending even when the workspace draft was saved', () => {
  const facts = documentState({dirty:false,connected:true,incoming:true});
  assert.equal(facts.draft.label,'Update ready');
  assert.match(facts.draft.detail,/waiting for your acceptance/);
});
import {restoreSlide} from '../src/history-restore.mjs';
import {slideDiff,wordChanges} from '../src/slide-diff.mjs';

test('draft, last push, and verified deployment remain independent', () => {
  const value = documentState({dirty:true,connected:true,fileDigest:'new',receipt:{stage:'published',revision:'abc',deployed_revision:'abc',source_sha256:'old'}});
  assert.equal(value.draft.label,'Draft'); assert.equal(value.sent.matchesFile,false); assert.equal(value.live.label,'Live');
  assert.match(value.sent.detail,/not a fresh check/);
  assert.equal(documentState({receipt:{stage:'published',revision:'abc',deployed_revision:'other'}}).live.label,'Live version unknown');
  assert.equal(documentState({receipt:{site_url:'https://example.test'}}).live.label,'Live version unknown');
});
test('duplicate titles require explicit destination and preserve other slides', () => {
  const previous = '# Plan\n\n## Same\n\nold one\n\n## Same\n\nold two\n';
  const current = '# Plan\n\n## Same\n\nnew one\n\n## Same\n\nnew two\n';
  assert.throws(()=>restoreSlide(previous,current,0,undefined,'replace'),/explicitly/);
  const restored = restoreSlide(previous,current,0,1,'replace');
  assert.match(restored,/new one/); assert.match(restored,/old one/); assert.doesNotMatch(restored,/new two/);
  const inserted = restoreSlide(previous,current,1,0,'after');
  assert.ok(inserted.indexOf('old two') < inserted.indexOf('new two'));
  assert.equal((inserted.match(/## Same/g)||[]).length,3);
});
test('removed slides can be explicitly appended; Org and surrounding sections retained', () => {
  const previous = '* Part\n** A\nOld\n** B\nBody\n';
  const current = '* Part\n** A\nNew\n* Next\n** C\nLast\n';
  const restored = restoreSlide(previous,current,1,null,'end',true);
  assert.ok(restored.startsWith(current)); assert.ok(restored.includes('** B\nBody'));
  assert.throws(()=>restoreSlide('## A\n```\nno end','## B\n',0,0,'replace'),/unfinished/);
});
test('slide comparisons recognize moves and retitles without guessing duplicate identities', () => {
  const before = '## A\n\nOne\n\n## B\n\nTwo\n';
  const after = '## Renamed B\n\nTwo\n\n## A\n\nOne\n';
  assert.ok(slideDiff(before,after).some(x=>x.kind.includes('Retitled') && x.kind.includes('Moved')));
  const ambiguous = slideDiff('## Same\na\n## Same\nb\n','## Same\nc\n## Same\nd\n');
  assert.equal(ambiguous.filter(x=>x.kind==='Removed').length,2);
  assert.equal(ambiguous.filter(x=>x.kind==='Added').length,2);
});
test('readable word changes preserve text and isolate formatting from content', () => {
  const parts = wordChanges('## Title\n**Old** words here.','## Title\n**New** words here.');
  assert.equal(parts.map(p=>p.text ?? p.before).join(''),'Title\nOld words here.');
  assert.equal(parts.map(p=>p.text ?? p.after).join(''),'Title\nNew words here.');
  assert.ok(parts.some(p=>p.before==='Old' && p.after==='New'));
});
