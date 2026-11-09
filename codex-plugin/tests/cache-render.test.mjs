import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';

const root = fileURLToPath(new URL('../../', import.meta.url));
test('real renderer survives cache removal and keeps save/conflict and incremental previews',
  {skip: !process.env.QUARTO, timeout: 180000}, async () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-cache-render-'));
    const installed = path.join(directory, 'plugin/codex-plugin/bundle');
    fs.mkdirSync(installed, {recursive: true});
    fs.copyFileSync(path.join(root, 'codex-plugin/bundle/server.mjs'), path.join(installed, 'server.mjs'));
    const file = path.join(directory, 'document.md'), config = path.join(directory, 'config.json');
    const original = '---\ntitle: Synthetic cache test\nslide-layout: structured\n---\n\n# Section\n\n## Evidence\n\nBefore the update.\n';
    fs.writeFileSync(file, original); fs.writeFileSync(config, '{}');
    const client = new Client({name: 'cache-removal-test', version: '1.0.0'});
    const transport = new StdioClientTransport({command: process.execPath,
      args: [path.join(installed, 'server.mjs')], cwd: directory,
      env: {...process.env, MATSUGIT_CONFIG: config, MATSUGIT_DEFAULT_THEME: 'default',
        MATSUGIT_THEMES_DIR: path.join(directory, 'no-themes'), MATSUGIT_PYTHON: 'python3'}, stderr: 'pipe'});
    async function call(name, args) {
      const result = await client.callTool({name, arguments: args});
      assert.equal(result.isError, undefined, JSON.stringify(result));
      return result;
    }
    try {
      await client.connect(transport);
      const opened = (await call('matsugit_open', {path: file})).structuredContent;
      const {session, etag} = opened;
      const first = (await call('matsugit_preview', {session, text: original})).structuredContent.job;
      // The worker has started; cache replacement must not break its imports/assets.
      fs.rmSync(path.join(directory, 'plugin'), {recursive: true});
      assert.match((await client.readResource({uri: 'ui://matsugit/workspace-v1'})).contents[0].text, /Markdown/);
      async function ready(job) {
        for (let i = 0; i < 1200; i++) {
          const status = (await call('matsugit_preview_status', {session, job})).structuredContent;
          if (status.state !== 'rendering') { assert.equal(status.state, 'ready', status.error); return status; }
          await delay(100);
        }
        throw Error('Render did not finish');
      }
      assert.equal((await ready(first)).kind, 'full');
      const html = await call('matsugit_preview_chunk', {session, job: first, format: 'document', offset: 0});
      assert.match(html.structuredContent.chunk, /<!DOCTYPE html>/i);
      const changed = original.replace('Before the update.', 'After the update.');
      const second = (await call('matsugit_preview', {session, text: changed, base: first})).structuredContent.job;
      assert.equal((await ready(second)).kind, 'patch');
      const patch = await call('matsugit_preview_chunk', {session, job: second, format: 'document', offset: 0});
      assert.match(patch.structuredContent.chunk, /After the update/);
      const slides = (await call('matsugit_preview', {session, text: changed, format: 'slides'})).structuredContent.job;
      assert.equal((await ready(slides)).kind, 'full');
      assert.equal(fs.readFileSync(file, 'utf8'), original);
      assert.equal((await call('matsugit_save', {session, etag, text: changed})).structuredContent.outcome, 'saved');
      assert.equal((await call('matsugit_save', {session, etag, text: 'stale'})).structuredContent.outcome, 'conflict');
      assert.equal(fs.readFileSync(file, 'utf8'), changed);
    } finally { await client.close(); fs.rmSync(directory, {recursive: true, force: true}); }
  });
