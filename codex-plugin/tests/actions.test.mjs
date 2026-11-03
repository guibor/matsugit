import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
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
