import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {WorkspaceStore} from '../src/store.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const temporary = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-move-')));

test('an open workspace follows only the move that was reviewed', () => {
  const directory = temporary();
  try {
    const original = path.join(directory, 'deck.md'), target = path.join(directory, 'repo-source.md'), other = path.join(directory, 'other.md');
    fs.writeFileSync(original, '# Deck\n'); fs.writeFileSync(other, '# Other\n');
    const store = new WorkspaceStore(directory), {session, etag} = store.open(original);
    const move = to => { fs.rmSync(original, {force: true}); if (to === target) fs.writeFileSync(target, '# Deck\n'); fs.symlinkSync(to, original); };
    // A symlink nobody reviewed is never followed.
    move(other);
    assert.throws(() => store.owner(session), /path changed/);
    store.expectRelocation(original, target);
    assert.throws(() => store.owner(session), /path changed/);
    // The reviewed destination is followed for reads, ownership and saves.
    move(target);
    assert.equal(store.owner(session), target);
    assert.equal(store.source(session).text, '# Deck\n');
    assert.equal(store.save(session, '# Deck, edited\n', etag).outcome, 'saved');
    assert.equal(fs.readFileSync(target, 'utf8'), '# Deck, edited\n');
    assert.ok(fs.lstatSync(original).isSymbolicLink());
    store.settleRelocation(original);
    assert.equal(store.relocated(original, target).path, target);
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
});

test('publishing with move keeps the session usable while the file moves, and reports the new path', {skip: process.platform === 'win32', timeout: 120000}, async () => {
  const directory = path.join(temporary(), 'target');
  const info = JSON.parse(execFileSync(process.env.MATSUGIT_PYTHON || 'python3', [path.join(root, 'codex-plugin/tests/publish-target.py'), directory], {encoding: 'utf8'}));
  const client = new Client({name: 'matsugit-move-test', version: '1.0.0'});
  await client.connect(new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')],
    env: {...process.env, MATSUGIT_CONFIG: info.config, GIT_SSH_COMMAND: info.ssh}, stderr: 'pipe'}));
  const call = async (name, args) => {
    const result = await client.callTool({name, arguments: args});
    assert.equal(result.isError, undefined, name + ': ' + JSON.stringify(result.content));
    return {...result.structuredContent, ...(result._meta || {})};
  };
  try {
    const opened = await call('matsugit_open', {path: info.source});
    const {session} = opened, text = opened.source;
    const run = async (action, args) => {
      let job = await call('matsugit_action', {session, action, text, name: 'Deck.md', target: 'docs', build: 'ci', move_source: true, ...args});
      while (job.state === 'running') {
        // Poll tightly, as the workspace does, across the instant the file moves.
        await new Promise(resolve => setTimeout(resolve, 20));
        job = await call('matsugit_action_status', {session, job: job.job});
        await call('matsugit_read', {session});
      }
      assert.equal(job.state, 'ready', job.error);
      return job;
    };
    const plan = await run('plan', {});
    assert.equal(plan.result.relocation.destination, info.destination);
    const published = await run('publish', {plan: plan.job});
    assert.match(published.result.status, /^Pushed/);
    assert.equal(published.workspace.path, info.destination);
    assert.equal(published.workspace.source ?? published.workspace.text, text);
    // The original session keeps working at the new path; the old place is a link.
    assert.equal((await call('matsugit_path', {session})).path, info.destination);
    assert.ok(fs.lstatSync(info.source).isSymbolicLink());
    assert.equal((await call('matsugit_save', {session, text: text + '\nMore.\n', etag: published.workspace.etag})).outcome, 'saved');
    assert.equal(fs.readFileSync(info.destination, 'utf8'), text + '\nMore.\n');
    const pushed = execFileSync('git', ['--git-dir', path.join(directory, 'remotes/team/docs.git'), 'show', 'main:matsugit-site/deck/source.md'], {encoding: 'utf8'});
    assert.equal(pushed, text);
  } finally { await client.close(); fs.rmSync(path.dirname(directory), {recursive: true, force: true}); }
});
