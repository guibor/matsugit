import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';

const root = fileURLToPath(new URL('../../', import.meta.url));
test('portable, Codex compatibility and workspace release versions agree', () => {
  const manifests = ['plugin.json', '.codex-plugin/plugin.json', '.cursor-plugin/plugin.json', 'codex-plugin/package.json']
    .map(name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8')));
  assert.equal(new Set(manifests.map(manifest => manifest.version)).size, 1);
});
test('built plugin initializes and exposes the app, file handler and versioned file operations', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-protocol-'));
  const file = path.join(directory, 'deck.md');
  fs.writeFileSync(file, '# Original\n');
  const client = new Client({name: 'matsugit-test', version: '1.0.0'});
  const transport = new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')], stderr: 'pipe'});
  let stderr = ''; transport.stderr?.on('data', part => stderr += part);
  client.onerror = error => { stderr += String(error); };
  try {
    await client.connect(transport);
    assert.equal(client.getServerVersion().version,
      JSON.parse(fs.readFileSync(path.join(root, 'plugin.json'), 'utf8')).version);
    const {tools} = await client.listTools();
    const handler = tools.find(tool => tool.name === 'matsugit_file');
    assert.deepEqual(handler._meta['openai/ui'].entrypoints[0].extensions, ['.md', '.markdown', '.qmd', '.org']);
    assert.deepEqual(tools.find(tool => tool.name === 'matsugit_save')._meta.ui.visibility, ['app']);
    assert.deepEqual(tools.find(tool => tool.name === 'matsugit_preview_cancel')._meta.ui.visibility, ['app']);
    const app = await client.readResource({uri: 'ui://matsugit/workspace-v1'});
    assert.match(app.contents[0].text, /Markdown/);
    assert.equal(app.contents[0].text, fs.readFileSync(path.join(root, 'codex-plugin/bundle/app.html'), 'utf8'));
    assert.equal(app.contents[0].mimeType, 'text/html;profile=mcp-app');
    const opened = await client.callTool({name: 'matsugit_open', arguments: {path: file, layout: 'split', format: 'slides'}});
    assert.equal(opened.isError, undefined, JSON.stringify(opened));
    assert.equal(opened._meta.source, '# Original\n');
    assert.equal(opened.structuredContent.text, undefined);
    assert.equal(opened.structuredContent.format, 'slides');
    assert.equal(opened.structuredContent.layout, 'split');
    const {session, etag} = opened.structuredContent;
    const copied = await client.callTool({name:'matsugit_path',arguments:{session}});
    assert.equal(copied.structuredContent.path,fs.realpathSync(file));
    assert.equal((await client.callTool({name:'matsugit_path',arguments:{}})).structuredContent.path,null);
    assert.equal((await client.callTool({name:'matsugit_path',arguments:{session:'not-opened'}})).isError,true);
    for (const name of ['matsugit_path','matsugit_table'])
      assert.deepEqual(tools.find(tool=>tool.name===name)._meta.ui.visibility,['app']);
    const saved = await client.callTool({name: 'matsugit_save', arguments: {session, etag, text: '# Saved\n'}});
    assert.equal(saved.structuredContent.outcome, 'saved');
    const stale = await client.callTool({name: 'matsugit_save', arguments: {session, etag, text: '# Stale\n'}});
    assert.equal(stale.structuredContent.outcome, 'conflict');
    assert.equal(fs.readFileSync(file, 'utf8'), '# Saved\n');
    const invalid = await client.callTool({name: 'matsugit_open', arguments: {path: '../bad.md'}});
    assert.equal(invalid.isError, true);
  } catch (error) {
    throw new Error(`${error.message}\n${stderr}`, {cause: error});
  } finally {
    await client.close(); fs.rmSync(directory, {recursive: true, force: true});
  }
  assert.doesNotMatch(stderr, /SyntaxError|ERR_MODULE/);
});
