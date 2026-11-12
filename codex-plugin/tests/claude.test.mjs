import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {wantsBrowser, clientOf, UI_EXTENSION} from '../src/browser-launch.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));

test('only a known text-only host, or an explicit setting, sends the workspace to the browser', () => {
  const claudeCode = {info: {name: 'claude-code'}, capabilities: {roots: {}}};
  assert.equal(wantsBrowser(claudeCode, {}), true);
  // A host that renders MCP Apps keeps the panel, whatever its name.
  assert.equal(wantsBrowser({info: {name: 'claude-code'}, capabilities: {extensions: {[UI_EXTENSION]: {}}}}, {}), false);
  for (const name of ['Cursor', 'codex', 'claude-ai', 'Claude Desktop', ''])
    assert.equal(wantsBrowser({info: {name}, capabilities: {}}, {}), false, name);
  assert.equal(wantsBrowser({info: {name: 'Cursor'}}, {MATSUGIT_BROWSER: '1'}), true);
  assert.equal(wantsBrowser(claudeCode, {MATSUGIT_BROWSER: '0'}), false);
  // The 2026 protocol carries the client in each request's envelope.
  const envelope = {'io.modelcontextprotocol/clientInfo': {name: 'claude-code'}, 'io.modelcontextprotocol/clientCapabilities': {}};
  assert.equal(clientOf({}, {mcpReq: {envelope}}).info.name, 'claude-code');
  assert.equal(clientOf({server: {getClientVersion: () => ({name: 'x'}), getClientCapabilities: () => ({})}}, {}).info.name, 'x');
});

async function connect(name) {
  const client = new Client({name, version: '1.0.0'});
  await client.connect(new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')],
    env: {...process.env, MATSUGIT_BROWSER_OPEN: '0', MATSUGIT_BROWSER: '', MATSUGIT_BROWSER_UNUSED_MS: '15000'}, stderr: 'pipe'}));
  return client;
}

test('in Claude Code the open tools put the workspace in the browser and return its address', async () => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-claude-')));
  const deck = path.join(directory, 'deck.md');
  fs.writeFileSync(deck, '---\ntitle: Synthetic\n---\n\n## One\n\nText.\n');
  const client = await connect('claude-code');
  try {
    assert.ok((await client.listTools()).tools.some(tool => tool.name === 'matsugit_browser'));
    const opened = await client.callTool({name: 'matsugit_open', arguments: {path: deck}});
    assert.equal(opened.isError, undefined, JSON.stringify(opened.content));
    const data = opened.structuredContent;
    assert.equal(data.opened, 'browser');
    assert.equal(data.path, deck);
    assert.match(data.url, /^http:\/\/127\.0\.0\.1:\d+\/[\w-]{32}\/$/);
    assert.match(data.message, /cannot show the matsugit panel/);
    assert.equal((await fetch(data.url)).status, 200);
    // Opening the same file again reuses the running workspace.
    const again = (await client.callTool({name: 'matsugit_open', arguments: {path: deck}})).structuredContent;
    assert.equal(again.url, data.url);
    // The tour and the explicit browser tool take the same route.
    const tour = (await client.callTool({name: 'matsugit_tour', arguments: {directory}})).structuredContent;
    assert.equal(tour.opened, 'browser');
    assert.ok(fs.existsSync(path.join(directory, 'matsugit-tour.md')));
    const sample = (await client.callTool({name: 'matsugit_browser', arguments: {}})).structuredContent;
    assert.equal(sample.path, null);
    assert.equal(fs.readFileSync(deck, 'utf8'), '---\ntitle: Synthetic\n---\n\n## One\n\nText.\n');
  } finally {
    await client.close();
  }
  // The browser workspaces outlive the chat's server; with no tab they stop on their own (15 s here).
});

test('a panel host keeps the panel', async () => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-panel-')));
  const deck = path.join(directory, 'deck.md');
  fs.writeFileSync(deck, '## One\n');
  const client = await connect('Cursor');
  try {
    const opened = await client.callTool({name: 'matsugit_open', arguments: {path: deck}});
    assert.equal(opened.structuredContent.opened, undefined);
    assert.ok(opened.structuredContent.session);
    assert.equal(opened._meta.source, '## One\n');
  } finally {
    await client.close();
  }
});
