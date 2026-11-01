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

for (const saved of [false, true]) {
  test(`preview and UI survive removed cwd and plugin cache (${saved ? 'selected file' : 'unsaved draft'})`,
    {skip: process.platform === 'win32', timeout: 20000}, async () => {
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'folioforge-cwd-test-'));
      const inherited = path.join(directory, 'removed-cwd');
      const shim = path.join(directory, 'python-shim');
      const worker = path.join(directory, 'worker.mjs');
      const source = path.join(directory, 'deck.md');
      const installed = path.join(directory, 'plugin/codex-plugin/bundle');
      fs.mkdirSync(installed, {recursive: true});
      fs.copyFileSync(path.join(root, 'codex-plugin/bundle/server.mjs'), path.join(installed, 'server.mjs'));
      fs.mkdirSync(inherited);
      fs.writeFileSync(source, '# Original\n');
      // Like pyenv, the shell wrapper needs a real cwd before Python can start.
      fs.writeFileSync(shim, `#!/bin/bash
set -eu
if ! here="$(pwd -P)"; then
  printf "pyenv: cannot change working directory to empty path\\n" >&2
  exit 1
fi
test "$here" = "$PWD"
exec "$FOLIOFORGE_TEST_NODE" "$FOLIOFORGE_TEST_WORKER" "$@"
`, {mode: 0o700});
      fs.writeFileSync(worker, `import fs from 'node:fs';
import path from 'node:path';
let input = ''; for await (const part of process.stdin) input += part;
const request = JSON.parse(input);
fs.accessSync(process.argv[2]);
for (const file of ['core.py', 'preview.py', 'runtime/layout.css', 'themes/default/theme.json']) {
  fs.accessSync(path.join(path.dirname(process.argv[2]), '../folioforge', file));
}
fs.mkdirSync(request.output, {recursive: true});
const output = JSON.stringify({cwd: process.cwd(), pwd: process.env.PWD, output: request.output, source: request.path, worker: process.argv[2]});
for (const name of ['index.html', 'slides.html']) fs.writeFileSync(request.output + '/' + name, output);
console.log(JSON.stringify({theme: 'default'}));
`);
      const client = new Client({name: 'folioforge-cwd-test', version: '1.0.0'});
      const transport = new StdioClientTransport({command: process.execPath,
        args: [path.join(installed, 'server.mjs')], cwd: inherited,
        env: {...process.env, PWD: inherited, FOLIOFORGE_PYTHON: shim,
          FOLIOFORGE_TEST_NODE: process.execPath, FOLIOFORGE_TEST_WORKER: worker}, stderr: 'pipe'});
      try {
        await client.connect(transport);
        const before = await client.readResource({uri: 'ui://folioforge/workspace-v1'});
        const session = saved ? (await client.callTool({name: 'folioforge_open', arguments: {path: source}})).structuredContent.session : undefined;
        fs.rmdirSync(inherited);
        fs.rmSync(path.join(directory, 'plugin'), {recursive: true});
        const after = await client.readResource({uri: 'ui://folioforge/workspace-v1'});
        assert.equal(after.contents[0].text, before.contents[0].text);
        const start = await client.callTool({name: 'folioforge_preview', arguments: {text: '# Draft\n', session}});
        assert.equal(start.isError, undefined, JSON.stringify(start));
        const job = start.structuredContent.job;
        let status;
        for (let attempt = 0; attempt < 100; attempt++) {
          status = (await client.callTool({name: 'folioforge_preview_status', arguments: {job, session}})).structuredContent;
          if (status.state !== 'rendering') break;
          await delay(50);
        }
        assert.equal(status.state, 'ready', status.error);
        const result = await client.callTool({name: 'folioforge_preview_chunk', arguments: {job, session, format: 'document', offset: 0}});
        const rendered = JSON.parse(result._meta.chunk);
        assert.equal(rendered.cwd, fs.realpathSync(path.dirname(rendered.output)));
        assert.equal(rendered.pwd, rendered.cwd);
        const snapshot = path.resolve(path.dirname(rendered.worker), '..');
        const checkFile = name => assert.ok(fs.readFileSync(path.join(snapshot, name)).equals(fs.readFileSync(path.join(root, name))),
          'Bundled runtime is stale; run npm run build: ' + name);
        checkFile('codex-plugin/worker.py');
        for (const name of fs.readdirSync(path.join(root, 'folioforge')).filter(name => name.endsWith('.py'))) checkFile('folioforge/' + name);
        for (const assetRoot of ['folioforge/runtime', 'folioforge/themes/default']) {
          for (const name of fs.readdirSync(path.join(root, assetRoot), {recursive: true})) {
            if (fs.statSync(path.join(root, assetRoot, name)).isFile()) checkFile(assetRoot + '/' + name);
          }
        }
        if (saved) assert.equal(rendered.source, fs.realpathSync(source));
        assert.equal(fs.readFileSync(source, 'utf8'), '# Original\n');
      } finally {
        await client.close();
        fs.rmSync(directory, {recursive: true, force: true});
      }
    });
}
