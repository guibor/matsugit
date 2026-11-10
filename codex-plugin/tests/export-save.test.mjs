import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {WorkspaceActions} from '../src/actions.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-local-export-'));
  t.after(() => fs.rmSync(root, {recursive:true, force:true}));
  const downloads = path.join(root, 'Downloads'), file = path.join(root, 'prepared.pdf');
  const bytes = Buffer.from('%PDF-1.7\nSynthetic export\n\u0000\u00ff');
  fs.writeFileSync(file, bytes);
  const actions = new WorkspaceActions(null, {owner:session => session}, downloads);
  actions.jobs.set('job', {action:'export',state:'ready',owner:'doc',file,size:bytes.length,
    exportName:actions.exportName('source.md','pdf')});
  return {root,downloads,file,bytes,actions};
}

test('explicit save creates exact private bytes and returns the real path; repeat is idempotent', t => {
  const {downloads,bytes,actions} = fixture(t);
  assert.equal(fs.existsSync(downloads), false);
  const saved = actions.saveExport('job','doc');
  assert.equal(saved.path,path.join(downloads,'source.pdf'));
  assert.equal(saved.host,os.hostname()); assert.equal(saved.size,bytes.length);
  assert.deepEqual(fs.readFileSync(saved.path),bytes);
  assert.equal(fs.statSync(saved.path).mode & 0o777,0o600);
  assert.deepEqual(actions.saveExport('job','doc'),saved);
  assert.deepEqual(fs.readdirSync(downloads),['source.pdf']);
});

test('collisions and changed prior exports are retained, never overwritten', t => {
  const {downloads,bytes,actions} = fixture(t);
  fs.mkdirSync(downloads); fs.writeFileSync(path.join(downloads,'source.pdf'),'Existing PDF');
  const first = actions.saveExport('job','doc');
  assert.equal(path.basename(first.path),'source (1).pdf');
  fs.writeFileSync(first.path,'External edit');
  const second = actions.saveExport('job','doc');
  assert.equal(path.basename(second.path),'source (2).pdf');
  assert.equal(fs.readFileSync(first.path,'utf8'),'External edit');
  assert.equal(fs.readFileSync(path.join(downloads,'source.pdf'),'utf8'),'Existing PDF');
  assert.deepEqual(fs.readFileSync(second.path),bytes);
});

test('only a ready export belonging to this document can be saved', t => {
  const {downloads,actions} = fixture(t);
  assert.throws(()=>actions.saveExport('job','other'),/Unknown operation/);
  assert.throws(()=>actions.saveExport('missing','doc'),/Unknown operation/);
  actions.jobs.get('job').state='running';
  assert.throws(()=>actions.saveExport('job','doc'),/Prepare an export/);
  actions.jobs.get('job').state='ready'; actions.jobs.get('job').action='plan';
  assert.throws(()=>actions.saveExport('job','doc'),/Prepare an export/);
  assert.equal(fs.existsSync(downloads),false);
});

test('Downloads symlinks are refused, file symlinks are never followed', t => {
  const {root,downloads,actions} = fixture(t);
  const elsewhere=path.join(root,'elsewhere'); fs.mkdirSync(elsewhere);
  fs.symlinkSync(elsewhere,downloads);
  assert.throws(()=>actions.saveExport('job','doc'),/symlink/);
  assert.deepEqual(fs.readdirSync(elsewhere),[]);
  fs.unlinkSync(downloads); fs.mkdirSync(downloads);
  const target=path.join(elsewhere,'important.pdf'); fs.writeFileSync(target,'Keep');
  fs.symlinkSync(target,path.join(downloads,'source.pdf'));
  assert.equal(path.basename(actions.saveExport('job','doc').path),'source (1).pdf');
  assert.equal(fs.readFileSync(target,'utf8'),'Keep');
});

test('changed prepared data leaves no partial final file and can be retried', t => {
  const {downloads,file,bytes,actions} = fixture(t);
  fs.writeFileSync(file,'Changed');
  assert.throws(()=>actions.saveExport('job','doc'),/Prepared export changed/);
  assert.deepEqual(fs.readdirSync(downloads),[]);
  fs.writeFileSync(file,bytes);
  assert.deepEqual(fs.readFileSync(actions.saveExport('job','doc').path),bytes);
});

test('export names cannot escape Downloads and long Unicode names fit a filesystem component', t => {
  const {downloads,actions} = fixture(t);
  assert.equal(actions.exportName('../../source.md','pdf'),'source.pdf');
  assert.equal(actions.exportName('C:\\private\\source.md','pdf'),'source.pdf');
  const name=actions.exportName('\u00e9'.repeat(300)+'.md','pdf');
  assert.ok(Buffer.byteLength(name)<=184);
  actions.jobs.get('job').exportName=name;
  assert.equal(path.dirname(actions.saveExport('job','doc').path),downloads);
});
