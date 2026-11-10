import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';

const root = fileURLToPath(new URL('../../', import.meta.url));
test('agents get the same plain-language findings as the workspace, read-only', async () => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-check-')));
  const file = path.join(directory, 'deck.md');
  const source = '---\ntitle: T\nslide-layout: structured\n---\n\n## One\n\nFine.\n\n## Two\n\n:::: columns\n#### A\nx\n::::\n\n::: takaway\nDone.\n:::\n';
  fs.writeFileSync(file, source);
  const client = new Client({name: 'matsugit-check-test', version: '1.0.0'});
  await client.connect(new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')], stderr: 'pipe'}));
  try {
    const tool = (await client.listTools()).tools.find(item => item.name === 'matsugit_check');
    // Visible to the model (not app-only) and declared read-only.
    assert.equal(tool._meta?.ui, undefined);
    assert.equal(tool.annotations.readOnlyHint, true);
    const checked = await client.callTool({name: 'matsugit_check', arguments: {path: file}});
    assert.equal(checked.isError, undefined, JSON.stringify(checked));
    const data = checked.structuredContent;
    assert.deepEqual([data.problems, data.tips, data.label], [1, 1, '1 to fix']);
    assert.deepEqual(data.findings.map(item => [item.code, item.slide, item.title, item.line]),
      [['parts-count', 2, 'Two', 12], ['block-name', 2, 'Two', 17]]);
    assert.equal(data.findings[1].suggestedFix, 'Change to takeaway');
    assert.ok(data.findings.every(item => !('from' in item) && !('fix' in item)));
    assert.equal(fs.readFileSync(file, 'utf8'), source);
    const text = await client.callTool({name: 'matsugit_check', arguments: {text: '* S\n** A\n#+begin_columns\nx\n', format: 'org'}});
    assert.equal(text.structuredContent.findings[0].code, 'block-open');
    assert.deepEqual((await client.callTool({name: 'matsugit_check', arguments: {text: source.replace(/## Two[\s\S]*/, '')}})).structuredContent.findings, []);
    for (const args of [{}, {path: file, text: 'x'}, {path: 'relative.md'}, {path: path.join(directory, 'notes.txt')}])
      assert.equal((await client.callTool({name: 'matsugit_check', arguments: args})).isError, true, JSON.stringify(args));
  } finally {
    await client.close();
    fs.rmSync(directory, {recursive: true, force: true});
  }
});
