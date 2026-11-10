import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {WorkspaceStore, checkedPath, checkedText, MAX_SOURCE} from '../src/store.mjs';

test('opening and saving only the selected file, with conflicts and permissions preserved', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-store-test-'));
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
  assert.throws(() => store.start({text: '# X', format: 'other'}));
  assert.throws(() => store.status('unknown'));
});

test('saving identical source does not rewrite the file or bypass conflicts', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-unchanged-test-'));
  const file = path.join(directory, 'note.md'), store = new WorkspaceStore(directory);
  try {
    fs.writeFileSync(file, '# Same text\r\n', {mode: 0o600});
    fs.utimesSync(file, 1000000000, 1000000000);
    const opened = store.open(file), before = fs.statSync(file, {bigint: true});
    for (let i = 0; i < 3; i++) {
      assert.deepEqual(store.save(opened.session, opened.text, opened.etag),
        {outcome: 'saved', etag: opened.etag});
    }
    const after = fs.statSync(file, {bigint: true});
    assert.equal(after.ino, before.ino);
    assert.equal(after.mtimeNs, before.mtimeNs);
    assert.equal(after.ctimeNs, before.ctimeNs);
    fs.writeFileSync(file, '# External edit\n');
    // Matching today's contents is not permission to ignore a stale revision.
    assert.equal(store.save(opened.session, '# External edit\n', opened.etag).outcome, 'conflict');
    assert.equal(fs.readFileSync(file, 'utf8'), '# External edit\n');
  } finally { store.close(); fs.rmSync(directory, {recursive: true, force: true}); }
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
test('a removed plugin cache asks for a reload before allocating a render job', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-missing-plugin-'));
  fs.rmdirSync(directory);
  const store = new WorkspaceStore(directory);
  assert.throws(() => store.start({text: '# Draft'}), /plugin files.*Save or download.*reload/);
  assert.equal(store.jobs.size, 0);
});

test('cancel is scoped to its document and cannot cancel a completed render', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-cancel-test-'));
  const store = new WorkspaceStore(directory);
  try {
    const file = path.join(directory, 'a.md'), other = path.join(directory, 'b.md');
    fs.writeFileSync(file, '# A'); fs.writeFileSync(other, '# B');
    const a = store.open(file), b = store.open(other);
    const stopped = [];
    store.stopChild = child => stopped.push(child);
    store.jobs.set('job', {owner: file, state: 'rendering', child: 'owned-process'});
    assert.throws(() => store.cancel('job', b.session), /Unknown preview/);
    assert.equal(store.status('job', a.session).state, 'rendering');
    assert.equal(store.cancel('job', a.session).state, 'canceled');
    store.cancel('job', a.session);
    assert.deepEqual(stopped, ['owned-process']);
    store.jobs.set('ready', {owner: file, state: 'ready'});
    assert.equal(store.cancel('ready', a.session).state, 'ready');
    assert.throws(() => store.start({text: '# B', session: b.session, base: 'ready'}), /Unknown preview/);
  } finally { store.jobs.clear(); store.close(); fs.rmSync(directory, {recursive: true, force: true}); }
});
test('explicit relocation rebinds source without replacing its symlink on save', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-link-test-'));
  const original = path.join(directory, 'note.md'), target = path.join(directory, 'canonical.md');
  fs.writeFileSync(original, '# Original\n');
  const store = new WorkspaceStore(directory);
  try {
    const opened = store.open(original);
    fs.renameSync(original, target); fs.symlinkSync(target, original);
    assert.throws(() => store.source(opened.session), /path changed/);
    const rebound = store.relocated(original, target);
    assert.equal(store.owner(opened.session, original), target);
    assert.equal(store.save(rebound.session, '# Updated\n', rebound.etag).outcome, 'saved');
    assert.ok(fs.lstatSync(original).isSymbolicLink());
    assert.equal(fs.readFileSync(original, 'utf8'), '# Updated\n');
  } finally { store.close(); fs.rmSync(directory, {recursive:true,force:true}); }
});
