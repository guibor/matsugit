import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {WorkspaceStore, checkedPath, checkedText, MAX_SOURCE} from '../src/store.mjs';

test('opening and saving only the selected file, with conflicts and permissions preserved', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'folioforge-store-test-'));
  const file = path.join(directory, 'note.md');
  const store = new WorkspaceStore(directory);
  try {
    fs.writeFileSync(file, '# Before\n', {mode: 0o600});
    const opened = store.open(file);
    assert.equal(opened.text, '# Before\n');
    assert.equal(store.save(opened.session, '# After\n', opened.etag).outcome, 'saved');
    assert.equal(fs.readFileSync(file, 'utf8'), '# After\n');
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
    assert.equal(store.save(opened.session, '# Stale\n', opened.etag).outcome, 'conflict');
    assert.equal(fs.readFileSync(file, 'utf8'), '# After\n');
    fs.writeFileSync(file, '# External edit\n');
    assert.equal(store.source(opened.session).text, '# External edit\n');
    assert.throws(() => store.save('unknown', 'text', 'etag'));
    assert.deepEqual(fs.readdirSync(directory), ['note.md']);
    fs.writeFileSync(path.join(directory, 'other.md'), '# Other');
    fs.unlinkSync(file); fs.symlinkSync('other.md', file);
    assert.throws(() => store.source(opened.session), /path changed/);
    assert.throws(() => store.save(opened.session, 'changed', opened.etag), /path changed/);
    assert.throws(() => store.owner(opened.session), /path changed/);
  } finally { store.close(); fs.rmSync(directory, {recursive: true, force: true}); }
});
test('paths, document size, source text and theme options are constrained', () => {
  assert.throws(() => checkedPath('../not-absolute.md'));
  assert.throws(() => checkedText('x'.repeat(MAX_SOURCE + 1)));
  assert.throws(() => checkedText('bad\0text'));
  const store = new WorkspaceStore('/tmp');
  assert.throws(() => store.start({text: '# X', theme: '../private', name: 'x.md'}));
  assert.throws(() => store.status('unknown'));
});
test('large preview transfers are bounded and preserve Unicode across chunks', () => {
  const store = new WorkspaceStore('/tmp');
  const html = 'x'.repeat(256 * 1024 - 1) + '\u{1f680}' + 'y'.repeat(256 * 1024);
  store.jobs.set('preview', {owner: null, state: 'ready', rendered: {document: html, slides: '<html></html>'}});
  assert.equal(store.status('preview').rendered, undefined);
  let offset = 0, output = '';
  while (true) {
    const part = store.chunk('preview', 'document', offset);
    assert.ok(part.chunk.length <= 256 * 1024);
    output += JSON.parse(JSON.stringify(part.chunk)); offset = part.next;
    if (part.done) break;
  }
  assert.equal(output, html);
  assert.throws(() => store.chunk('preview', 'document', -1));
  assert.throws(() => store.chunk('preview', 'other', 0));
});
