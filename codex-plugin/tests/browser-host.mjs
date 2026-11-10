// Isolated test host only. The shipped plugin uses stdio, never an HTTP listener.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
const root = fileURLToPath(new URL('../../', import.meta.url));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-browser-test-'));
const fixture = process.env.MATSUGIT_SHOWCASE_SOURCE;
const standardOnly = process.env.MATSUGIT_STANDARD_MCP === '1';
const chatMode = process.env.MATSUGIT_TEST_CHAT || '';
const downloadMode = process.env.MATSUGIT_TEST_DOWNLOAD || 'browser';
const resultMode = process.env.MATSUGIT_TEST_RESULT || 'full';
// Most tests assert exactly when the file is written, so they opt out of autosave.
const openOptions = {tips: false, ...(process.env.MATSUGIT_TEST_DEFAULT_SAVE === '1' ? {} : {autosave: false}),
  ...JSON.parse(process.env.MATSUGIT_TEST_OPEN_OPTIONS || '{}')};
const cursorHost = process.env.MATSUGIT_TEST_HOST === 'cursor';
function hostResult(result) {
  if (resultMode === 'full') return result;
  const {_meta, ...rest} = result;
  if (resultMode === 'text-only') delete rest.structuredContent;
  return rest;
}
const messages = [];
let failChat = false;
// A test may supply its own real file and publishing configuration.
const inPlace = process.env.MATSUGIT_TEST_SOURCE;
const source = inPlace || path.join(temporary, fixture ? path.basename(fixture) : 'pilot.md');
const inherited = path.join(temporary, 'removed-cwd');
fs.mkdirSync(inherited);
if (!inPlace) fs.copyFileSync(fixture || new URL('./workspace.md', import.meta.url), source);
let client, opened, session, app;
async function start() {
client = new Client({name: 'matsugit-browser-test', version: '1.0.0'});
await client.connect(new StdioClientTransport({command: process.execPath,
  args: [path.join(root, 'codex-plugin/bundle/server.mjs')], cwd: inherited,
  env: {...process.env, PWD: inherited, MATSUGIT_CONFIG: process.env.MATSUGIT_TEST_CONFIG || path.join(temporary, 'absent.json'),
    ...(downloadMode === 'blocked' ? {HOME:temporary} : {}),
    MATSUGIT_RECOVERY_DIR: path.join(temporary, 'recovery'),
    MATSUGIT_PUBLICATION_STATE: path.join(temporary, 'publication')}, stderr: 'inherit'}));
opened = await client.callTool({name: 'matsugit_open', arguments: {path: source, ...openOptions}});
session = opened.structuredContent.session;
app = (await client.readResource({uri: 'ui://matsugit/workspace-v1'})).contents[0].text;
}
await start();
if (process.platform !== 'win32') fs.rmdirSync(inherited);
const host = `<!doctype html><meta charset="utf-8"><style>html,body,iframe{margin:0;border:0;width:100%;height:100%;display:block;overflow:hidden}</style>
${cursorHost ? '<input id="chat-prompt" aria-label="Host chat prompt"><style>#chat-prompt{display:block;width:100%;height:32px}iframe{height:320px}</style>' : ''}
<iframe src="/app" id="app" allow="clipboard-write" ${downloadMode === 'browser' ? '' : 'sandbox="allow-scripts allow-same-origin allow-forms allow-modals"'}></iframe><script>
window.downloadRequests=[];window.rejectDownload=false;window.exportRequests=0;
window.contextUpdates=0;window.displayRequests=[];
window.addEventListener('message',async e=>{if(e.source!==document.getElementById('app').contentWindow||e.data?.jsonrpc!=='2.0')return;
const message=e.data;
if (${cursorHost} && message.method==='ui/notifications/size-changed') {
  document.getElementById('app').style.height=Math.min(800,message.params.height)+'px';return;
}
if(message.method==='ui/update-model-context') {
  window.contextUpdates++;
  if (${cursorHost}) document.getElementById('chat-prompt').focus();
}
if(message.method==='ui/request-display-mode') window.displayRequests.push(message.params.mode);
if(message.method==='ui/notifications/initialized'){
const result=await(await fetch(location.search.includes('file')?'/file-result':location.search.includes('untitled')?'/untitled-result':'/result')).json();
e.source.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:result},'*');return;}
if(message.id===undefined)return;
if(message.method==='tools/call'&&message.params.name==='matsugit_action'&&message.params.arguments?.action==='export')window.exportRequests++;
if(message.method==='ui/download-file'){
  const reply=value=>e.source.postMessage({jsonrpc:'2.0',id:message.id,...value},'*');
  const mode=${JSON.stringify(downloadMode)},params=message.params;
  if(mode==='browser'||mode==='blocked'){reply({error:{code:-32601,message:'Method not found'}});return;}
  let blob,name;
  if(mode==='legacy'){
    if(!(params.blob instanceof Blob)||!params.name){reply({error:{code:-32602,message:'Invalid MCP file download params'}});return;}
    blob=params.blob;name=params.name;
  }else{
    const item=params.contents?.[0]?.resource;
    if(!item?.blob){reply({error:{code:-32602,message:'Expected resource contents'}});return;}
    blob=new Blob([Uint8Array.from(atob(item.blob),c=>c.charCodeAt(0))],{type:item.mimeType});
    name=decodeURIComponent(new URL(item.uri).pathname.split('/').pop());
  }
  window.downloadRequests.push({name,size:blob.size,type:blob.type});
  if(window.rejectDownload){window.rejectDownload=false;reply({result:{isError:true}});return;}
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=name;document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),60000);reply({result:{}});return;
}
try{const result=await(await fetch('/rpc',{method:'POST',body:JSON.stringify(message)})).json();e.source.postMessage({jsonrpc:'2.0',id:message.id,...result},'*');}
catch(error){e.source.postMessage({jsonrpc:'2.0',id:message.id,error:{code:-32603,message:error.message}},'*');}
});</script>`;
const server = http.createServer(async (req, res) => {
  try {
    res.setHeader('Cache-Control', 'no-store');
    if (req.url === '/app') {
      res.setHeader('Content-Type', 'text/html');
      res.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline' data: blob:; style-src 'unsafe-inline' data: blob:; img-src data: blob:; font-src data: blob:; frame-src blob:; base-uri https://matsugit.invalid; connect-src 'none'");
      return res.end(app);
    }
    if (req.url === '/result') return res.end(JSON.stringify(hostResult(await client.callTool({name: 'matsugit_open', arguments: {path: source, ...openOptions}}))));
    if (req.url === '/test-messages') return res.end(JSON.stringify(messages));
    if (req.url === '/test-fail-chat' && req.method === 'POST') { failChat = true; return res.end('{}'); }
    if (req.url === '/untitled-result') return res.end(JSON.stringify(await client.callTool({name: 'matsugit_workspace', arguments: {}})));
    if (req.url === '/restart' && req.method === 'POST') {
      await client.close(); fs.mkdirSync(inherited); await start(); fs.rmdirSync(inherited);
      return res.end('{}');
    }
    if (req.url === '/file-result') return res.end(JSON.stringify({structuredContent: {file: {name: 'pilot.md', resourceUri: 'host://selected/pilot'}, autosave: openOptions.autosave, tips: openOptions.tips}, content: []}));
    if (req.url === '/rpc') {
      let raw = ''; for await (const chunk of req) raw += chunk;
      const message = JSON.parse(raw), params = message.params;
      let result = {};
      if (message.method === 'ui/initialize') result = {protocolVersion: '2026-01-26', hostInfo: {name: 'Isolated test host', version: '1.0.0'},
        hostCapabilities: {serverTools: {}, serverResources: {}, openLinks: {},
          ...(downloadMode === 'standard' ? {downloadFile:{}} : {}),
          ...(chatMode ? {message:{text:{}}} : {}),
          experimental:{...(standardOnly ? {} : {'openai/resource':{}}), ...(chatMode === 'extended' ? {'openai/message':{}} : {})}},
        hostContext: cursorHost ? {theme:'light', displayMode:'inline', availableDisplayModes:['inline'],
          userAgent:'cursor', containerDimensions:{maxHeight:800}} : {theme: 'light', displayMode: 'fullscreen'}};
      else if (message.method === 'ui/message') {
        if (!chatMode) throw Error('Chat unsupported');
        messages.push(params);
        await new Promise(resolve=>setTimeout(resolve,200));
        if (failChat) { failChat = false; throw Error('Simulated lost acknowledgement'); }
      }
      else if (standardOnly && message.method.startsWith('openai/')) throw Error('Host has no OpenAI extensions');
      else if (message.method === 'tools/call') result = hostResult(await client.callTool(standardOnly ? params : {...params, _meta: {'openai/resource': {path: source}}}));
      else if (message.method === 'resources/read') {
        const latest = await client.callTool({name: 'matsugit_read', arguments: {session}});
        result = {contents: [{uri: params.uri, text: latest.structuredContent.source, _meta: {'openai/resource': latest.structuredContent}}]};
      } else if (message.method === 'openai/resources/write') {
        result = (await client.callTool({name: 'matsugit_save', arguments: {session, text: params.text, etag: params.ifMatch}})).structuredContent;
      }
      return res.end(JSON.stringify({result}));
    }
    res.setHeader('Content-Type', 'text/html'); res.end(host);
  } catch (error) { res.end(JSON.stringify({error: {code: -32603, message: error.message}})); }
});
server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({port: server.address().port, source, downloads:path.join(temporary,'Downloads'),
  recovery: path.join(temporary, 'recovery'), publication: path.join(temporary, 'publication')})));
async function close() { server.close(); await client.close(); fs.rmSync(temporary, {recursive: true, force: true}); process.exit(); }
process.once('SIGTERM', close); process.once('SIGINT', close);
