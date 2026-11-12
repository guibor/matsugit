// The workspace page as the plugin serves it, read back from the runtime embedded
// in bundle/server.mjs. Tests, the demo and screenshot provenance use this
// instead of a second committed copy of the page.
import fs from 'node:fs';
import {brotliDecompressSync} from 'node:zlib';

export function bundledApp(server = new URL('./bundle/server.mjs', import.meta.url)) {
  const source = fs.readFileSync(server, 'utf8');
  const match = /new PluginRuntime\("([A-Za-z0-9+/=]+)"\)/.exec(source);
  if (!match) throw Error('No embedded runtime in ' + server);
  return JSON.parse(brotliDecompressSync(Buffer.from(match[1], 'base64'))).app;
}

// `node app-html.mjs > app.html` writes the page for inspection.
if (import.meta.url === `file://${process.argv[1]}`) process.stdout.write(bundledApp());
