import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {checkDeck} from '../src/check.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const tour = fs.readFileSync(path.join(root, 'matsugit/templates/tour.md'), 'utf8');

test('the sample deck explains itself and has nothing to fix', () => {
  assert.deepEqual(checkDeck(tour), []);
  for (const words of ['Change this title', 'Add', 'Ask the agent', 'Story', 'Check', 'Present', 'Share', 'Turn my notes into a deck'])
    assert.ok(tour.includes(words), words);
  // No part of it needs optional setup (charts, D2) to render on a first run.
  assert.ok(!/\.chart|```d2|```mermaid|vega-lite/.test(tour));
});

test('first run: the sample is created once in the chosen folder and opened; the launcher shows it too', async () => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-tour-')));
  const client = new Client({name: 'matsugit-tour-test', version: '1.0.0'});
  await client.connect(new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')], stderr: 'pipe'}));
  try {
    const tool = (await client.listTools()).tools.find(item => item.name === 'matsugit_tour');
    assert.ok(tool && tool._meta.ui.resourceUri, 'matsugit_tour opens the workspace');
    assert.equal(tool.annotations.destructiveHint, false);
    const opened = await client.callTool({name: 'matsugit_tour', arguments: {directory}});
    assert.equal(opened.isError, undefined, JSON.stringify(opened.content));
    const file = path.join(directory, 'matsugit-tour.md');
    assert.equal(fs.readFileSync(file, 'utf8'), tour);
    assert.equal(opened.structuredContent.path, file);
    assert.equal(opened.structuredContent.layout, 'split');
    assert.equal(opened._meta.source, tour);
    // Someone's edits to the sample are never overwritten by running it again.
    fs.writeFileSync(file, '# My own version\n');
    const again = await client.callTool({name: 'matsugit_tour', arguments: {directory, layout: 'story'}});
    assert.equal(again._meta.source, '# My own version\n');
    assert.equal(again.structuredContent.layout, 'story');
    for (const bad of ['relative/folder', path.join(directory, 'missing')])
      assert.equal((await client.callTool({name: 'matsugit_tour', arguments: {directory: bad}})).isError, true, bad);
    // Opening the app with no file shows the sample as a scratch copy, not an empty template.
    const scratch = await client.callTool({name: 'matsugit_workspace', arguments: {}});
    assert.equal(scratch.structuredContent.text, tour);
    assert.equal(scratch.structuredContent.writable, false);
    assert.equal(scratch.structuredContent.format, 'slides');
  } finally { await client.close(); fs.rmSync(directory, {recursive: true, force: true}); }
});
