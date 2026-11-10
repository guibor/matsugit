import {build} from 'esbuild';
import {mkdir, readFile, writeFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {gzipSync} from 'node:zlib';
import {collectNotices} from './notices.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(root, 'bundle');
await mkdir(out, {recursive: true});
const story = await build({entryPoints:[path.join(root,'src/story-cli.mjs')], bundle:true,
  outfile:path.join(out,'story-cli.mjs'), platform:'node',format:'esm',target:'node22',legalComments:'inline',metafile:true});
const templates = execFileSync(process.env.MATSUGIT_PYTHON || process.env.FOLIOFORGE_PYTHON || 'python3', ['-c',
  'import json; from matsugit.authoring import editor_templates; print(json.dumps(editor_templates()))'],
  {cwd: path.dirname(root), encoding: 'utf8'});
const browser = await build({entryPoints: [path.join(root, 'src/app.js')], bundle: true,
  write: false, minify: true, format: 'iife', target: 'es2022', legalComments: 'inline', metafile: true,
  define: {__MATSUGIT_TEMPLATES__: templates}});
const html = await readFile(path.join(root, 'src/index.html'), 'utf8');
const css = await readFile(path.join(root, 'src/style.css'), 'utf8');
const hostCss = await readFile(fileURLToPath(import.meta.resolve('@openai/mcp-extensions/app/styles.css')), 'utf8');
const app = html.replace('/* APP_STYLES */', () => hostCss + '\n' + css)
  .replace('/* APP_SCRIPT */', () => browser.outputFiles[0].text.replaceAll('</script', '<\\/script'));
await writeFile(path.join(out, 'app.html'), app);
// Freeze the UI, Python modules and renderer assets into this server version.
// Codex may replace its installed cache while the process still serves viewers.
const files = {};
async function include(relative) {
  files[relative] = (await readFile(path.join(root, '..', relative))).toString('base64');
}
async function includeTree(relative) {
  for (const item of (await readdir(path.join(root, '..', relative), {withFileTypes: true})).sort((a, b) => a.name.localeCompare(b.name))) {
    const name = relative + '/' + item.name;
    if (item.isDirectory()) await includeTree(name);
    else if (item.isFile()) await include(name);
    else throw Error('Unexpected renderer asset: ' + name);
  }
}
await include('codex-plugin/worker.py');
await include('codex-plugin/actions.py');
for (const name of (await readdir(path.join(root, '../matsugit'))).sort().filter(name => name.endsWith('.py'))) {
  await include('matsugit/' + name);
}
await includeTree('matsugit/runtime');
await includeTree('matsugit/diagram_runtime');
await includeTree('matsugit/themes/default');
const packed = gzipSync(JSON.stringify({app, files}));
// The gzip header records the building OS (byte 9). Pin it so a build on macOS
// and on Linux produce the same committed bundle.
packed[9] = 3;
const runtime = packed.toString('base64');
const mergeWorker = await build({entryPoints: [path.join(root, 'src/merge-worker.mjs')], bundle: true,
  write: false, platform: 'node', format: 'cjs', target: 'node22', legalComments: 'inline', metafile: true});
const server = await build({entryPoints: [path.join(root, 'src/server.mjs')], bundle: true,
  outfile: path.join(out, 'server.mjs'), platform: 'node', format: 'esm', target: 'node22',
  define: {__MATSUGIT_RUNTIME__: JSON.stringify(runtime), __MATSUGIT_MERGE_WORKER__: JSON.stringify(mergeWorker.outputFiles[0].text)},
  legalComments: 'inline', metafile: true, banner: {js: "import {createRequire as __createRequire} from 'node:module'; const require = __createRequire(import.meta.url);"}});
await writeFile(path.join(out, 'THIRD-PARTY-NOTICES.txt'),
  await collectNotices([browser.metafile, server.metafile, mergeWorker.metafile, story.metafile]));
