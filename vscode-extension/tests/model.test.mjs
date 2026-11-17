import test from 'node:test';
import assert from 'node:assert/strict';
import {DocumentModel, checkedText, replacement, safeLink, download, position} from '../model.mjs';

function fixture(text = 'Title\nClaim\n') {
  const notifications = [];
  const document = {isDirty: false, getText: () => text, save: async () => { document.isDirty = false; model.saved(); return true; }};
  const model = new DocumentModel(document, async edit => {
    text = text.slice(0, edit.start) + edit.text + text.slice(edit.end);
    document.isDirty = true; model.changed(); return true;
  }, message => notifications.push(message));
  return {model, document, notifications, external: value => {text = value; document.isDirty = true; model.changed();}};
}
test('minimal changes retain surrounding text and Unicode', () => {
  assert.deepEqual(replacement('hello\nworld', 'hello\nthere'), {start: 6, end: 11, text: 'there'});
  for (const [a,b] of [['', 'a'], ['a',''], ['same','same'], ['a\u{1f680}x','a\u{1f680}y']]) {
    const change = replacement(a,b);
    assert.equal(a.slice(0,change.start)+change.text+a.slice(change.end),b);
  }
});
test('Windows newlines use logical editor positions and retain native EOL on Save', async () => {
  let text = 'Title\r\nClaim\r\n';
  const document = {isDirty:false, getText:()=>text, save:async()=>{document.isDirty=false;return true;}};
  const model = new DocumentModel(document, async edit => {
    assert.deepEqual(position(text, edit.start), {line:1,character:0});
    text = 'Title\r\nBetter\r\n';document.isDirty=true;model.changed();return true;
  });
  const before = model.snapshot();
  assert.equal(before.source,'Title\nClaim\n');
  assert.equal((await model.edit({base:before.source,text:'Title\nBetter\n'})).applied,true);
  assert.equal((await model.save({etag:before.etag,text:'Title\nBetter\n'})).outcome,'saved');
  assert.equal(text,'Title\r\nBetter\r\n');
});
test('draft writes update the native buffer but never save or advance external version', async () => {
  const {model, document, notifications} = fixture();
  const before = model.snapshot();
  assert.equal((await model.edit({base: before.source, text: 'Edited\nClaim\n'})).applied, true);
  assert.equal(document.isDirty, true);
  assert.equal(model.snapshot().etag, before.etag);
  assert.deepEqual(notifications, [{dirty: true, external: false}]);
});
test('a stale draft cannot overwrite another editor', async () => {
  const {model, external} = fixture();
  const before = model.snapshot(); external('Colleague\nClaim\n');
  assert.equal((await model.edit({base: before.source, text: 'Author\nClaim\n'})).applied, false);
  assert.equal(model.snapshot().source, 'Colleague\nClaim\n');
  assert.notEqual(model.snapshot().etag, before.etag);
});
test('save checks both the buffer and external revision', async () => {
  const {model, document} = fixture();
  const before = model.snapshot();
  await model.edit({base: before.source, text: 'Edited'});
  assert.deepEqual(await model.save({text:'stale', etag:before.etag}), {outcome:'conflict'});
  assert.equal(document.isDirty,true);
  assert.equal((await model.save({text:'Edited',etag:before.etag})).outcome,'saved');
  assert.equal(document.isDirty,false);
});
test('native save refusal retains dirty buffer', async () => {
  const {model, document} = fixture(); document.save = async () => false;
  const state = model.snapshot(); await model.edit({base: state.source, text:'Draft'});
  await assert.rejects(model.save({text:'Draft',etag:state.etag}),/did not save/);
  assert.equal(document.getText(),'Draft'); assert.equal(document.isDirty,true);
});
test('queued writers are compared against the accepted buffer', async () => {
  const {model} = fixture(); const base = model.snapshot().source;
  const a = model.edit({base,text:'First'}), b = model.edit({base,text:'Second'});
  assert.equal((await a).applied,true); assert.equal((await b).applied,false);
  assert.equal(model.snapshot().source,'First');
});
test('invalid documents and executable links are refused', () => {
  assert.throws(() => checkedText('bad\0text')); assert.throws(() => checkedText('x'.repeat(2097153)));
  for (const url of ['command:workbench.action.closeWindow','file:///etc/passwd','https://user:pass@example.com'])
    assert.throws(() => safeLink(url));
  assert.equal(safeLink('http://example.test/deck'), 'http://example.test/deck');
});
test('export names are leaf names and bytes are checked', () => {
  const value = download({contents:[{type:'resource',resource:{uri:'file:///deck.pdf',blob:'aGVsbG8='}}]});
  assert.equal(value.name,'deck.pdf'); assert.equal(value.bytes.toString(),'hello');
  assert.throws(() => download({contents:[]}));
  assert.throws(() => download({contents:[{type:'resource',resource:{uri:'file:///..',blob:'%%%'}}]}));
});
