import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {AgentEdits, patchSlide, MAX_SLIDE} from '../src/agent-edits.mjs';
import {WorkspaceStore, saveDocument} from '../src/store.mjs';

const source = '---\ntitle: Private metadata\n---\n# Plan\n## Repeat\n### First claim\nEvidence A\n\n## Repeat\n### Second claim\nEvidence B\n\n::: notes\nKeep speaker detail.\n:::\n\n## Last\nUnrelated content.\n';
const edit = [{old:'Evidence B',new:'Updated evidence B'}];
function fixture(t,options) {
  const folder = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'matsugit-scoped-')));
  const file = path.join(folder,'deck.md');
  fs.writeFileSync(file,source);
  const store = new WorkspaceStore('.'), api = new AgentEdits(options);
  t.after(() => { store.close(); fs.rmSync(folder,{recursive:true,force:true}); });
  return {folder,file,store,api};
}

test('snapshot identifies duplicate titles by position and reveals only the selected slide', t => {
  const {file,api} = fixture(t);
  const snapshot = api.read(file,2);
  assert.equal(snapshot.title,'Repeat'); assert.equal(snapshot.section,'Plan');
  assert.equal(snapshot.slides,3); assert.equal(snapshot.readOnly,false);
  assert.match(snapshot.source,/Second claim/);
  assert.doesNotMatch(snapshot.source,/Private metadata|First claim|Unrelated content/);
  const result = api.edit(snapshot.edit_id,edit);
  assert.equal(result.outcome,'saved');
  assert.equal(fs.readFileSync(file,'utf8'),source.replace('Evidence B','Updated evidence B'));
  assert.throws(() => api.edit(snapshot.edit_id,edit),/already used/);
});

test('previews and identical edits do not write, change timestamps or discard the edit snapshot', t => {
  const {file,api} = fixture(t), snapshot = api.read(file,2);
  const before = fs.statSync(file).mtimeMs;
  const preview = api.edit(snapshot.edit_id,edit,true);
  assert.equal(preview.outcome,'preview'); assert.match(preview.source,/Updated evidence B/);
  assert.equal(fs.readFileSync(file,'utf8'),source);
  assert.equal(api.edit(snapshot.edit_id,[{old:'Evidence B',new:'Evidence B'}]).outcome,'saved');
  assert.equal(fs.statSync(file).mtimeMs,before);
});

test('any intervening save or reorder rejects stale edits without guessing another target', t => {
  const {file,api} = fixture(t);
  for (const change of [s => s.replace('Evidence A','Human edit A'), s => s.replace('## Repeat\n### First','## New\n\n## Repeat\n### First')]) {
    fs.writeFileSync(file,source);
    const snapshot = api.read(file,2), changed = change(source);
    fs.writeFileSync(file,changed);
    assert.equal(api.edit(snapshot.edit_id,edit).outcome,'conflict');
    assert.equal(api.read(file,2,snapshot.etag).outcome,'conflict');
    assert.equal(fs.readFileSync(file,'utf8'),changed);
  }
});

test('a writer racing the final save is checked again and retained', t => {
  const {file,api} = fixture(t), snapshot = api.read(file,2);
  api.save = (...args) => { fs.writeFileSync(file,source.replace('Evidence B','Human revision')); return saveDocument(...args); };
  assert.equal(api.edit(snapshot.edit_id,edit).outcome,'conflict');
  assert.match(fs.readFileSync(file,'utf8'),/Human revision/);
});

test('ambiguous, overlapping, missing, cross-slide and boundary-changing edits are refused', () => {
  for (const changes of [
    [{old:'e',new:'X'}], [{old:'Not here',new:'X'}], [{old:'Evidence A',new:'X'}],
    [{old:'Evidence B',new:'X'},{old:'Evidence',new:'Y'}],
    [{old:'## Repeat',new:'# Section'}],
    [{old:'Evidence B',new:'Evidence B\n## Inserted slide\nMore'}],
    [{old:'Evidence B',new:'::: notes\nEvidence B'}],
    [{old:'Evidence B',new:'```\nEvidence B'}],
    [{old:'\n## Last',new:'\n## Other'}],
    [{old:'',new:'X'}], [{old:'Evidence B',new:'\0'}], [],
  ]) assert.throws(() => patchSlide(source,2,changes),undefined,JSON.stringify(changes));
});

test('replacements are applied to one snapshot, regardless of their order', () => {
  const result = patchSlide(source,2,[{old:'Evidence B',new:'Second claim'},{old:'Second claim',new:'A stronger claim'}]);
  assert.equal(result.text,source.replace('### Second claim','### A stronger claim').replace('Evidence B','Second claim'));
});

test('Org, CRLF, Unicode, notes and attributes survive scoped edits', () => {
  const org = '#+title: Plan\r\n* Area\r\n** Same\r\n*** Claim\r\nEvidence A\r\n** Same\r\n:PROPERTIES:\r\n:CUSTOM_ID: stable\r\n:END:\r\nEvidence B\r\n#+begin_notes\r\nPrivate detail\r\n#+end_notes\r\n';
  assert.equal(patchSlide(org,2,edit,true).text,org.replace('Evidence B','Updated evidence B'));
  const markdown = '## Title {#stable}\r\n### Claim\r\nEvidence B\r\n';
  assert.equal(patchSlide(markdown,1,[{old:'Evidence B',new:'\u05e9\u05dc\u05d5\u05dd'}]).text,markdown.replace('Evidence B','\u05e9\u05dc\u05d5\u05dd'));
});

test('unfinished sources, missing slides and oversized edits are bounded', t => {
  const {file,api} = fixture(t);
  for (const slide of [0,-1,1.5,4]) assert.throws(() => api.read(file,slide),/existing slide/);
  assert.throws(() => patchSlide(source,2,[{old:'Evidence B',new:'x'.repeat(MAX_SLIDE)}]),/64 KiB/);
  assert.throws(() => patchSlide(source,2,Array(33).fill(edit[0])),/32 exact/);
  fs.writeFileSync(file,'## A\n::: notes\nUnclosed');
  assert.throws(() => api.read(file,1),/unfinished/);
  fs.writeFileSync(file,'## A\n```js\nUnclosed');
  assert.throws(() => api.read(file,1),/unfinished code/);
  fs.writeFileSync(file,'## A\nBody\n');
  const snapshot = api.read(file,1);
  assert.throws(() => api.edit(snapshot.edit_id,[{old:'Body',new:'```js\nBody'}]),/unfinished code/);
  assert.equal(fs.readFileSync(file,'utf8'),'## A\nBody\n');
  fs.writeFileSync(file,'## A\n'+'x'.repeat(MAX_SLIDE));
  assert.throws(() => api.read(file,1),/64 KiB/);
});

test('edit snapshots are bounded, expire and cannot target another file', t => {
  let now = 0;
  const {file,folder,api} = fixture(t,{now:() => now});
  const snapshot = api.read(file,2);
  for (let i=1;i<128;i++) api.read(file,2);
  assert.throws(() => api.read(file,2),/Too many pending/);
  now = 600000;
  assert.throws(() => api.edit(snapshot.edit_id,edit),/expired/);
  const other = path.join(folder,'other.md'); fs.writeFileSync(other,source);
  assert.equal(api.edit(api.read(other,2).edit_id,edit).outcome,'saved');
  assert.equal(fs.readFileSync(file,'utf8'),source);
  assert.equal(api.snapshots.size,0);
});

test('deleted sources and replaced symlinks never cause a new file or unexpected target write', t => {
  const {file,folder,api} = fixture(t), snapshot = api.read(file,2);
  fs.unlinkSync(file);
  assert.throws(() => api.edit(snapshot.edit_id,edit),/ENOENT|no longer/);
  assert.equal(fs.existsSync(file),false);
  const other = path.join(folder,'other.md'); fs.writeFileSync(other,source);
  fs.symlinkSync(other,file);
  assert.throws(() => api.edit(snapshot.edit_id,edit),/path changed/);
  assert.equal(fs.readFileSync(other,'utf8'),source);
});

test('read-only documents use the existing save refusal', t => {
  const {file,api} = fixture(t), snapshot = api.read(file,2);
  api.save = () => ({outcome:'read-only'});
  assert.equal(api.edit(snapshot.edit_id,edit).outcome,'read-only');
  assert.equal(fs.readFileSync(file,'utf8'),source);
});

test('reads and edits across many documents never consume viewer sessions', t => {
  const {file,folder,store,api} = fixture(t);
  const viewer = store.open(file);
  for (let i=0;i<70;i++) {
    const other = path.join(folder,`deck-${i}.md`);
    fs.writeFileSync(other,'No slide headings.');
    assert.throws(() => api.read(other,1),/existing slide/);
    fs.writeFileSync(other,source);
    assert.equal(api.edit(api.read(other,2).edit_id,edit).outcome,'saved');
  }
  assert.equal(store.sessions.size,1);
  assert.equal(api.snapshots.size,0);
  assert.equal(store.source(viewer.session).text,source);
});
