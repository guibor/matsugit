import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';

const bundle = fileURLToPath(new URL('../bundle/server.mjs', import.meta.url));
test('recovery MCP survives process restart, scopes files and preserves current disk content', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-recovery-protocol-'));
  const file = path.join(directory, 'deck.md'), second = path.join(directory, 'other.org');
  fs.writeFileSync(file, '# Original\n'); fs.writeFileSync(second, '* Other');
  let client;
  const start = async () => {
    client = new Client({name: 'recovery-test', version: '1'});
    await client.connect(new StdioClientTransport({command: process.execPath, args: [bundle],
      env: {...process.env, MATSUGIT_RECOVERY_DIR: path.join(directory, 'recovery')}, stderr: 'pipe'}));
  };
  const call = async (name, args = {}, host) => client.callTool({name: 'matsugit_' + name, arguments: args,
    ...(host ? {_meta: {'openai/resource': {path: host}}} : {})});
  const ok = result => { assert.notEqual(result.isError, true, JSON.stringify(result)); return {...result.structuredContent, ...result._meta}; };
  try {
    await start();
    const {tools} = await client.listTools();
    for (const tool of tools.filter(t => t.name.startsWith('matsugit_recovery_'))) assert.deepEqual(tool._meta.ui.visibility, ['app']);
    const opened = ok(await call('open', {path: file})), {session} = opened;
    const {id} = ok(await call('recovery_begin', {session, name: 'deck.md'}));
    ok(await call('recovery_checkpoint', {session, id, generation: 1, text: '# Private draft\nשלום', base: '# Original\n', view: {format: 'slides'}}));
    const listed = await call('recovery_list', {session});
    assert.equal(listed._meta.items.length, 1);
    assert.doesNotMatch(JSON.stringify(listed.content), /Private draft|deck.md|Original/);
    const other = ok(await call('open', {path: second}));
    assert.equal((await call('recovery_restore', {session: other.session, id})).isError, true);
    assert.equal((await call('recovery_forget', {session: other.session, id, token: listed._meta.items[0].token})).isError, true);
    const unnamed = ok(await call('recovery_begin', {name: 'Untitled.md'}, file));
    ok(await call('recovery_checkpoint', {id: unnamed.id, generation: 1, text: 'unnamed', base: '', view: {}}, file));
    assert.equal(ok(await call('recovery_restore', {id: unnamed.id}, file)).recovery.owner, null);
    await client.close();
    fs.writeFileSync(file, '# External edit\n');
    await start();
    const restored = ok(await call('recovery_restore', {id}));
    assert.equal(restored.workspace.text, '# External edit\n');
    assert.equal(restored.recovery.base, '# Original\n');
    assert.equal(restored.recovery.text, '# Private draft\nשלום');
    assert.equal(restored.recovery.view.format, 'slides');
    assert.equal((await call('recovery_restore', {session, id})).isError, true, 'old process sessions expire');
    const refused = ok(await call('save', {session: restored.workspace.session, etag: opened.etag, text: restored.recovery.text}));
    assert.equal(refused.outcome, 'conflict');
    assert.equal(fs.readFileSync(file, 'utf8'), '# External edit\n');
    fs.unlinkSync(file);
    const missing = ok(await call('recovery_restore', {id}));
    assert.equal(missing.workspace.writable, false);
    assert.equal(missing.workspace.missingSource, true);
    assert.equal(missing.recovery.text, restored.recovery.text);
    const scope = {session: restored.workspace.session};
    const writer = ok(await call('recovery_begin', {...scope, name: 'deck.md'}));
    ok(await call('recovery_checkpoint', {...scope, id: writer.id, generation: 1, text: 'still protected', base: '', view: {}}));
  } finally { await client?.close(); fs.rmSync(directory, {recursive: true, force: true}); }
});
