// Isolated test host only. The shipped plugin uses stdio, never an HTTP listener.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
const root = fileURLToPath(new URL('../../', import.meta.url));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'folioforge-browser-test-'));
const source = path.join(temporary, 'pilot.md');
const inherited = path.join(temporary, 'removed-cwd');
fs.mkdirSync(inherited);
fs.copyFileSync(new URL('./workspace.md', import.meta.url), source);
const client = new Client({name: 'folioforge-browser-test', version: '1.0.0'});
await client.connect(new StdioClientTransport({command: process.execPath,
  args: [path.join(root, 'codex-plugin/bundle/server.mjs')], cwd: inherited,
  env: {...process.env, PWD: inherited, FOLIOFORGE_CONFIG: path.join(temporary, 'absent.json')}, stderr: 'inherit'}));
if (process.platform !== 'win32') fs.rmdirSync(inherited);
const opened = await client.callTool({name: 'folioforge_open', arguments: {path: source}});
const session = opened.structuredContent.session;
const app = (await client.readResource({uri: 'ui://folioforge/workspace-v1'})).contents[0].text;
const host = `<!doctype html><meta charset="utf-8"><style>html,body,iframe{margin:0;border:0;width:100%;height:100%;display:block;overflow:hidden}</style>
<iframe src="/app" id="app" allow="clipboard-write"></iframe><script>
window.addEventListener('message',async e=>{if(e.source!==document.getElementById('app').contentWindow||e.data?.jsonrpc!=='2.0')return;
const message=e.data;
if(message.method==='ui/notifications/initialized'){
const result=await(await fetch(location.search.includes('file')?'/file-result':'/result')).json();
e.source.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result},'*');return;}
if(message.id===undefined)return;
try{const result=await(await fetch('/rpc',{method:'POST',body:JSON.stringify(message)})).json();e.source.postMessage({jsonrpc:'2.0',id:message.id,...result},'*');}
catch(error){e.source.postMessage({jsonrpc:'2.0',id:message.id,error:{code:-32603,message:error.message}},'*');}
});</script>`;
const server = http.createServer(async (req, res) => {
  try {
    res.setHeader('Cache-Control', 'no-store');
    if (req.url === '/app') {
      res.setHeader('Content-Type', 'text/html');
      res.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline' data: blob:; style-src 'unsafe-inline' data: blob:; img-src data: blob:; font-src data: blob:; frame-src blob:; base-uri https://folioforge.invalid; connect-src 'none'");
      return res.end(app);
    }
    if (req.url === '/result') return res.end(JSON.stringify(opened));
    if (req.url === '/file-result') return res.end(JSON.stringify({structuredContent: {file: {name: 'pilot.md', resourceUri: 'host://selected/pilot'}}, content: []}));
    if (req.url === '/rpc') {
      let raw = ''; for await (const chunk of req) raw += chunk;
      const message = JSON.parse(raw), params = message.params;
      let result = {};
      if (message.method === 'ui/initialize') result = {protocolVersion: '2026-01-26', hostInfo: {name: 'Isolated test host', version: '1.0.0'},
        hostCapabilities: {serverTools: {}, serverResources: {}, openLinks: {}, experimental: {'openai/resource': {}}}, hostContext: {theme: 'light', displayMode: 'fullscreen'}};
      else if (message.method === 'tools/call') result = await client.callTool({...params, _meta: {'openai/resource': {path: source}}});
      else if (message.method === 'resources/read') {
        const latest = await client.callTool({name: 'folioforge_read', arguments: {session}});
        result = {contents: [{uri: params.uri, text: latest._meta.source, _meta: {'openai/resource': latest.structuredContent}}]};
      } else if (message.method === 'openai/resources/write') {
        result = (await client.callTool({name: 'folioforge_save', arguments: {session, text: params.text, etag: params.ifMatch}})).structuredContent;
      }
      return res.end(JSON.stringify({result}));
    }
    res.setHeader('Content-Type', 'text/html'); res.end(host);
  } catch (error) { res.end(JSON.stringify({error: {code: -32603, message: error.message}})); }
});
server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({port: server.address().port, source})));
async function close() { server.close(); await client.close(); fs.rmSync(temporary, {recursive: true, force: true}); process.exit(); }
process.once('SIGTERM', close); process.once('SIGINT', close);
