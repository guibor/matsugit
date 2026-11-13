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
const starting = new Map();

function stop(child) {
  child.stdout?.destroy();
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill();
  const timer = setTimeout(() => child.kill('SIGKILL'), 2000);
  timer.unref();
  child.once('exit', () => clearTimeout(timer));
}

function ready(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    let text = '';
    const finish = (error, value) => {
      clearTimeout(timer);
      child.off('error', failed); child.off('exit', exited); child.stdout.off('data', received);
      error ? reject(error) : resolve(value);
    };
    const failed = error => finish(error);
    const exited = () => finish(Error('The browser workspace stopped before it was ready.'));
    const received = chunk => {
      text += chunk;
      if (Buffer.byteLength(text) > 65536) return finish(Error('Browser startup response exceeded the size limit.'));
      if (text.includes('\n')) finish(null, text.slice(0, text.indexOf('\n')));
    };
    const timer = setTimeout(() => finish(Error('The browser workspace did not start in time.')), timeoutMs);
    child.once('error', failed); child.once('exit', exited);
    child.stdout.setEncoding('utf8'); child.stdout.on('data', received);
  });
}

/** Start (or reuse) the browser workspace for file, or the sample when file is null. */
export async function openInBrowser(file, {script = path.join(here, 'browser.mjs'), env = process.env,
  view = {}, timeoutMs = 30000} = {}) {
  const options = Object.fromEntries(['layout', 'format', 'editor', 'autosave']
    .filter(name => view[name] !== undefined).map(name => [name, view[name]]));
  const key = JSON.stringify([file || '', options]);
  if (starting.has(key)) return starting.get(key);
  const existing = running.get(key);
  if (existing && existing.child.exitCode === null && existing.child.signalCode === null) {
    return {url: existing.url, path: file || null, reused: true, launched: openUrl(existing.url, env)};
  }
  const child = spawn(process.execPath, [script, file || '', JSON.stringify(options)],
    {detached: true, stdio: ['ignore', 'pipe', 'ignore'], env});
  const pending = (async () => {
    try {
      const data = JSON.parse(await ready(child, timeoutMs));
      if (data?.error) throw Error(data.error);
      if (!data || typeof data.url !== 'string'
          || !/^http:\/\/127\.0\.0\.1:[0-9]+\/[\w-]{32}\/$/.test(data.url))
        throw Error('The browser workspace returned an invalid local address.');
      const url = new URL(data.url);
      if (!url.port || Number(url.port) < 1) throw Error('Invalid browser port.');
      child.stdout.destroy(); child.unref();
      running.set(key, {url: data.url, child});
      child.once('exit', () => { if (running.get(key)?.child === child) running.delete(key); });
      return {url: data.url, path: data.path, reused: false, launched: openUrl(data.url, env)};
    } catch (error) {
      stop(child);
      throw error;
    } finally { starting.delete(key); }
  })();
  starting.set(key, pending);
  return pending;
}

/** What the agent reads instead of a panel. */
export function browserResult(opened, name) {
  return {opened: 'browser', url: opened.url, path: opened.path, name,
    message: (opened.launched ? 'Browser launch requested for the matsugit workspace'
      : 'The matsugit browser workspace is ready') +
      ` at ${opened.url}. Tell the user in one line, with the address; if no tab appeared, they can open the link. It is private to this computer and stops five minutes after the tab closes. ` +
      'Keep editing the file on disk as usual: the open tab takes your changes in. Ask AI in the browser copies requests for the user to paste here.'};
}
