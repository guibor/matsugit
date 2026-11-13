import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {wantsBrowser, clientOf, UI_EXTENSION, openInBrowser} from '../src/browser-launch.mjs';

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

async function connect(name, environment = {}) {
  const client = new Client({name, version: '1.0.0'});
  await client.connect(new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')],
    env: {...process.env, MATSUGIT_BROWSER_OPEN: '0', MATSUGIT_BROWSER: '',
      MATSUGIT_BROWSER_IDLE_MS: '2000', MATSUGIT_BROWSER_UNUSED_MS: '5000', ...environment}, stderr: 'pipe'}));
  return client;
}

test('in Claude Code the open tools put the workspace in the browser and return its address', async () => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-claude-')));
  const deck = path.join(directory, 'deck.md');
  fs.writeFileSync(deck, '---\ntitle: Synthetic\n---\n\n## One\n\nText.\n');
  const client = await connect('claude-code');
  try {
    assert.ok((await client.listTools()).tools.some(tool => tool.name === 'matsugit_browser'));
    const options = {path: deck, layout: 'story', format: 'slides', editor: 'visual', autosave: false};
    const [opened, simultaneous] = await Promise.all([1, 2].map(() => client.callTool({name: 'matsugit_open', arguments: options})));
    assert.equal(opened.isError, undefined, JSON.stringify(opened.content));
    const data = opened.structuredContent;
    assert.equal(data.opened, 'browser');
    assert.equal(data.path, deck);
    assert.match(data.url, /^http:\/\/127\.0\.0\.1:\d+\/[\w-]{32}\/$/);
    assert.match(data.message, /browser workspace is ready/);
    assert.equal(simultaneous.structuredContent.url, data.url);
    assert.equal((await fetch(data.url)).status, 200);
    const page = await fetch(data.url + 'result', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}).then(r => r.json());
    assert.equal(page.structuredContent.layout, 'story');
    assert.equal(page.structuredContent.format, 'slides');
    assert.equal(page.structuredContent.autosave, false);
    assert.equal(page._meta.source, fs.readFileSync(deck, 'utf8'));
    // Opening the same file again reuses the running workspace.
    const again = (await client.callTool({name: 'matsugit_open', arguments: options})).structuredContent;
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
  fs.rmSync(directory, {recursive: true, force: true});
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
    fs.rmSync(directory, {recursive: true, force: true});
  }
});

test('forced browser mode does not recursively launch another workspace', async () => {
  const client = await connect('Cursor', {MATSUGIT_BROWSER: '1'});
  try {
    const opened = await client.callTool({name: 'matsugit_workspace', arguments: {layout: 'story'}});
    assert.equal(opened.isError, undefined, JSON.stringify(opened.content));
    const data = await fetch(opened.structuredContent.url + 'result', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}).then(r => r.json());
    assert.equal(data.structuredContent.opened, undefined);
    assert.equal(data.structuredContent.layout, 'story');
    assert.ok(data.structuredContent.text);
  } finally { await client.close(); }
});

test('failed browser startups are bounded and stopped, not left running', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-browser-failure-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  for (const [name, output, error] of [
    ['timeout', '', /did not start in time/],
    ['invalid-json', "process.stdout.write('not json\\n');", /JSON/],
    ['invalid-address', `console.log(JSON.stringify({url:'https://example.com/'}));`, /invalid local address/],
    ['large', `process.stdout.write('x'.repeat(65537));`, /size limit/],
    ['exit', 'process.exit(1);', /stopped before/],
  ]) await t.test(name, async () => {
    const script = path.join(directory, name + '.mjs'), pidFile = script + '.pid';
    fs.writeFileSync(script, `import fs from 'node:fs'; fs.writeFileSync(${JSON.stringify(pidFile)}, String(process.pid));\n${output}\nsetInterval(()=>{}, 1000);`);
    await assert.rejects(openInBrowser(script, {script, timeoutMs: 1000,
      env: {...process.env, MATSUGIT_BROWSER_OPEN: '0'}}), error);
    const pid = Number(fs.readFileSync(pidFile, 'utf8'));
    for (let i = 0; i < 100; i++) {
      try { process.kill(pid, 0); } catch { return; }
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    process.kill(pid, 'SIGKILL');
    assert.fail('Failed browser process was left running');
  });
});
