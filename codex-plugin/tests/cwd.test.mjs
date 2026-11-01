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
  test(`preview survives a removed inherited directory (${saved ? 'selected file' : 'unsaved draft'})`,
    {skip: process.platform === 'win32', timeout: 20000}, async () => {
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'folioforge-cwd-test-'));
      const inherited = path.join(directory, 'removed-cwd');
      const shim = path.join(directory, 'python-shim');
      const worker = path.join(directory, 'worker.mjs');
      const source = path.join(directory, 'deck.md');
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
let input = ''; for await (const part of process.stdin) input += part;
const request = JSON.parse(input);
fs.accessSync(process.argv[2]);
fs.mkdirSync(request.output, {recursive: true});
const output = JSON.stringify({cwd: process.cwd(), pwd: process.env.PWD, output: request.output, source: request.path});
for (const name of ['index.html', 'slides.html']) fs.writeFileSync(request.output + '/' + name, output);
console.log(JSON.stringify({theme: 'default'}));
`);
      const client = new Client({name: 'folioforge-cwd-test', version: '1.0.0'});
      const transport = new StdioClientTransport({command: process.execPath,
        args: [path.join(root, 'codex-plugin/bundle/server.mjs')], cwd: inherited,
        env: {...process.env, PWD: inherited, FOLIOFORGE_PYTHON: shim,
          FOLIOFORGE_TEST_NODE: process.execPath, FOLIOFORGE_TEST_WORKER: worker}, stderr: 'pipe'});
      try {
        await client.connect(transport);
        const session = saved ? (await client.callTool({name: 'folioforge_open', arguments: {path: source}})).structuredContent.session : undefined;
        fs.rmdirSync(inherited);
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
        if (saved) assert.equal(rendered.source, fs.realpathSync(source));
        assert.equal(fs.readFileSync(source, 'utf8'), '# Original\n');
      } finally {
        await client.close();
        fs.rmSync(directory, {recursive: true, force: true});
      }
    });
}
