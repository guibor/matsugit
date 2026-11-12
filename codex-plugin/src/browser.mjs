// The browser fallback: the same workspace, in an ordinary browser tab, for when no
// chat host shows MCP Apps (no plugin, another agent, or a host that failed).
//
// It runs the shipped server (server.mjs) over stdio exactly as Cursor or Codex
// would, and plays the host's part in a page served on this computer only:
// - it listens on 127.0.0.1, on a port the system picks;
// - every address carries a random token that only the person who ran it gets;
// - requests naming another host (DNS rebinding) or coming from another origin
//   are refused, so other web pages cannot reach the document;
// - it stops by itself five minutes after the last tab closes.
// Usage: node browser.mjs [file] — prints one JSON line {url, path} when ready.
import http from 'node:http';
import path from 'node:path';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
// Hidden tabs may have timers throttled to one minute; allow several beats.
const IDLE = Number(process.env.MATSUGIT_BROWSER_IDLE_MS) || 5 * 60_000;
const UNUSED = Number(process.env.MATSUGIT_BROWSER_UNUSED_MS) || 10 * 60_000;
const BODY_LIMIT = 16 * 1024 * 1024;

export function startServer(serverPath = path.join(here, 'server.mjs')) {
  const child = spawn(process.execPath, [serverPath], {stdio: ['pipe', 'pipe', 'inherit']});
  const pending = new Map();
  let next = 1, buffer = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    buffer += chunk;
    for (let end; (end = buffer.indexOf('\n')) >= 0;) {
      const line = buffer.slice(0, end).trim(); buffer = buffer.slice(end + 1);
      if (!line) continue;
      let message; try { message = JSON.parse(line); } catch { continue; }
      const waiter = message.id !== undefined && pending.get(message.id);
      if (!waiter) continue;
      pending.delete(message.id);
      message.error ? waiter.reject(Object.assign(Error(message.error.message), {rpc: message.error})) : waiter.resolve(message.result);
    }
  });
  let closed = false;
  const rejectPending = error => { closed = true; for (const waiter of pending.values()) waiter.reject(error); pending.clear(); };
  child.on('error', rejectPending);
  child.stdin.on('error', rejectPending);
  const exited = new Promise(resolve => child.on('exit', resolve));
  exited.then(() => rejectPending(Error('The matsugit server stopped.')));
  const send = message => child.stdin.write(JSON.stringify({jsonrpc: '2.0', ...message}) + '\n');
  const request = (method, params) => new Promise((resolve, reject) => {
    if (closed || child.exitCode !== null) return reject(Error('The matsugit server stopped.'));
    const id = next++; pending.set(id, {resolve, reject}); send({id, method, params});
  });
  const ready = request('initialize', {protocolVersion: '2025-06-18', capabilities: {},
    clientInfo: {name: 'matsugit-browser', version: '1.0.0'}}).then(result => { send({method: 'notifications/initialized'}); return result; });
  return {request, ready, exited, close: () => child.kill()};
}

export function hostPage(token, title, beat = 15000) {
  const escape = text => text.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escape(title)} · matsugit</title>
<style>html,body,iframe{margin:0;border:0;width:100%;height:100%;display:block;overflow:hidden;background:#fff}
@media (prefers-color-scheme:dark){html,body{background:#1e1e1e}}</style></head><body>
<iframe src="/${token}/app" id="app" title="matsugit workspace" allow="clipboard-write; fullscreen"></iframe>
<script>
const base='/${token}/', frame=document.getElementById('app');
const dark=matchMedia('(prefers-color-scheme: dark)');
const context=()=>({theme:dark.matches?'dark':'light',displayMode:'fullscreen',availableDisplayModes:['fullscreen'],platform:'web'});
const post=(path,body)=>fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
const beat=()=>fetch(base+'alive',{method:'POST'}).catch(()=>{});
beat(); setInterval(beat,${beat});
dark.addEventListener('change',()=>frame.contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/host-context-changed',params:context()},'*'));
addEventListener('message',async event=>{
  if(event.source!==frame.contentWindow||event.data?.jsonrpc!=='2.0')return;
  const message=event.data, reply=value=>event.source.postMessage({jsonrpc:'2.0',id:message.id,...value},'*');
  const answer=result=>reply({result}), refuse=(code,text)=>reply({error:{code,message:text}});
  switch(message.method){
    case 'ui/notifications/initialized': {
      const result=await post('result',{});
      event.source.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result},'*');return;
    }
    case 'ui/initialize': return answer({protocolVersion:'2026-01-26',hostInfo:{name:'matsugit in the browser',version:'1.0.0'},
      hostCapabilities:{serverTools:{},serverResources:{},openLinks:{}},hostContext:context()});
    case 'ui/open-link': {
      const url=String(message.params?.url||'');
      if(/^https?:/i.test(url))open(url,'_blank','noopener,noreferrer');
      return answer({});
    }
    case 'ui/request-display-mode': return answer({mode:'fullscreen'});
    case 'ui/update-model-context': return answer({});
    case 'tools/call': case 'resources/read': {
      try{reply(await post('rpc',{method:message.method,params:message.params}));}
      catch(error){refuse(-32603,'The matsugit server is not running. Run the open command again.');}
      return;
    }
  }
  // No chat here: the workspace then offers to copy requests for the agent instead.
  if(message.id!==undefined)refuse(-32601,'Not available in the browser');
});
</script></body></html>`;
}

// The app page carries its own strict policy; framing is limited to this origin.
const APP_POLICY = "default-src 'none'; script-src 'unsafe-inline' data: blob:; style-src 'unsafe-inline' data: blob:; " +
  "img-src data: blob:; font-src data: blob:; media-src data: blob:; frame-src blob:; connect-src 'none'; base-uri https://matsugit.invalid; form-action 'none'; frame-ancestors 'self'";
const HOST_POLICY = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

export async function serve({file, serverPath, port = 0, onIdle = () => process.exit(0)} = {}) {
  const mcp = startServer(serverPath);
  const terminate = () => { mcp.close(); process.exit(0); };
  process.once('SIGTERM', terminate);
  process.once('SIGINT', terminate);
  try {
  await mcp.ready;
  const absolute = file ? path.resolve(file) : null;
  if (absolute && !fs.existsSync(absolute)) { mcp.close(); throw Error('No such file: ' + absolute); }
  const open = () => absolute ? mcp.request('tools/call', {name: 'matsugit_open', arguments: {path: absolute}})
    : mcp.request('tools/call', {name: 'matsugit_workspace', arguments: {}});
  const first = await open();
  if (first.isError) { mcp.close(); throw Error(first.content?.map(item => item.text).join(' ') || 'The document could not be opened.'); }
  const app = (await mcp.request('resources/read', {uri: 'ui://matsugit/workspace-v1'})).contents[0].text;
  const token = crypto.randomBytes(24).toString('base64url');
  let seen = 0;
  const started = Date.now();
  const server = http.createServer(async (req, res) => {
    const deny = (code, text) => { res.writeHead(code, {'Content-Type': 'text/plain'}); res.end(text); };
    const {port: actual} = server.address();
    const hosts = [`127.0.0.1:${actual}`, `localhost:${actual}`];
    if (!hosts.includes(req.headers.host)) return deny(403, 'Forbidden');
    const origin = req.headers.origin;
    if (origin && !hosts.some(host => origin === 'http://' + host)) return deny(403, 'Forbidden');
    const url = new URL(req.url, 'http://' + req.headers.host);
    const prefix = `/${token}/`;
    // Compare the token in constant time; anything else is not found.
    const given = Buffer.from(url.pathname.slice(1, 1 + token.length));
    if (!url.pathname.startsWith('/') || given.length !== token.length || !crypto.timingSafeEqual(given, Buffer.from(token))
        || url.pathname[token.length + 1] !== '/') return deny(404, 'Not found');
    const route = url.pathname.slice(prefix.length);
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    try {
      if (req.method === 'GET' && route === '') {
        res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': HOST_POLICY});
        return res.end(hostPage(token, absolute ? path.basename(absolute) : 'Sample deck', Math.min(15000, Math.floor(IDLE / 4))));
      }
      if (req.method === 'GET' && route === 'app') {
        res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': APP_POLICY});
        return res.end(app);
      }
      if (req.method !== 'POST') return deny(404, 'Not found');
      if (!/^application\/json\b/.test(req.headers['content-type'] || '') && route !== 'alive') return deny(415, 'JSON only');
      let size = 0; const chunks = [];
      for await (const chunk of req) { size += chunk.length; if (size > BODY_LIMIT) return deny(413, 'Too large'); chunks.push(chunk); }
      const reply = value => { res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(value)); };
      if (route === 'alive') { seen = Date.now(); return reply({}); }
      if (route === 'result') { seen = Date.now(); return reply(await open()); }
      if (route === 'rpc') {
        const message = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if (!['tools/call', 'resources/read'].includes(message.method)) return reply({error: {code: -32601, message: 'Method not found'}});
        try { return reply({result: await mcp.request(message.method, message.params)}); }
        catch (error) { return reply({error: error.rpc || {code: -32603, message: error.message}}); }
      }
      deny(404, 'Not found');
    } catch (error) {
      if (!res.headersSent) deny(500, 'The request failed.');
    }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  const stop = () => {
    clearInterval(timer); server.close(); server.closeAllConnections(); mcp.close();
    process.removeListener('SIGTERM', terminate); process.removeListener('SIGINT', terminate);
  };
  const timer = setInterval(() => {
    const now = Date.now();
    if (seen ? now - seen > IDLE : now - started > UNUSED) { stop(); onIdle(); }
  }, Math.min(5000, IDLE / 2));
  mcp.exited.then(() => { stop(); onIdle(); });
  return {url: `http://127.0.0.1:${server.address().port}/${token}/`, path: absolute, stop};
  } catch (error) {
    mcp.close();
    process.removeListener('SIGTERM', terminate); process.removeListener('SIGINT', terminate);
    throw error;
  }
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url))) {
  try {
    // Whoever started this may stop reading once it has the address.
    process.stdout.on('error', () => {});
    const opened = await serve({file: process.argv[2]});
    process.stdout.write(JSON.stringify({url: opened.url, path: opened.path}) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({error: error.message}) + '\n');
    process.exit(1);
  }
}
