import {readFile, readdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const licenseDirectory = fileURLToPath(new URL('./licenses/', import.meta.url));
const supplements = new Map([
  ['@cfworker/json-schema@4.1.4', path.join(licenseDirectory, 'cfworker-json-schema-4.1.4.txt')],
]);

export async function collectNotices(metafiles, cwd = process.cwd(), overrides = supplements) {
  const packages = new Set();
  for (const graph of metafiles) {
    for (const file of Object.keys(graph.inputs)) {
      const parts = file.replaceAll('\\', '/').split('node_modules/');
      if (parts.length < 2) continue;
      const tail = parts.at(-1).split('/');
      const name = tail.slice(0, tail[0].startsWith('@') ? 2 : 1).join('/');
      packages.add(path.resolve(cwd, parts.slice(0, -1).join('node_modules/'), 'node_modules', name));
    }
  }
  const notices = [];
  for (const directory of [...packages].sort()) {
    const info = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
    const files = (await readdir(directory, {withFileTypes: true}))
      .filter(entry => entry.isFile() && /^(licen[sc]e|notice|copying)(\.|$)/i.test(entry.name))
      .map(entry => path.join(directory, entry.name)).sort();
    const key = `${info.name}@${info.version}`;
    if (!files.length && overrides.has(key)) files.push(overrides.get(key));
    const texts = await Promise.all(files.map(file => readFile(file, 'utf8')));
    if (!texts.length || texts.some(text => !text.trim())) {
      throw new Error(`Missing dependency license text: ${key}. Supply a verified, version-specific notice before bundling.`);
    }
    notices.push(`${info.name} ${info.version} (${info.license || 'see notice'})`, ...texts);
  }
  return notices.join('\n\n') + '\n';
}
