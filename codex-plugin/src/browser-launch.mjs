// When the chat cannot show the workspace (Claude Code is text-only), the open
// tools put it in the user's browser instead, through browser.mjs beside this file.
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
// Hosts that render MCP Apps announce this extension (ext-apps EXTENSION_ID).
export const UI_EXTENSION = 'io.modelcontextprotocol/ui';
// Known hosts that call tools but never render MCP Apps. Kept to hosts we have
// checked, so a panel host that does not announce the extension is not affected.
const TEXT_ONLY = /^claude-code$/i;

/** Who is calling: the per-request envelope (2026 protocol) or the initialize handshake (2025). */
export function clientOf(server, context) {
  const envelope = context?.mcpReq?.envelope || context?.mcpReq?._meta || {};
  const low = server?.server;
  return {info: envelope['io.modelcontextprotocol/clientInfo'] || low?.getClientVersion?.(),
    capabilities: envelope['io.modelcontextprotocol/clientCapabilities'] || low?.getClientCapabilities?.()};
}

/** MATSUGIT_BROWSER=1 always uses the browser, =0 never; otherwise only a known text-only host. */
export function wantsBrowser(client, env = process.env) {
  if (env.MATSUGIT_BROWSER === '1') return true;
  if (env.MATSUGIT_BROWSER === '0') return false;
  if (client?.capabilities?.extensions?.[UI_EXTENSION]) return false;
  return TEXT_ONLY.test(client?.info?.name || '');
}

export function openUrl(url, env = process.env) {
  if (env.MATSUGIT_BROWSER_OPEN === '0') return false;
  const [command, args] = process.platform === 'darwin' ? ['open', [url]]
    : process.platform === 'win32' ? ['rundll32', ['url.dll,FileProtocolHandler', url]] : ['xdg-open', [url]];
  try {
    const child = spawn(command, args, {detached: true, stdio: 'ignore'});
    child.on('error', () => {});
    child.unref();
    return true;
  } catch { return false; }
}

const running = new Map();

/** Start (or reuse) the browser workspace for file, or the sample when file is null. */
export async function openInBrowser(file, {script = path.join(here, 'browser.mjs'), env = process.env} = {}) {
  const key = file || '';
  const existing = running.get(key);
  if (existing && existing.child.exitCode === null && existing.child.signalCode === null) {
    return {url: existing.url, path: file || null, reused: true, launched: openUrl(existing.url, env)};
  }
  const child = spawn(process.execPath, [script, ...(file ? [file] : [])],
    {detached: true, stdio: ['ignore', 'pipe', 'ignore'], env});
  const line = await new Promise((resolve, reject) => {
    let text = '';
    const timer = setTimeout(() => reject(Error('The browser workspace did not start within 60 seconds.')), 60_000);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', () => { clearTimeout(timer); resolve(text); });
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      text += chunk;
      if (text.includes('\n')) { clearTimeout(timer); resolve(text.slice(0, text.indexOf('\n'))); }
    });
  });
  let data;
  try { data = JSON.parse(line); } catch { throw Error('The browser workspace did not start.'); }
  if (data.error) throw Error(data.error);
  child.stdout.destroy();
  child.unref();
  running.set(key, {url: data.url, child});
  return {url: data.url, path: data.path, reused: false, launched: openUrl(data.url, env)};
}

/** What the agent reads instead of a panel. */
export function browserResult(opened, name) {
  return {opened: 'browser', url: opened.url, path: opened.path, name,
    message: (opened.launched ? 'This chat cannot show the matsugit panel, so the workspace opened in the user\'s browser'
      : 'This chat cannot show the matsugit panel; the workspace is ready in the browser') +
      ` at ${opened.url}. Tell the user in one line, with the address. It is private to this computer and stops a minute after the tab closes. ` +
      'Keep editing the file on disk as usual: the open tab takes your changes in. Ask AI in the browser copies requests for the user to paste here.'};
}
