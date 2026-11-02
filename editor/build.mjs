import {build} from 'esbuild';
import {readFile, readdir, writeFile} from 'node:fs/promises';

await build({entryPoints: ['main.js'], bundle: true, minify: true, format: 'esm',
  legalComments: 'linked', outfile: '../matsugit/editor_assets/editor.js'});

const notices = [];
async function collect(directory) {
  for (const entry of await readdir(directory, {withFileTypes: true})) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    const path = `${directory}/${entry.name}`;
    if (entry.name.startsWith('@')) { await collect(path); continue; }
    const manifest = JSON.parse(await readFile(`${path}/package.json`, 'utf8'));
    const licenses = (await readdir(path)).filter(name => /^licen[cs]e(?:\.|$)/i.test(name));
    for (const license of licenses) {
      notices.push(`${manifest.name} ${manifest.version} (${manifest.license || 'see below'})\n${await readFile(`${path}/${license}`, 'utf8')}`);
    }
  }
}
await collect('node_modules');
await writeFile('../matsugit/editor_assets/THIRD-PARTY-LICENSES.txt', notices.sort().join('\n\n--------------------\n\n'));
