import {build} from 'esbuild';
import {mkdir, readFile, writeFile, readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {brotliCompressSync, gunzipSync, constants} from 'node:zlib';
import {collectNotices} from './notices.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
// zod bundles error messages in dozens of languages (about 350 KB); nothing here
// uses any but English, which zod loads by default. Keep only that one. A library
// that imported another language by name would fail this build, not at runtime.
const englishZod = {name: 'zod-english-only', setup(builder) {
  builder.onLoad({filter: /[\\/]node_modules[\\/]zod[\\/]v4[\\/]locales[\\/]index\.js$/}, args =>
    ({contents: 'export { default as en } from "./en.js";\n', resolveDir: path.dirname(args.path), loader: 'js'}));
}};
const out = path.join(root, 'bundle');
await mkdir(out, {recursive: true});
const story = await build({entryPoints:[path.join(root,'src/story-cli.mjs')], bundle:true,
  outfile:path.join(out,'story-cli.mjs'), platform:'node',format:'esm',target:'node22',legalComments:'inline',metafile:true, plugins:[englishZod]});
const templates = execFileSync(process.env.MATSUGIT_PYTHON || process.env.FOLIOFORGE_PYTHON || 'python3', ['-c',
  'import json; from matsugit.authoring import editor_templates; print(json.dumps(editor_templates()))'],
  {cwd: path.dirname(root), encoding: 'utf8'});
const browser = await build({entryPoints: [path.join(root, 'src/app.js')], bundle: true,
  write: false, minify: true, format: 'iife', target: 'es2022', legalComments: 'inline', metafile: true, plugins: [englishZod],
  define: {__MATSUGIT_TEMPLATES__: templates}});
const html = await readFile(path.join(root, 'src/index.html'), 'utf8');
const css = await readFile(path.join(root, 'src/style.css'), 'utf8');
const hostCss = await readFile(fileURLToPath(import.meta.resolve('@openai/mcp-extensions/app/styles.css')), 'utf8');
const app = html.replace('/* APP_STYLES */', () => hostCss + '\n' + css)
  .replace('/* APP_SCRIPT */', () => browser.outputFiles[0].text.replaceAll('</script', '<\\/script'));
// The app is served from the runtime embedded in server.mjs; app-html.mjs reads it
// back for tests and the demo, so no second copy is committed.
// Freeze the UI, Python modules and renderer assets into this server version.
// Codex may replace its installed cache while the process still serves viewers.
const files = {}, texts = {};
async function include(relative) {
  let bytes = await readFile(path.join(root, '..', relative));
  // Assets stored compressed in the repository are embedded expanded: the runtime
  // compresses better as a whole, and the extracted renderer gets the plain file.
  if (relative.endsWith('.gz')) { bytes = gunzipSync(bytes); relative = relative.slice(0, -3); }
  // Text goes in as text, which compresses far better than base64.
  const text = bytes.toString('utf8');
  if (Buffer.from(text, 'utf8').equals(bytes)) texts[relative] = text;
  else files[relative] = bytes.toString('base64');
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
await includeTree('matsugit/dependencies');
await includeTree('matsugit/themes/default');
const mergeWorker = await build({entryPoints: [path.join(root, 'src/merge-worker.mjs')], bundle: true,
  write: false, platform: 'node', format: 'cjs', target: 'node22', legalComments: 'inline', metafile: true, plugins: [englishZod]});
texts['codex-plugin/merge-worker.cjs'] = mergeWorker.outputFiles[0].text;
await writeFile(path.join(out, 'merge-worker.cjs'), mergeWorker.outputFiles[0].text);
// Brotli at full quality: about a quarter smaller than gzip here, and the output
// carries no OS or time stamp, so macOS and Linux builds match byte for byte.
const packed = brotliCompressSync(Buffer.from(JSON.stringify({app, files, texts})), {params: {
  [constants.BROTLI_PARAM_QUALITY]: 11, [constants.BROTLI_PARAM_LGWIN]: 24, [constants.BROTLI_PARAM_SIZE_HINT]: 0}});
const runtime = packed.toString('base64');
const server = await build({entryPoints: [path.join(root, 'src/server.mjs')], bundle: true, loader: {'.md': 'text'},
  outfile: path.join(out, 'server.mjs'), platform: 'node', format: 'esm', target: 'node22',
  define: {__MATSUGIT_RUNTIME__: JSON.stringify(runtime)},
  legalComments: 'inline', metafile: true, plugins: [englishZod], banner: {js: "import {createRequire as __createRequire} from 'node:module'; const require = __createRequire(import.meta.url);"}});
// The browser fallback has no dependencies; it runs server.mjs beside it.
await build({entryPoints: [path.join(root, 'src/browser.mjs')], bundle: true, outfile: path.join(out, 'browser.mjs'),
  platform: 'node', format: 'esm', target: 'node22', legalComments: 'inline'});
await writeFile(path.join(out, 'THIRD-PARTY-NOTICES.txt'),
  await collectNotices([browser.metafile, server.metafile, mergeWorker.metafile, story.metafile]));
