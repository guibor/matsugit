import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {RecoveryStore, preferences} from '../src/recovery.mjs';
import {WorkspaceStore} from '../src/store.mjs';

function setup(t, options) {
  const directory = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'matsugit-recovery-test-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  return new RecoveryStore(path.join(directory, 'recovery'), options);
}
const snapshot = (text = '* Draft\nUnicode: שלום\n') => ({text, base: '* Original\n',
  view: {layout: 'split', format: 'slides', theme: 'default', anchor: 12, head: 14,
    width: 42, editorScroll: 123, positions: {slides: {hash: '#/claim', h: 3, v: 0, slideId: 'claim'}}}});

test('private atomic checkpoints survive restart and restore text and view, not rendered assets', t => {
  const store = setup(t), owner = path.join(path.dirname(store.directory), 'deck.org');
  fs.writeFileSync(owner, '* Original\n');
  const {id} = store.begin({owner, name: 'deck.org'});
  store.checkpoint(id, 1, {...snapshot(), html: 'must not persist'}, owner);
  const restarted = new RecoveryStore(store.directory), {candidate, id: next} = restarted.begin({owner, name: 'deck.org'});
  assert.notEqual(next, id);
  assert.equal(candidate.text, snapshot().text);
  assert.equal(candidate.view.positions.slides.slideId, 'claim');
  assert.equal(candidate.view.width, 42);
  assert.equal(candidate.html, undefined);
  assert.equal(fs.readFileSync(owner, 'utf8'), '* Original\n');
  assert.deepEqual(fs.readdirSync(store.directory), [id + '.json']);
  if (process.getuid) {
    assert.equal(fs.statSync(store.directory).mode & 0o777, 0o700);
    assert.equal(fs.statSync(store.file(id)).mode & 0o777, 0o600);
  }
});

test('simultaneous viewers have separate records, ordered writes and document scopes', t => {
  const store = setup(t), other = new RecoveryStore(store.directory);
  const a = store.begin({owner: '/a.md'}).id, b = other.begin({owner: '/a.md'}).id;
  store.checkpoint(a, 2, snapshot('one'), '/a.md');
  other.checkpoint(b, 1, snapshot('two'), '/a.md');
  assert.deepEqual(store.checkpoint(a, 1, snapshot('stale'), '/a.md'), {stale: true});
  assert.equal(store.read(a).text, 'one');
  assert.equal(store.read(b).text, 'two');
  assert.equal(store.list('/a.md').items.length, 2);
  assert.equal(store.list('/b.md').items.length, 0);
  assert.throws(() => store.checkpoint(a, 3, snapshot(), '/b.md'), /expired/);
  assert.throws(() => other.checkpoint(a, 3, snapshot(), '/a.md'), /expired/);
});

test('explicit deletion checks freshness and cannot be resurrected by another running writer', t => {
  const store = setup(t), other = new RecoveryStore(store.directory), {id} = store.begin({});
  store.checkpoint(id, 1, snapshot());
  const before = other.read(id);
  store.checkpoint(id, 2, snapshot('newer'));
  assert.throws(() => other.forget(id, before.token), /changed/);
  other.forget(id, other.read(id).token);
  assert.throws(() => store.checkpoint(id, 3, snapshot()), /removed/);
  assert.equal(store.list().items.length, 0);
});

test('storage limit refuses new work without deleting old drafts or corrupting previous checkpoint', t => {
  const store = setup(t, {maxRecords: 1, maxBytes: 3000}), {id} = store.begin({});
  store.checkpoint(id, 1, snapshot('kept'));
  assert.throws(() => store.checkpoint(store.begin({}).id, 1, snapshot()), /full/);
  assert.throws(() => store.checkpoint(id, 2, snapshot('x'.repeat(4000))), /full/);
  assert.equal(store.read(id).text, 'kept');
  assert.deepEqual(fs.readdirSync(store.directory), [id + '.json']);
});

test('corrupt records and interrupted locks are retained; other viewers can recover', t => {
  const store = setup(t), {id} = store.begin({});
  store.checkpoint(id, 1, snapshot());
  const corrupt = path.join(store.directory, randomUUID() + '.json');
  fs.writeFileSync(corrupt, '{truncated', {mode: 0o600});
  assert.equal(store.list().unreadable, 1);
  fs.writeFileSync(store.file(id) + '.lock', '', {mode: 0o600});
  assert.throws(() => store.checkpoint(id, 2, snapshot('changed')), /interrupted/);
  assert.equal(store.read(id).text, snapshot().text);
  const restarted = new RecoveryStore(store.directory), next = restarted.begin({});
  assert.equal(next.candidate.id, id);
  restarted.checkpoint(next.id, 1, snapshot('recovered'));
  assert.equal(fs.readFileSync(corrupt, 'utf8'), '{truncated');
});

test('rejects traversal, nonprivate files and symlinks without following them', t => {
  const store = setup(t), {id} = store.begin({});
  assert.throws(() => store.read('../outside'), /Invalid/);
  store.checkpoint(id, 1, snapshot());
  if (process.getuid) {
    fs.chmodSync(store.file(id), 0o644);
    assert.throws(() => store.read(id), /Unsafe/);
    fs.chmodSync(store.file(id), 0o600);
    const linked = randomUUID();
    fs.symlinkSync(store.file(id), store.file(linked));
    assert.throws(() => store.read(linked), /Unsafe/);
    fs.chmodSync(store.directory, 0o755);
    assert.throws(() => store.begin({}), /private/);
  }
});

test('validates source size, Unicode, preferences and unnamed/resource identities', t => {
  const store = setup(t), {id} = store.begin({resourceUri: 'host://a'});
  assert.throws(() => store.checkpoint(id, 1, snapshot('\0')), /Invalid source/);
  assert.throws(() => store.checkpoint(id, 1, snapshot('א'.repeat(1024 * 1024 + 1))), /2 MiB/);
  store.checkpoint(id, 1, snapshot('x'.repeat(2 * 1024 * 1024)));
  assert.equal(store.begin({resourceUri: 'host://a'}).candidate.id, id);
  assert.equal(store.begin({resourceUri: 'host://b'}).candidate, null);
  assert.equal(store.begin({}).candidate, null);
  assert.equal(preferences(null).layout, 'split');
  const view = preferences({theme: '../bad', head: -1, width: 500, height: 0, layout: 'wrong', positions: {slides: {hash: 'javascript:bad'}}});
  assert.equal(view.theme, ''); assert.equal(view.width, 80); assert.equal(view.height, 20);
  assert.equal(view.head, 0); assert.equal(view.layout, 'split'); assert.equal(view.positions.slides.hash, '');
});

test('recovery identity remains usable when source disappears, but source operations still reject it', t => {
  const recovery = setup(t), file = path.join(path.dirname(recovery.directory), 'deck.md');
  fs.writeFileSync(file, '# Original');
  const store = new WorkspaceStore('.'), {session} = store.open(file);
  fs.unlinkSync(file);
  assert.equal(store.recoveryOwner(session, file), file);
  assert.throws(() => store.source(session));
  assert.throws(() => store.recoveryOwner(session, '/other.md'), /do not match/);
  assert.throws(() => store.recoveryOwner('expired', file), /expired/);
});
