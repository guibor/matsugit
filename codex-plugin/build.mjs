import {build} from 'esbuild';
import {mkdir, readFile, writeFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {gzipSync} from 'node:zlib';

const root = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(root, 'bundle');
await mkdir(out, {recursive: true});
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
await includeTree('matsugit/themes/default');
const runtime = gzipSync(JSON.stringify({app, files})).toString('base64');
const server = await build({entryPoints: [path.join(root, 'src/server.mjs')], bundle: true,
  outfile: path.join(out, 'server.mjs'), platform: 'node', format: 'esm', target: 'node22',
  define: {__MATSUGIT_RUNTIME__: JSON.stringify(runtime)},
  legalComments: 'inline', metafile: true, banner: {js: "import {createRequire as __createRequire} from 'node:module'; const require = __createRequire(import.meta.url);"}});
const packages = new Set();
for (const file of [...Object.keys(browser.metafile.inputs), ...Object.keys(server.metafile.inputs)]) {
  const parts = file.split('node_modules/');
  if (parts.length < 2) continue;
  const tail = parts.at(-1).split('/');
  const name = tail.slice(0, tail[0].startsWith('@') ? 2 : 1).join('/');
  packages.add(path.resolve(parts.slice(0, -1).join('node_modules/'), 'node_modules', name));
}
const notices = [];
for (const directory of [...packages].sort()) {
  const info = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
  notices.push(`${info.name} ${info.version} (${info.license || 'see notice'})`);
  for (const file of (await readdir(directory)).filter(file => /^(licen[sc]e|notice|copying)(\.|$)/i.test(file))) {
    notices.push(await readFile(path.join(directory, file), 'utf8'));
  }
}
await writeFile(path.join(out, 'THIRD-PARTY-NOTICES.txt'), notices.join('\n\n') + '\n');
