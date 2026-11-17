import {build} from '../codex-plugin/node_modules/esbuild/lib/main.js';
import {mkdir, copyFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root = path.dirname(fileURLToPath(import.meta.url));
await build({entryPoints: [path.join(root, 'extension.mjs')], outfile: path.join(root, 'dist/extension.cjs'),
  bundle: true, platform: 'node', format: 'cjs', target: 'node20', external: ['vscode'],
  nodePaths: [path.join(root, '../codex-plugin/node_modules')], legalComments: 'inline'});
await mkdir(path.join(root, 'runtime'), {recursive: true});
for (const name of ['server.mjs', 'THIRD-PARTY-NOTICES.txt'])
  await copyFile(path.join(root, '../codex-plugin/bundle', name), path.join(root, 'runtime', name));
await copyFile(path.join(root, '../LICENSE'), path.join(root, 'LICENSE'));
