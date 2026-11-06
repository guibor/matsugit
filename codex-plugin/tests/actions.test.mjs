import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {WorkspaceActions} from '../src/actions.mjs';

test('action ownership, plan requirement and optional setup use local worker', async () => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-actions-test-'));
  const old = process.env.MATSUGIT_CONFIG;
  process.env.MATSUGIT_CONFIG = path.join(directory,'absent.json');
  const actions = new WorkspaceActions({root:() => root}, {owner:session => session || null});
  try {
    assert.throws(() => actions.start({action:'publish', session:'/test/deck.md', text:'draft'}), /Review/);
    assert.throws(() => actions.start({action:'plan', text:'draft'}), /local source/);
    const {job} = actions.start({action:'options', session:path.join(directory,'deck.md')});
    assert.throws(() => actions.status(job, '/other.md'), /Unknown operation/);
    let status;
    for (let i=0;i<100;i++) {
      status = actions.status(job,path.join(directory,'deck.md'));
      if (status.state !== 'running') break;
      await new Promise(resolve => setTimeout(resolve,50));
    }
    assert.equal(status.state, 'ready', JSON.stringify(status));
    assert.deepEqual(status.result.targets, {});
    assert.throws(() => actions.chunk(job,0,path.join(directory,'deck.md')), /Invalid export/);
  } finally {
    actions.close(); fs.rmSync(directory,{recursive:true,force:true});
    if (old === undefined) delete process.env.MATSUGIT_CONFIG; else process.env.MATSUGIT_CONFIG = old;
  }
});

test('repeated Git checks replace old reviews without exhausting jobs or losing downloads', async () => {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-sync-retry-'));
  const repo = path.join(directory, 'repo'), remote = path.join(directory, 'remote.git');
  fs.mkdirSync(repo);
  const git = (at, ...args) => execFileSync('git', ['-C', at, ...args], {stdio:'pipe'});
  git(directory, 'init', '--bare', '--initial-branch=main', remote);
  git(repo, 'init', '-b', 'main'); git(repo, 'config', 'user.name', 'Test'); git(repo, 'config', 'user.email', 'test@example.invalid');
  const source = path.join(repo, 'deck.md'), other = path.join(repo, 'other.md');
  fs.writeFileSync(source, '# Base\n'); fs.writeFileSync(other, '# Other\n');
  git(repo, 'add', '.'); git(repo, 'commit', '-m', 'Base'); git(repo, 'remote', 'add', 'origin', remote); git(repo, 'push', '-u', 'origin', 'main');
  const actions = new WorkspaceActions({root:() => root}, {owner:session => session});
  const check = async owner => {
    const result = actions.start({action:'sync-plan', session:owner});
    let status;
    for (let i=0; i<300; i++) {
      status = actions.status(result.job, owner);
      if (status.state !== 'running') break;
      await new Promise(resolve => setTimeout(resolve,20));
    }
    assert.equal(status.state, 'ready', JSON.stringify(status));
    return result.job;
  };
  try {
    const download = fs.mkdtempSync(path.join(directory, 'download-'));
    fs.writeFileSync(path.join(download, 'deck.txt'), 'Retain export');
    actions.jobs.set('download', {state:'ready', file:path.join(download, 'deck.txt'), directory:download, owner:source});
    const otherPlan = await check(other);
    let previous, last;
    for (let i=0; i<30; i++) {
      last = await check(source);
      if (previous) {
        assert.equal(actions.jobs.has(previous), false);
        assert.throws(() => actions.start({action:'sync', session:source, plan:previous, text:'# Base\n'}), /Review/);
      }
      previous = last;
    }
    assert.equal(actions.jobs.size, 3);
    assert.equal(actions.plans.size, 2);
    assert.equal(actions.plans.has(otherPlan), true);
    assert.equal(actions.plans.has(last), true);
    assert.equal(fs.readFileSync(path.join(download, 'deck.txt'), 'utf8'), 'Retain export');
  } finally { actions.close(); fs.rmSync(directory, {recursive:true, force:true}); }
});
