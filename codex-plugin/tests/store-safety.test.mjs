import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {WorkspaceStore} from '../src/store.mjs';

function fixture(run) {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'matsugit-safe-recreate-'));
  const parent = path.join(root, 'notes'); fs.mkdirSync(parent);
  const file = path.join(parent, 'draft.md'), store = new WorkspaceStore(root);
  try {
    fs.writeFileSync(file, '# Private draft\n', {mode:0o600});
    const opened = store.open(file);
    run({root, parent, file, store, opened});
  } finally { store.close(); fs.rmSync(root, {recursive:true, force:true}); }
}

test('recreation keeps private permissions and never replaces an arriving file', () => fixture(({file, parent, store, opened}) => {
  fs.unlinkSync(file);
  assert.equal(store.save(opened.session, '# Restored\n', opened.etag, {recreate:true}).outcome, 'saved');
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.equal(store.save(opened.session, 'replace', opened.etag, {recreate:true}).outcome, 'conflict');
  assert.equal(fs.readFileSync(file, 'utf8'), '# Restored\n');
  assert.deepEqual(fs.readdirSync(parent), ['draft.md']);
}));

test('recreation refuses a redirected or missing parent without creating directories', () => fixture(({root, parent, file, store, opened}) => {
  fs.unlinkSync(file);
  fs.renameSync(parent, path.join(root, 'previous'));
  const elsewhere = path.join(root, 'elsewhere'); fs.mkdirSync(elsewhere);
  fs.symlinkSync(elsewhere, parent);
  assert.throws(() => store.save(opened.session, 'private', opened.etag, {recreate:true}), /directory|path changed/i);
  assert.deepEqual(fs.readdirSync(elsewhere), []);
  fs.unlinkSync(parent);
  assert.throws(() => store.save(opened.session, 'private', opened.etag, {recreate:true}));
  assert.equal(fs.existsSync(parent), false);
}));

test('an interrupted recreation leaves neither a partial document nor a temporary file', () => fixture(({file, parent, store, opened}) => {
  fs.unlinkSync(file);
  const write = fs.writeFileSync;
  try {
    fs.writeFileSync = (target, text, options) => {
      write(target, 'partial', options);
      throw Object.assign(Error('Synthetic disk failure'), {code:'EIO'});
    };
    assert.throws(() => store.save(opened.session, '# Complete\n', opened.etag, {recreate:true}), /disk failure/);
  } finally { fs.writeFileSync = write; }
  assert.equal(fs.existsSync(file), false);
  assert.deepEqual(fs.readdirSync(parent), []);
}));

test('reopening the same document does not exhaust workspace sessions', () => fixture(({file, store, opened}) => {
  for (let i=0; i<80; i++) assert.equal(store.open(file).session, opened.session);
  assert.equal(store.sessions.size, 1);
}));
