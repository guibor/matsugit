import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {hostPage, startServer} from '../src/browser.mjs';

test('browser host escapes filenames and keeps chat actions unavailable', () => {
  const page = hostPage('token', '<script>alert("title")</script>');
  assert.ok(page.includes('&lt;script&gt;'));
  assert.ok(!page.includes('<script>alert('));
  assert.ok(page.includes("event.source!==frame.contentWindow"));
  assert.ok(page.includes('Not available in the browser'));
});

test('failed child rejects startup and later requests instead of waiting', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'matsugit-browser-child-'));
  try {
    const script = path.join(directory, 'exit.mjs');
    await writeFile(script, 'process.exit(1);');
    const mcp = startServer(script);
    await assert.rejects(mcp.ready, /stopped/);
    await mcp.exited;
    await assert.rejects(mcp.request('tools/call', {}), /stopped/);
  } finally { await rm(directory, {recursive:true, force:true}); }
});
