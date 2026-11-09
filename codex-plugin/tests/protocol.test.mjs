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
  const launch = path.join(directory, 'removed-launch');
  fs.mkdirSync(launch);
  fs.writeFileSync(file, '# Original\n');
  const client = new Client({name: 'matsugit-test', version: '1.0.0'});
  const transport = new StdioClientTransport({command: process.execPath, args: [path.join(root, 'codex-plugin/bundle/server.mjs')], cwd:launch, stderr: 'pipe'});
  let stderr = ''; transport.stderr?.on('data', part => stderr += part);
  client.onerror = error => { stderr += String(error); };
  try {
    await client.connect(transport);
    fs.rmdirSync(launch);
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
    const opened = await client.callTool({name: 'matsugit_open', arguments: {path: file, layout: 'split', format: 'slides', editor: 'visual'}});
    assert.equal(opened.isError, undefined, JSON.stringify(opened));
    assert.equal(opened._meta.source, '# Original\n');
    assert.equal(opened.structuredContent.text, undefined);
    assert.equal(opened.structuredContent.format, 'slides');
    assert.equal(opened.structuredContent.layout, 'split');
    assert.equal(opened.structuredContent.editor, 'visual');
    const story = await client.callTool({name:'matsugit_workspace',arguments:{layout:'story'}});
    assert.equal(story.isError,undefined,JSON.stringify(story));
    assert.equal(story.structuredContent.layout,'story');
    const {session, etag} = opened.structuredContent;
    const merge = await client.callTool({name:'matsugit_merge', arguments:{base:'A\n\nB\n', local:'Mine\n\nB\n', incoming:'A\n\nFile\n'}});
    assert.equal(merge.isError, undefined, JSON.stringify(merge));
    assert.equal(merge.structuredContent.merge.conflicts, 0);
    assert.equal(merge.structuredContent.merge.segments.map(s=>s.text).join(''), 'Mine\n\nFile\n');
    assert.deepEqual(tools.find(tool=>tool.name==='matsugit_merge')._meta.ui.visibility,['app']);
    assert.equal(fs.readFileSync(file,'utf8'), '# Original\n');
    fs.mkdirSync(path.join(directory, 'themes', 'alpha'), {recursive: true});
    fs.mkdirSync(path.join(directory, 'themes', 'beta'), {recursive: true});
    for (const name of ['alpha', 'beta']) fs.writeFileSync(path.join(directory, 'themes', name, 'theme.json'), '{"extends":"default"}');
    fs.writeFileSync(path.join(directory, 'matsugit.json'), JSON.stringify({theme: 'alpha', themes_dir: 'themes'}));
    const catalog = await client.callTool({name: 'matsugit_themes', arguments: {session}});
    assert.equal(catalog.isError, undefined, JSON.stringify(catalog));
    assert.deepEqual(catalog.structuredContent, {default: 'alpha', themes: ['alpha', 'beta', 'default']});
    assert.equal((await client.callTool({name: 'matsugit_themes', arguments: {session: 'expired'}})).isError, true);
    assert.deepEqual(tools.find(tool => tool.name === 'matsugit_themes')._meta.ui.visibility, ['app']);
    assert.equal(tools.find(tool => tool.name === 'matsugit_themes').annotations.readOnlyHint, true);
    const copied = await client.callTool({name:'matsugit_path',arguments:{session}});
    assert.equal(copied.structuredContent.path,fs.realpathSync(file));
    const hostThemes = await client.callTool({name: 'matsugit_themes', arguments: {}, _meta: {'openai/resource': {path: file}}});
    assert.deepEqual(hostThemes.structuredContent, catalog.structuredContent);
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
